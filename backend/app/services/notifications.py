"""New-listing digest for followed companies.

Notifications are driven only by Follow (company-level). Saved jobs never
trigger email - that is a shortlist, not a subscription.

Quota shape: the refresh step costs ONE upstream call per followed company, so
a daily run against a ~200 call/month plan is unaffordable. Run it weekly, keep
DIGEST_MAX_COMPANIES small, and use --dry-run while developing.

    python -m app.tasks digest              # poll upstream, then email
    python -m app.tasks digest --dry-run    # email from stored jobs, 0 API calls
"""

from __future__ import annotations

import asyncio
import html
import logging

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Company, Follow, Job, NotifiedJob, User
from app.services import jsearch
from app.services.email import send_email
from app.services.ingest import normalize_company_name, upsert_jobs
from app.services.push import send_to_user

logger = logging.getLogger(__name__)

SECONDS_BETWEEN_CALLS = 1.0
MAX_JOBS_PER_EMAIL = 15


async def refresh_followed_companies(db: Session) -> int:
    """Poll the job source for each followed company and store new listings.

    Costs one upstream call per company, capped by DIGEST_MAX_COMPANIES.
    """
    companies = list(
        db.scalars(
            select(Company)
            .join(Follow, Follow.company_id == Company.id)
            .distinct()
            .limit(settings.digest_max_companies)
        )
    )
    if not companies:
        logger.info("No followed companies - skipping upstream refresh")
        return 0

    logger.info(
        "Refreshing %d followed compan%s (max %d, one API call each)",
        len(companies),
        "y" if len(companies) == 1 else "ies",
        settings.digest_max_companies,
    )

    new_rows = 0
    for index, company in enumerate(companies):
        try:
            jobs, _, _ = await jsearch.search(
                keywords=company.name, location=None, job_type=None
            )
        except jsearch.JobSourceError:
            logger.exception("Skipping %s - job source unavailable", company.name)
            continue

        # The source matches on free text, so keep only this employer's listings.
        target = normalize_company_name(company.name)
        jobs = [j for j in jobs if normalize_company_name(j.company_name) == target]

        before = db.query(Job).count()
        upsert_jobs(db, jobs)
        db.commit()
        new_rows += db.query(Job).count() - before

        if index < len(companies) - 1:
            await asyncio.sleep(SECONDS_BETWEEN_CALLS)

    return new_rows


def _render_email(user: User, jobs: list[Job]) -> tuple[str, str, str]:
    count = len(jobs)
    subject = f"{count} new job{'s' if count != 1 else ''} from companies you follow"

    lines = [f"Hi {user.name},", "", "New listings from companies you follow:", ""]
    rows = []
    for job in jobs:
        location = job.location or "Location not listed"
        salary = f" - {job.salary_range}" if job.salary_range else ""
        lines.append(f"* {job.title} at {job.company.name} ({location}){salary}")
        if job.url:
            lines.append(f"  {job.url}")
        # Job data is external, unvalidated text - escape before embedding in HTML.
        rows.append(
            "<li style='margin-bottom:12px'>"
            f"<strong>{html.escape(job.title)}</strong><br>"
            f"{html.escape(job.company.name)} &middot; {html.escape(location)}"
            f"{html.escape(salary)}<br>"
            + (
                f"<a href='{html.escape(job.url, quote=True)}'>View listing</a>"
                if job.url
                else ""
            )
            + "</li>"
        )
    lines += ["", f"Open JobTrail: {settings.app_base_url}"]

    html_body = (
        "<div style=\"font-family:system-ui,-apple-system,Segoe UI,sans-serif\">"
        f"<p>Hi {html.escape(user.name)},</p>"
        "<p>New listings from companies you follow:</p>"
        f"<ul style='padding-left:18px'>{''.join(rows)}</ul>"
        f"<p><a href='{html.escape(settings.app_base_url, quote=True)}'>Open JobTrail</a></p>"
        "</div>"
    )
    return subject, "\n".join(lines), html_body


def send_digests(db: Session) -> int:
    """Email each user the followed-company listings they have not seen yet."""
    users = list(
        db.scalars(select(User).join(Follow, Follow.user_id == User.id).distinct())
    )

    sent = 0
    for user in users:
        followed_ids = set(
            db.scalars(select(Follow.company_id).where(Follow.user_id == user.id))
        )
        if not followed_ids:
            continue

        already_notified = select(NotifiedJob.job_id).where(NotifiedJob.user_id == user.id)
        jobs = list(
            db.scalars(
                select(Job)
                .options(selectinload(Job.company))
                .where(Job.company_id.in_(followed_ids), Job.id.notin_(already_notified))
                .order_by(Job.first_seen_at.desc())
                .limit(MAX_JOBS_PER_EMAIL)
            )
        )
        if not jobs:
            continue

        subject, text_body, html_body = _render_email(user, jobs)
        send_email(user.email, subject, text_body, html_body)

        # Push is an enhancement on top of the email, not a replacement - a user
        # with no registered device still got the message above.
        headline = jobs[0]
        send_to_user(
            db,
            user.id,
            {
                "title": subject,
                "body": f"{headline.title} at {headline.company.name}"
                + (f" and {len(jobs) - 1} more" if len(jobs) > 1 else ""),
                "url": "/",
            },
        )

        # Mark as notified either way: a failed send should not spam on retry,
        # and the same listings still surface at the top of the homepage feed.
        for job in jobs:
            db.add(NotifiedJob(user_id=user.id, job_id=job.id))
        db.commit()
        sent += 1

    return sent


async def run_digest(db: Session, dry_run: bool = False) -> dict[str, int]:
    """dry_run skips the upstream poll entirely, so it costs zero API calls."""
    if dry_run:
        logger.info("Dry run - skipping upstream refresh, no API quota used")
        new_jobs = 0
    else:
        new_jobs = await refresh_followed_companies(db)

    emails = send_digests(db)
    return {
        "new_jobs": new_jobs,
        "emails_sent": emails,
        "api_calls": jsearch.upstream_call_count(),
    }
