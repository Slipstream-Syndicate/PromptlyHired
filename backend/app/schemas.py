"""Pydantic request/response models.

Every endpoint validates at this boundary - client-side validation is never
trusted. Free-text fields are length-capped and stripped of control characters
before they reach the database.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import ApplicationStatus, JobType

_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def clean_text(value: str | None) -> str | None:
    """Strip control characters and surrounding whitespace.

    Rendering safety itself comes from React escaping by default; this keeps
    junk out of the stored data rather than trying to be an HTML sanitiser.
    """
    if value is None:
        return None
    cleaned = _CONTROL_CHARS.sub("", value).strip()
    return cleaned or None


# --- Auth ---------------------------------------------------------------


class UserCreate(BaseModel):
    email: EmailStr
    # 72 bytes is bcrypt's hard limit - reject rather than silently truncate.
    password: str = Field(min_length=8, max_length=72)
    name: str = Field(min_length=1, max_length=120)

    @field_validator("name")
    @classmethod
    def _clean_name(cls, v: str) -> str:
        cleaned = clean_text(v)
        if not cleaned:
            raise ValueError("name must not be blank")
        return cleaned


class UserLogin(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=72)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=1, max_length=512)


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


# --- Profile & preferences ----------------------------------------------


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    email: EmailStr
    name: str
    profile_picture_url: str | None = None
    created_at: datetime


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    profile_picture_url: str | None = Field(default=None, max_length=1024)

    @field_validator("name", "profile_picture_url")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return clean_text(v)


class PreferencesIn(BaseModel):
    """Same field set the homepage search filters use - one source of truth."""

    keywords: str | None = Field(default=None, max_length=255)
    location: str | None = Field(default=None, max_length=255)
    salary_min: int | None = Field(default=None, ge=0, le=10_000_000)
    salary_max: int | None = Field(default=None, ge=0, le=10_000_000)
    job_type: JobType | None = None

    @field_validator("keywords", "location")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return clean_text(v)

    @field_validator("salary_max")
    @classmethod
    def _check_range(cls, v: int | None, info):
        smin = info.data.get("salary_min")
        if v is not None and smin is not None and v < smin:
            raise ValueError("salary_max must be greater than or equal to salary_min")
        return v


class PreferencesOut(PreferencesIn):
    model_config = ConfigDict(from_attributes=True)

    updated_at: datetime | None = None


# --- Companies & jobs ----------------------------------------------------


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo_url: str | None = None


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    company: CompanyOut
    location: str | None = None
    salary_range: str | None = None
    url: str | None = None
    posted_date: date | None = None
    description: str | None = None
    job_type: JobType | None = None
    source_api: str
    # Names the destination of the outbound Apply link ("Apply on LinkedIn").
    source_publisher: str | None = None

    # Per-user state, attached by the router. Save and Follow are independent:
    # neither implies the other.
    is_saved: bool = False
    is_company_followed: bool = False
    application_status: ApplicationStatus | None = None


class SearchResponse(BaseModel):
    """Followed-company listings are pinned above the general results."""

    followed: list[JobOut]
    results: list[JobOut]
    preferences: PreferencesOut
    source: str
    # search-v2 paginates by opaque cursor, not page number. Pass it back as
    # ?cursor=... to fetch the next page.
    next_cursor: str | None = None


class FollowOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    company: CompanyOut
    created_at: datetime


class SavedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: JobOut
    saved_at: datetime


# --- Applications --------------------------------------------------------


class ApplicationCreate(BaseModel):
    job_id: int
    status: ApplicationStatus = ApplicationStatus.applied
    applied_date: date | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    # A job normally moves off the Saved shortlist once actually applied to.
    unsave: bool = True

    @field_validator("notes")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return clean_text(v)


class ApplicationUpdate(BaseModel):
    status: ApplicationStatus | None = None
    applied_date: date | None = None
    notes: str | None = Field(default=None, max_length=10_000)

    @field_validator("notes")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return clean_text(v)


class ApplicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job: JobOut
    status: ApplicationStatus
    applied_date: date
    status_updated_at: datetime
    notes: str | None = None
    # Surfaced on the Applications page so a quiet application is visible
    # without opening the analytics view.
    needs_follow_up: bool = False
    days_since_update: int = 0
