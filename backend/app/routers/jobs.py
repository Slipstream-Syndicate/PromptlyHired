from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Follow, Job, JobPreferences, JobType
from app.schemas import JobOut, PreferencesOut, SearchResponse
from app.services import sources
from app.services.ingest import upsert_jobs
from app.services.jsearch import JobSourceError, NormalizedJob
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _get_or_create_prefs(db, user) -> JobPreferences:
    prefs = db.scalar(select(JobPreferences).where(JobPreferences.user_id == user.id))
    if prefs is None:
        prefs = JobPreferences(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


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
    use_saved_preferences: Annotated[
        bool,
        Query(
            description=(
                "True on the login auto-search: run with the stored preferences. "
                "False when the user submits the filter form, whose values then "
                "become the new stored preferences."
            )
        ),
    ] = False,
) -> SearchResponse:
    prefs = _get_or_create_prefs(db, user)

    if use_saved_preferences:
        keywords, location = prefs.keywords, prefs.location
        salary_min, salary_max = prefs.salary_min, prefs.salary_max
        job_type = prefs.job_type
    else:
        # A submitted filter form is the whole filter state, so an omitted field
        # means cleared. Preferences and search filters stay one source of truth.
        prefs.keywords = keywords
        prefs.location = location
        prefs.salary_min = salary_min
        prefs.salary_max = salary_max
        prefs.job_type = job_type
        db.commit()
        db.refresh(prefs)

    try:
        listings, source, next_cursor = await sources.search(
            keywords, location, job_type, salary_min, cursor
        )
    except JobSourceError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    listings = [j for j in listings if _salary_matches(j, salary_min, salary_max)]
    rows = upsert_jobs(db, listings)
    db.commit()

    followed_company_ids = set(
        db.scalars(select(Follow.company_id).where(Follow.user_id == user.id))
    )

    # "New from companies you follow" is pinned above the general results.
    followed_rows = [r for r in rows if r.company_id in followed_company_ids]
    general_rows = [r for r in rows if r.company_id not in followed_company_ids]

    return SearchResponse(
        followed=decorate_jobs(db, user, followed_rows),
        results=decorate_jobs(db, user, general_rows),
        preferences=PreferencesOut.model_validate(prefs),
        source=source,
        next_cursor=next_cursor,
    )


@router.get("/{job_id}", response_model=JobOut)
def get_job(job_id: int, user: CurrentUser, db: DbSession) -> JobOut:
    job = db.scalar(
        select(Job).options(selectinload(Job.company)).where(Job.id == job_id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")
    return decorate_jobs(db, user, [job])[0]
