"""Attach per-user state to job listings in one batch, not per row.

Saved and Followed are independent flags: saving a job never follows its
company, and following a company never saves its jobs.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Application, Company, Follow, Job, SavedJob, User
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
    followed_ids = set(
        db.scalars(
            select(Follow.company_id).where(
                Follow.user_id == user.id, Follow.company_id.in_(company_ids)
            )
        )
    )
    statuses = {
        job_id: status
        for job_id, status in db.execute(
            select(Application.job_id, Application.status).where(
                Application.user_id == user.id, Application.job_id.in_(job_ids)
            )
        )
    }

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
            is_company_followed=job.company_id in followed_ids,
            application_status=statuses.get(job.id),
        )
        for job in jobs
    ]
