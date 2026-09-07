"""Attach per-user state to job listings in one batch, not per row.

Deliberately does NOT attach a match percentage: scoring is an API call per job,
so the feed shows only whether an analysis already exists.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, GeneratedDocument, Job, JobMatch, SavedJob, User
from app.schemas import CompanyOut, JobOut


def decorate_jobs(db: Session, user: User, jobs: Iterable[Job]) -> list[JobOut]:
    jobs = list(jobs)
    if not jobs:
        return []

    job_ids = {j.id for j in jobs}
    company_ids = {j.company_id for j in jobs}

    saved_ids = set(
        db.scalars(
            select(SavedJob.job_id).where(
                SavedJob.user_id == user.id, SavedJob.job_id.in_(job_ids)
            )
        )
    )
    matched_ids = set(
        db.scalars(
            select(JobMatch.job_id).where(
                JobMatch.user_id == user.id, JobMatch.job_id.in_(job_ids)
            )
        )
    )
    documented_ids = set(
        db.scalars(
            select(GeneratedDocument.job_id).where(
                GeneratedDocument.user_id == user.id,
                GeneratedDocument.job_id.in_(job_ids),
            )
        )
    )

    companies = {
        c.id: c for c in db.scalars(select(Company).where(Company.id.in_(company_ids)))
    }

    return [
        JobOut(
            id=job.id,
            title=job.title,
            company=CompanyOut.model_validate(companies[job.company_id]),
            location=job.location,
            salary_range=job.salary_range,
            url=job.url,
            posted_date=job.posted_date,
            description=job.description,
            job_type=job.job_type,
            source_api=job.source_api,
            source_publisher=job.source_publisher,
            is_saved=job.id in saved_ids,
            has_match=job.id in matched_ids,
            has_documents=job.id in documented_ids,
        )
        for job in jobs
    ]
