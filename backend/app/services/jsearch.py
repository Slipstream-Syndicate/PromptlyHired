"""JSearch (RapidAPI) client.

JSearch wraps Google for Jobs, which aggregates LinkedIn/Indeed/Glassdoor/
ZipRecruiter listings. That is the legal route to those listings - scraping
those sites directly violates their terms and gets IPs blocked.

Uses the /search-v2 endpoint: the older /search was retired and now 404s with
"Endpoint '/search' does not exist". search-v2 returns {"data": {"jobs": [...],
"cursor": "..."}} and paginates by opaque cursor rather than page number.

The free plan is small (~200 calls/month), so every upstream call is counted in
the log and identical searches are served from a short-lived in-process cache.

This module is pure: it talks to the API and normalises the payload. Nothing
here touches the database (see ingest.py for that).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import httpx

from app.config import settings
from app.models import JobType

logger = logging.getLogger(__name__)

SOURCE_NAME = "jsearch"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Counts upstream calls for the life of the process, so the log shows quota
# burn at a glance. Resets on restart - it is a signal, not an accountant.
_call_count = 0

# query-key -> (expires_at, jobs, cursor)
_cache: dict[str, tuple[float, list["NormalizedJob"], str | None]] = {}

_JSEARCH_TO_JOB_TYPE = {
    "FULLTIME": JobType.full_time,
    "PARTTIME": JobType.part_time,
    "CONTRACTOR": JobType.contract,
    "INTERN": JobType.contract,
}


class JobSourceError(RuntimeError):
    """Upstream job API failed in a way the caller should surface to the user."""


@dataclass(slots=True)
class NormalizedJob:
    external_id: str
    source_api: str
    title: str
    company_name: str
    company_logo_url: str | None
    location: str | None
    salary_range: str | None
    salary_min: int | None
    salary_max: int | None
    url: str | None
    posted_date: date | None
    description: str | None
    job_type: JobType | None
    source_publisher: str | None


def upstream_call_count() -> int:
    return _call_count


def _salary(item: dict) -> tuple[str | None, int | None, int | None]:
    """search-v2 has no currency field, so prefer its preformatted string."""
    lo, hi = item.get("job_min_salary"), item.get("job_max_salary")
    lo_i = int(lo) if isinstance(lo, (int, float)) else None
    hi_i = int(hi) if isinstance(hi, (int, float)) else None

    text = item.get("job_salary_string") or item.get("job_salary")
    if isinstance(text, str) and text.strip():
        return text.strip()[:120], lo_i, hi_i

    if lo_i is None and hi_i is None:
        return None, None, None

    suffix = {"YEAR": "/yr", "MONTH": "/mo", "WEEK": "/wk", "HOUR": "/hr"}.get(
        str(item.get("job_salary_period") or "").upper(), ""
    )
    if lo_i is not None and hi_i is not None:
        return f"{lo_i:,} - {hi_i:,}{suffix}", lo_i, hi_i
    return f"{(lo_i or hi_i):,}{suffix}", lo_i, hi_i


def _location(item: dict) -> str | None:
    # job_location is the dependable one; city/state/country are often null.
    loc = item.get("job_location")
    if isinstance(loc, str) and loc.strip():
        return loc.strip()[:255]
    parts = [item.get("job_city"), item.get("job_state"), item.get("job_country")]
    joined = ", ".join(p for p in parts if p)
    return joined[:255] or None


def _posted_date(item: dict) -> date | None:
    raw = item.get("job_posted_at_datetime_utc")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _employment_types(item: dict) -> list[str]:
    raw = item.get("job_employment_types")
    if isinstance(raw, list):
        return [str(t).upper() for t in raw]
    single = item.get("job_employment_type")
    return [str(single).upper()] if single else []


def _job_type(item: dict) -> JobType | None:
    if item.get("job_is_remote"):
        return JobType.remote
    for t in _employment_types(item):
        if t in _JSEARCH_TO_JOB_TYPE:
            return _JSEARCH_TO_JOB_TYPE[t]
    return None


def matches_job_type(item: dict, wanted: JobType | None) -> bool:
    """Filtered locally: search-v2 ignores an employment_types query param.

    Doing it here costs nothing, where a second API call would cost quota.
    """
    if wanted is None:
        return True
    if wanted is JobType.remote:
        return bool(item.get("job_is_remote"))
    target = next(k for k, v in _JSEARCH_TO_JOB_TYPE.items() if v is wanted)
    return target in _employment_types(item)


def normalize(item: dict) -> NormalizedJob | None:
    external_id = item.get("job_id")
    title = item.get("job_title")
    employer = item.get("employer_name")
    if not external_id or not title or not employer:
        return None

    salary_text, smin, smax = _salary(item)
    description = item.get("job_description")
    if description and len(description) > 20_000:
        description = description[:20_000]

    return NormalizedJob(
        external_id=str(external_id),
        source_api=SOURCE_NAME,
        title=str(title)[:500],
        company_name=str(employer)[:255],
        company_logo_url=item.get("employer_logo"),
        location=_location(item),
        salary_range=salary_text,
        salary_min=smin,
        salary_max=smax,
        url=item.get("job_apply_link"),
        posted_date=_posted_date(item),
        description=description,
        job_type=_job_type(item),
        source_publisher=(str(item["job_publisher"])[:120] if item.get("job_publisher") else None),
    )


def build_params(
    keywords: str | None,
    location: str | None,
    job_type: JobType | None,
    cursor: str | None = None,
) -> dict[str, str]:
    # search-v2 takes the location inside the query text ("X in London"),
    # with `country` narrowing the market.
    query = keywords or "software engineer"
    if location:
        query = f"{query} in {location}"

    params: dict[str, str] = {"query": query, "date_posted": "month"}
    if settings.jsearch_country:
        params["country"] = settings.jsearch_country
    if job_type is JobType.remote:
        params["work_from_home"] = "true"
    if cursor:
        params["cursor"] = cursor
    return params


async def search(
    keywords: str | None,
    location: str | None,
    job_type: JobType | None,
    cursor: str | None = None,
) -> tuple[list[NormalizedJob], str, str | None]:
    """Return (jobs, source, next_cursor).

    Falls back to local fixtures when no API key is configured.
    """
    global _call_count

    if not settings.rapidapi_key:
        logger.warning("RAPIDAPI_KEY not set - serving sample listings")
        return sample_jobs(keywords, location, job_type), "sample", None

    params = build_params(keywords, location, job_type, cursor)
    cache_key = repr(sorted(params.items()))
    hit = _cache.get(cache_key)
    if hit and hit[0] > time.monotonic():
        logger.info("JSearch cache hit (%s) - no quota used", params["query"])
        return hit[1], SOURCE_NAME, hit[2]

    headers = {
        "X-RapidAPI-Key": settings.rapidapi_key,
        "X-RapidAPI-Host": settings.jsearch_host,
    }
    url = f"https://{settings.jsearch_host}/search-v2"

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params, headers=headers)
    except httpx.HTTPError as exc:
        raise JobSourceError(f"Could not reach the job listings service: {exc}") from exc

    _call_count += 1
    logger.info(
        "JSearch upstream call #%d (%s) -> %s", _call_count, params["query"], response.status_code
    )

    if response.status_code == 429:
        raise JobSourceError(
            "Job listings quota reached for this plan. Try again next cycle."
        )
    if response.status_code == 403:
        raise JobSourceError(
            "Job listings service rejected the API key - check the RapidAPI subscription."
        )
    if response.status_code >= 400:
        logger.error("JSearch error %s: %s", response.status_code, response.text[:400])
        raise JobSourceError("Job listings service returned an error.")

    payload = response.json()
    data = payload.get("data") or {}
    items = data.get("jobs") or []
    next_cursor = data.get("cursor")

    jobs = [
        job
        for job in (
            normalize(i)
            for i in items
            if isinstance(i, dict) and matches_job_type(i, job_type)
        )
        if job
    ]

    if settings.jsearch_cache_ttl_minutes > 0:
        _cache[cache_key] = (
            time.monotonic() + settings.jsearch_cache_ttl_minutes * 60,
            jobs,
            next_cursor,
        )
    return jobs, SOURCE_NAME, next_cursor


# --- Dev fixtures --------------------------------------------------------
# Used only when RAPIDAPI_KEY is unset, so the UI can be built and demoed
# without burning free-tier quota. Never reached once a key is configured.

_SAMPLE = [
    ("Backend Engineer", "Monzo", "London, UK", 75_000, 95_000, JobType.full_time),
    ("Graduate Software Engineer", "Monzo", "London, UK", 55_000, 65_000, JobType.full_time),
    ("Full Stack Developer", "Stripe", "Remote", 90_000, 120_000, JobType.remote),
    ("Platform Engineer", "Stripe", "Dublin, IE", 85_000, 110_000, JobType.full_time),
    ("Junior Python Developer", "Octopus Energy", "Manchester, UK", 40_000, 52_000, JobType.full_time),
    ("Data Engineer", "Deliveroo", "London, UK", 70_000, 90_000, JobType.full_time),
    ("Frontend Engineer (React)", "Revolut", "Remote", 65_000, 85_000, JobType.remote),
    ("Software Engineer Intern", "Cloudflare", "London, UK", None, None, JobType.contract),
]


def sample_jobs(
    keywords: str | None, location: str | None, job_type: JobType | None
) -> list[NormalizedJob]:
    today = datetime.now(timezone.utc).date()
    out: list[NormalizedJob] = []
    for idx, (title, company, loc, smin, smax, jtype) in enumerate(_SAMPLE):
        if keywords:
            haystack = f"{title} {company}".lower()
            if not any(t in haystack for t in keywords.lower().split()):
                continue
        if location and location.lower() not in loc.lower() and loc != "Remote":
            continue
        if job_type and jtype is not job_type:
            continue
        salary_text = f"£{smin:,} - £{smax:,}/yr" if smin and smax else None
        out.append(
            NormalizedJob(
                external_id=f"sample-{idx}",
                source_api="sample",
                title=title,
                company_name=company,
                company_logo_url=None,
                location=loc,
                salary_range=salary_text,
                salary_min=smin,
                salary_max=smax,
                url="https://example.com/jobs/sample",
                posted_date=today - timedelta(days=idx),
                description=(
                    f"Sample listing for {title} at {company}. "
                    "Set RAPIDAPI_KEY in backend/.env to pull real listings from JSearch."
                ),
                job_type=jtype,
                source_publisher="Sample Board",
            )
        )
    return out
