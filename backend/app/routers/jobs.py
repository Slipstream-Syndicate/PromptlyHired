"""Job feed and job detail.

The feed is driven by the user's SkillProfile - they never have to invent
keywords. Filters remain available to narrow it, but are transient query
parameters rather than stored preferences.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import GeneratedDocument, Job, JobMatch, JobType, Resume, SkillProfile
from app.rate_limit import ai_rate_limit
from app.routers.resumes import active_resume, require_active_resume
from app.schemas import (
    GeneratedDocumentOut,
    JobDetailOut,
    JobMatchOut,
    JobOut,
    SearchResponse,
)
from app.services import ai, sources
from app.services.ingest import upsert_jobs
from app.services.jsearch import JobSourceError, NormalizedJob
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])

# How many extracted job titles to fold into one search query. All of them would
# produce an incoherent query that matches nothing.
MAX_TITLES_IN_QUERY = 3


def build_query(profile: SkillProfile | None, keywords: str | None) -> str | None:
    """Turn the skill profile into search terms.

    Titles beat raw skills: job boards index adverts by role name, so searching
    "Backend Engineer" returns far better results than "Python, Docker, AWS".
    """
    if keywords:
        return keywords
    if profile is None:
        return None
    titles = [t for t in (profile.job_titles or []) if t][:MAX_TITLES_IN_QUERY]
    if titles:
        return " OR ".join(titles) if len(titles) > 1 else titles[0]
    skills = [s for s in (profile.skills or []) if s][:4]
    return " ".join(skills) or None


def _salary_matches(job: NormalizedJob, floor: int | None, ceiling: int | None) -> bool:
    """Exclude only listings whose stated salary definitely misses the range.

    Most listings publish no salary at all; dropping those would empty the feed,
    so unknown salary is treated as a possible match.
    """
    if floor is not None and job.salary_max is not None and job.salary_max < floor:
        return False
    if ceiling is not None and job.salary_min is not None and job.salary_min > ceiling:
        return False
    return True


@router.get("/search", response_model=SearchResponse)
async def search_jobs(
    user: CurrentUser,
    db: DbSession,
    keywords: Annotated[str | None, Query(max_length=255)] = None,
    location: Annotated[str | None, Query(max_length=255)] = None,
    salary_min: Annotated[int | None, Query(ge=0, le=10_000_000)] = None,
    salary_max: Annotated[int | None, Query(ge=0, le=10_000_000)] = None,
    job_type: JobType | None = None,
    cursor: Annotated[str | None, Query(max_length=4096)] = None,
) -> SearchResponse:
    resume = active_resume(db, user)
    profile = resume.skill_profile if resume else None

    query = build_query(profile, keywords)
    if not query:
        # No resume and no keywords: nothing sensible to search for.
        return SearchResponse(results=[], source="none", searched_for=None)

    # Fall back to a location the resume mentions when the user has not filtered.
    if not location and profile and profile.locations:
        location = profile.locations[0]

    try:
        listings, source, next_cursor = await sources.search(
            query, location, job_type, salary_min, cursor
        )
    except JobSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    listings = [j for j in listings if _salary_matches(j, salary_min, salary_max)]
    rows = upsert_jobs(db, listings)
    db.commit()

    return SearchResponse(
        results=decorate_jobs(db, user, rows),
        source=source,
        next_cursor=next_cursor,
        searched_for=query,
    )


def _load_job(db, job_id: int) -> Job:
    job = db.scalar(
        select(Job).options(selectinload(Job.company)).where(Job.id == job_id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return job


@router.get("/{job_id}", response_model=JobDetailOut)
def get_job(job_id: int, user: CurrentUser, db: DbSession) -> JobDetailOut:
    """Job detail, including a cached match analysis if one already exists.

    Deliberately does NOT compute a match - scoring costs an API call, so it is
    a separate explicit POST.
    """
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
            .where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.job_id == job_id,
            )
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
    """Score this job against the active resume.

    Cached per (user, job, resume): reopening a card is free, and a new resume
    produces a new analysis without destroying the old one.
    """
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
            resume.extracted_text or "",
            job.title,
            job.company.name,
            job.description or "",
        )
    except ai.AIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ai.AIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    row = existing or JobMatch(user_id=user.id, job_id=job_id, resume_id=resume.id)
    row.match_percentage = analysis.match_percentage
    row.requirements_met = analysis.requirements_met[:40]
    row.requirements_missing = analysis.requirements_missing[:40]
    row.rationale = analysis.rationale
    row.model_used = settings.claude_model
    db.add(row)
    db.commit()
    db.refresh(row)
    return row
