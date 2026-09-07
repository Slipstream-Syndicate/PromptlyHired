"""Jobs enter the system by the user pasting a link. There is no feed.

Every job-board API worth having is paid (JSearch), partner-only (LinkedIn,
Indeed) or retired. Scraping them in bulk violates their terms and gets IPs
banned. Fetching one page a user explicitly asked for is a different act, and
it is the only free, defensible way to get a job into this app.
"""

from __future__ import annotations

import hashlib
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import Company, GeneratedDocument, Job, JobMatch, UserJob
from app.rate_limit import ai_rate_limit
from app.routers.resumes import active_resume, require_active_resume
from app.schemas import (
    GeneratedDocumentOut,
    JobDetailOut,
    JobMatchOut,
    JobOut,
    clean_text,
)
from app.services import ai, job_url
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

SOURCE_PASTED = "pasted"
# Below this a "description" is a cookie banner, not a job advert.
MIN_DESCRIPTION_CHARS = 200


class JobFromUrl(BaseModel):
    url: str = Field(min_length=8, max_length=2048)


class JobFromText(BaseModel):
    """Fallback for sites that block server-side fetches."""

    text: str = Field(min_length=MIN_DESCRIPTION_CHARS, max_length=40_000)
    title: str | None = Field(default=None, max_length=300)
    company: str | None = Field(default=None, max_length=200)
    url: str | None = Field(default=None, max_length=2048)


def _normalize_company(name: str) -> str:
    return " ".join(name.lower().split())[:255]


def _get_or_create_company(db, name: str) -> Company:
    name = (name or "").strip() or "Unknown company"
    key = _normalize_company(name)
    company = db.scalar(select(Company).where(Company.normalized_name == key))
    if company is None:
        company = Company(name=name[:255], normalized_name=key)
        db.add(company)
        db.flush()
    return company


def _store_job(db, *, title, company_name, location, description, url, publisher) -> Job:
    """Upsert on a stable identity so re-pasting the same job reuses the row.

    The URL is the natural key, but it can be long and carry tracking
    parameters, so it is hashed. Falls back to the text itself when there is no
    URL, which keeps pasted-text jobs deduplicated too.
    """
    basis = (url or "") or f"{title}|{company_name}|{description[:500]}"
    external_id = hashlib.sha256(basis.encode("utf-8")).hexdigest()

    existing = db.scalar(
        select(Job)
        .options(selectinload(Job.company))
        .where(Job.source_api == SOURCE_PASTED, Job.external_id == external_id)
    )
    company = _get_or_create_company(db, company_name)

    if existing is not None:
        # Refresh in case the advert was edited since it was first pasted.
        existing.title = title[:500]
        existing.description = description
        existing.location = location
        existing.company_id = company.id
        db.commit()
        db.refresh(existing)
        return existing

    job = Job(
        company_id=company.id,
        title=title[:500],
        location=location,
        description=description,
        url=url,
        source_api=SOURCE_PASTED,
        external_id=external_id,
        source_publisher=publisher,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _claim(db, user, job: Job) -> None:
    """Record that this user added the job, so it shows on their Jobs page."""
    existing = db.scalar(
        select(UserJob).where(UserJob.user_id == user.id, UserJob.job_id == job.id)
    )
    if existing is None:
        db.add(UserJob(user_id=user.id, job_id=job.id))
        db.commit()


@router.post(
    "/from-url",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ai_rate_limit)],
)
def add_job_from_url(payload: JobFromUrl, user: CurrentUser, db: DbSession) -> JobOut:
    """Fetch a pasted job link and store the advert.

    Extraction is cheapest-first: schema.org JSON-LD, then known containers,
    and only then the model - so most pastes cost no AI quota at all.
    """
    try:
        final_url, page = job_url.fetch_page(payload.url)
    except job_url.JobFetchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    parsed = job_url.parse_json_ld(page) or job_url.parse_containers(page)

    if parsed is None or len(parsed.get("description", "")) < MIN_DESCRIPTION_CHARS:
        try:
            extracted = ai.extract_job_from_page(job_url.page_text(page), final_url)
        except ai.AIUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Could not read that page automatically, and AI extraction is "
                "not configured. Paste the job description text instead.",
            ) from exc
        except ai.AIError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            ) from exc
        parsed = {
            "title": extracted.title,
            "company": extracted.company,
            "location": extracted.location,
            "description": extracted.description,
        }

    description = clean_text(parsed.get("description")) or ""
    if len(description) < MIN_DESCRIPTION_CHARS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Could not find a job description on that page. Copy the advert "
            "text and paste it directly instead.",
        )

    job = _store_job(
        db,
        title=clean_text(parsed.get("title")) or "Untitled role",
        company_name=clean_text(parsed.get("company")) or "",
        location=clean_text(parsed.get("location")),
        description=description,
        url=final_url,
        publisher=job_url.publisher_for(final_url),
    )
    _claim(db, user, job)
    return decorate_jobs(db, user, [job])[0]


@router.post(
    "/from-text",
    response_model=JobOut,
    status_code=status.HTTP_201_CREATED,
)
def add_job_from_text(payload: JobFromText, user: CurrentUser, db: DbSession) -> JobOut:
    """Paste the advert text directly. Costs no AI quota at all.

    Needed because LinkedIn, Indeed and others block server-side fetches; this
    is the escape hatch that keeps the app usable for any job anywhere.
    """
    url = None
    if payload.url:
        try:
            url = job_url.validate_url(payload.url)
        except job_url.JobFetchError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
            ) from exc

    job = _store_job(
        db,
        title=clean_text(payload.title) or "Untitled role",
        company_name=clean_text(payload.company) or "",
        location=None,
        description=clean_text(payload.text) or "",
        url=url,
        publisher=job_url.publisher_for(url) if url else None,
    )
    _claim(db, user, job)
    return decorate_jobs(db, user, [job])[0]


@router.get("", response_model=list[JobOut])
def list_jobs(user: CurrentUser, db: DbSession) -> list[JobOut]:
    """Every job this user has added, most recent first.

    With no feed, this is the main page's content.
    """
    jobs = list(
        db.scalars(
            select(Job)
            .join(UserJob, UserJob.job_id == Job.id)
            .options(selectinload(Job.company))
            .where(UserJob.user_id == user.id)
            .order_by(UserJob.added_at.desc())
        )
    )
    return decorate_jobs(db, user, jobs)


def _load_job(db, job_id: int) -> Job:
    job = db.scalar(select(Job).options(selectinload(Job.company)).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, user: CurrentUser, db: DbSession) -> JobDetailOut:
    """Job detail with a cached match if one exists. Never scores on its own."""
    job = _load_job(db, job_id)
    resume = active_resume(db, user)

    match = None
    if resume is not None:
        match = db.scalar(
            select(JobMatch).where(
                JobMatch.user_id == user.id,
                JobMatch.job_id == job_id,
                JobMatch.resume_id == resume.id,
            )
        )

    documents = list(
        db.scalars(
            select(GeneratedDocument)
            .where(GeneratedDocument.user_id == user.id, GeneratedDocument.job_id == job_id)
            .order_by(GeneratedDocument.created_at.desc())
        )
    )

    return JobDetailOut(
        job=decorate_jobs(db, user, [job])[0],
        match=JobMatchOut.model_validate(match) if match else None,
        documents=[GeneratedDocumentOut.model_validate(d) for d in documents],
    )


@router.post(
    "/{job_id}/match",
    response_model=JobMatchOut,
    dependencies=[Depends(ai_rate_limit)],
)
def analyze_job(
    job_id: int,
    user: CurrentUser,
    db: DbSession,
    refresh: Annotated[bool, Query(description="Recompute even if cached")] = False,
) -> JobMatch:
    """Score this job against the active resume. Cached per (user, job, resume)."""
    job = _load_job(db, job_id)
    resume = require_active_resume(db, user)

    existing = db.scalar(
        select(JobMatch).where(
            JobMatch.user_id == user.id,
            JobMatch.job_id == job_id,
            JobMatch.resume_id == resume.id,
        )
    )
    if existing is not None and not refresh:
        return existing

    try:
        analysis = ai.analyze_match(
            resume.extracted_text or "", job.title, job.company.name, job.description or ""
        )
    except ai.AIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ai.AIRateLimited as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)
        ) from exc
    except ai.AIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    row = existing or JobMatch(user_id=user.id, job_id=job_id, resume_id=resume.id)
    row.match_percentage = analysis.match_percentage
    row.requirements_met = analysis.requirements_met[:40]
    row.requirements_missing = analysis.requirements_missing[:40]
    row.rationale = analysis.rationale
    row.model_used = settings.gemini_model
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
