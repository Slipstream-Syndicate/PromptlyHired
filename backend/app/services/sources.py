"""Aggregates the job sources into one feed.

JSearch is primary (it carries the real publisher name and a direct apply link);
Adzuna is optional extra coverage. A failure in the secondary source must never
take down the search - if Adzuna errors, the user still gets JSearch results.

Pagination note: JSearch paginates by opaque cursor and Adzuna by page number,
which do not compose. Adzuna is therefore queried only for the first page; a
"Load more" continues through JSearch's cursor alone.
"""

from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.models import JobType
from app.services import adzuna, jsearch
from app.services.jsearch import JobSourceError, NormalizedJob

logger = logging.getLogger(__name__)


def _dedup_key(job: NormalizedJob) -> tuple[str, str]:
    """Best-effort cross-source identity.

    The same vacancy carries different ids in each aggregator, so exact id
    matching cannot catch it. Title + employer is the strongest signal we have
    without fuzzy matching; location is deliberately excluded because the two
    sources format it differently ("London" vs "London, United Kingdom").
    """
    return (
        " ".join(job.title.lower().split()),
        " ".join(job.company_name.lower().split()),
    )


def merge(*groups: list[NormalizedJob]) -> list[NormalizedJob]:
    """Concatenate in priority order, dropping later duplicates."""
    seen: set[tuple[str, str]] = set()
    out: list[NormalizedJob] = []
    for group in groups:
        for job in group:
            key = _dedup_key(job)
            if key in seen:
                continue
            seen.add(key)
            out.append(job)
    return out


async def search(
    keywords: str | None,
    location: str | None,
    job_type: JobType | None,
    salary_min: int | None = None,
    cursor: str | None = None,
) -> tuple[list[NormalizedJob], str, str | None]:
    """Return (jobs, source_label, next_cursor)."""
    # Only page one blends the sources - see the pagination note above.
    use_secondary = settings.adzuna_enabled and not cursor

    tasks = [jsearch.search(keywords, location, job_type, cursor)]
    if use_secondary:
        tasks.append(adzuna.search(keywords, location, job_type, salary_min))

    outcomes = await asyncio.gather(*tasks, return_exceptions=True)
    primary = outcomes[0]
    secondary = outcomes[1] if use_secondary else []

    if isinstance(primary, BaseException):
        # The primary source failing with no usable secondary is a real error.
        if isinstance(secondary, BaseException) or not secondary:
            if isinstance(primary, JobSourceError):
                raise primary
            raise JobSourceError("Job listings service is unavailable.") from primary
        logger.warning("JSearch failed, serving Adzuna only: %s", primary)
        return merge(secondary), adzuna.SOURCE_NAME, None

    jobs, source, next_cursor = primary

    if isinstance(secondary, BaseException):
        logger.warning("Adzuna failed, serving JSearch only: %s", secondary)
        secondary = []

    if not secondary:
        return jobs, source, next_cursor

    merged = merge(jobs, secondary)
    dropped = len(jobs) + len(secondary) - len(merged)
    logger.info(
        "Merged %d JSearch + %d Adzuna listings (%d cross-source duplicates dropped)",
        len(jobs),
        len(secondary),
        dropped,
    )
    return merged, f"{source}+{adzuna.SOURCE_NAME}", next_cursor
