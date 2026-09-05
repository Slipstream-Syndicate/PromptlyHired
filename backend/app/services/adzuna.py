"""Adzuna client - the secondary job source.

Adzuna is a separate aggregator from JSearch, so it widens coverage rather than
duplicating it. It is optional: with no credentials the search simply runs on
JSearch alone.

Two quirks worth knowing:
  * `salary_is_predicted` means Adzuna *estimated* the salary rather than the
    posting stating it. We label those rather than passing a guess off as fact.
  * `description` is a truncated snippet, not the full posting text.

Pure module: talks to the API and normalises. No database access.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from app.config import settings
from app.models import JobType
from app.services.jsearch import JobSourceError, NormalizedJob

logger = logging.getLogger(__name__)

SOURCE_NAME = "adzuna"
_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

_call_count = 0


def upstream_call_count() -> int:
    return _call_count


def _location(item: dict) -> str | None:
    loc = item.get("location") or {}
    display = loc.get("display_name")
    if isinstance(display, str) and display.strip():
        return display.strip()[:255]
    area = loc.get("area")
    if isinstance(area, list) and area:
        return ", ".join(str(a) for a in area)[:255]
    return None


def _salary(item: dict) -> tuple[str | None, int | None, int | None]:
    lo, hi = item.get("salary_min"), item.get("salary_max")
    lo_i = int(lo) if isinstance(lo, (int, float)) else None
    hi_i = int(hi) if isinstance(hi, (int, float)) else None
    if lo_i is None and hi_i is None:
        return None, None, None

    # "1"/1/True all appear in the wild for this flag.
    predicted = str(item.get("salary_is_predicted", "0")).lower() in {"1", "true"}
    symbol = {"gb": "£", "us": "$", "de": "€", "fr": "€"}.get(
        settings.adzuna_country.lower(), ""
    )

    if lo_i is not None and hi_i is not None and lo_i != hi_i:
        text = f"{symbol}{lo_i:,} - {symbol}{hi_i:,}"
    else:
        text = f"{symbol}{(lo_i or hi_i):,}"
    if predicted:
        text += " (est.)"
    return text[:120], lo_i, hi_i


def _job_type(item: dict) -> JobType | None:
    time_ = str(item.get("contract_time") or "").lower()
    type_ = str(item.get("contract_type") or "").lower()
    if time_ == "part_time":
        return JobType.part_time
    if type_ == "contract":
        return JobType.contract
    if time_ == "full_time":
        return JobType.full_time
    return None


def _posted_date(item: dict):
    raw = item.get("created")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date()
    except ValueError:
        return None


def normalize(item: dict) -> NormalizedJob | None:
    external_id = item.get("id")
    title = item.get("title")
    company = (item.get("company") or {}).get("display_name")
    if not external_id or not title or not company:
        return None

    salary_text, lo, hi = _salary(item)
    description = item.get("description")
    if description and len(description) > 20_000:
        description = description[:20_000]

    return NormalizedJob(
        external_id=str(external_id),
        source_api=SOURCE_NAME,
        # Adzuna returns titles with <strong> highlighting around matches.
        title=str(title).replace("<strong>", "").replace("</strong>", "").strip()[:500],
        company_name=str(company).strip()[:255],
        company_logo_url=None,
        location=_location(item),
        salary_range=salary_text,
        salary_min=lo,
        salary_max=hi,
        url=item.get("redirect_url"),
        posted_date=_posted_date(item),
        description=description,
        job_type=_job_type(item),
        # Adzuna links go through their own redirect, so that is the honest
        # destination to name on the Apply button.
        source_publisher="Adzuna",
    )


def build_params(
    keywords: str | None,
    location: str | None,
    salary_min: int | None,
    job_type: JobType | None,
) -> dict[str, str]:
    params: dict[str, str] = {
        "app_id": settings.adzuna_app_id,
        "app_key": settings.adzuna_app_key,
        "results_per_page": "20",
        "max_days_old": "30",
        "content-type": "application/json",
    }
    if keywords:
        params["what"] = keywords
    if location:
        params["where"] = location
    if salary_min:
        params["salary_min"] = str(salary_min)

    # Adzuna filters are opt-in flags rather than one enum.
    if job_type is JobType.full_time:
        params["full_time"] = "1"
    elif job_type is JobType.part_time:
        params["part_time"] = "1"
    elif job_type is JobType.contract:
        params["contract"] = "1"
    return params


async def search(
    keywords: str | None,
    location: str | None,
    job_type: JobType | None = None,
    salary_min: int | None = None,
    page: int = 1,
) -> list[NormalizedJob]:
    global _call_count

    if not settings.adzuna_enabled:
        return []

    params = build_params(keywords, location, salary_min, job_type)
    url = (
        f"https://api.adzuna.com/v1/api/jobs/"
        f"{settings.adzuna_country.lower()}/search/{max(1, page)}"
    )

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            response = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        raise JobSourceError(f"Could not reach Adzuna: {exc}") from exc

    _call_count += 1
    logger.info("Adzuna upstream call #%d -> %s", _call_count, response.status_code)

    if response.status_code in (401, 403):
        raise JobSourceError("Adzuna rejected the credentials.")
    if response.status_code == 429:
        raise JobSourceError("Adzuna rate limit reached.")
    if response.status_code >= 400:
        logger.error("Adzuna error %s: %s", response.status_code, response.text[:300])
        raise JobSourceError("Adzuna returned an error.")

    items = response.json().get("results") or []
    return [j for j in (normalize(i) for i in items if isinstance(i, dict)) if j]
