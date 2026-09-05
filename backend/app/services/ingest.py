"""Persist normalised listings, deduped across API sources.

Companies collapse on a normalised name so one employer means one Follow.
Jobs collapse on (source_api, external_id) so re-running a search does not
create duplicate rows or re-trigger notifications.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Company, Job
from app.services.jsearch import NormalizedJob


def normalize_company_name(name: str) -> str:
    return " ".join(name.lower().split())[:255]


def _get_or_create_companies(db: Session, names: list[str]) -> dict[str, Company]:
    keys = {normalize_company_name(n): n for n in names}
    if not keys:
        return {}

    existing = {
        c.normalized_name: c
        for c in db.scalars(
            select(Company).where(Company.normalized_name.in_(list(keys)))
        )
    }
    for norm, display in keys.items():
        if norm not in existing:
            company = Company(name=display, normalized_name=norm)
            db.add(company)
            existing[norm] = company
    db.flush()
    return existing


def upsert_jobs(db: Session, jobs: list[NormalizedJob]) -> list[Job]:
    """Insert unseen listings, refresh volatile fields on ones already stored.

    Returns the Job rows in the same order as the input.
    """
    if not jobs:
        return []

    companies = _get_or_create_companies(db, [j.company_name for j in jobs])

    for j in jobs:
        company = companies[normalize_company_name(j.company_name)]
        if j.company_logo_url and not company.logo_url:
            company.logo_url = j.company_logo_url

    keys = {(j.source_api, j.external_id) for j in jobs}
    existing = {
        (row.source_api, row.external_id): row
        for row in db.scalars(
            select(Job).where(
                Job.source_api.in_({k[0] for k in keys}),
                Job.external_id.in_({k[1] for k in keys}),
            )
        )
    }

    result: list[Job] = []
    for j in jobs:
        key = (j.source_api, j.external_id)
        row = existing.get(key)
        if row is None:
            row = Job(
                company_id=companies[normalize_company_name(j.company_name)].id,
                title=j.title,
                location=j.location,
                salary_range=j.salary_range,
                url=j.url,
                posted_date=j.posted_date,
                description=j.description,
                job_type=j.job_type,
                source_api=j.source_api,
                external_id=j.external_id,
                source_publisher=j.source_publisher,
            )
            db.add(row)
            existing[key] = row
        else:
            # Listings get edited upstream - keep the mutable bits current.
            row.title = j.title
            row.location = j.location
            row.salary_range = j.salary_range
            row.url = j.url
            row.description = j.description
            row.source_publisher = j.source_publisher
        result.append(row)

    db.flush()
    return result
