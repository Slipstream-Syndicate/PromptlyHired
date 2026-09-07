"""Pydantic request/response models.

Every endpoint validates at this boundary - client-side validation is never
trusted. Free-text fields are length-capped and stripped of control characters
before they reach the database.
"""

from __future__ import annotations

import re
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import DocumentKind, JobType

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


def clean_list(values: list[str] | None, max_items: int = 60, max_len: int = 120) -> list[str]:
    """Normalise an AI- or user-supplied string list.

    Deduplicates case-insensitively while preserving order, so an extraction
    returning both "Python" and "python" yields one entry.
    """
    out: list[str] = []
    seen: set[str] = set()
    for raw in (values or [])[: max_items * 3]:
        cleaned = clean_text(str(raw))
        if not cleaned:
            continue
        cleaned = cleaned[:max_len]
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(cleaned)
        if len(out) >= max_items:
            break
    return out


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


# --- Profile ------------------------------------------------------------


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


# --- Resume & skill profile ---------------------------------------------


class SkillProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    skills: list[str]
    job_titles: list[str]
    domains: list[str]
    locations: list[str]
    seniority: str | None = None
    years_experience: float | None = None
    summary: str | None = None
    edited_by_user: bool = False
    generated_at: datetime


class SkillProfileUpdate(BaseModel):
    """The user's own corrections. Extraction is a starting point, not truth."""

    skills: list[str] | None = None
    job_titles: list[str] | None = None
    domains: list[str] | None = None
    locations: list[str] | None = None
    seniority: str | None = Field(default=None, max_length=60)
    years_experience: float | None = Field(default=None, ge=0, le=80)
    summary: str | None = Field(default=None, max_length=4000)

    @field_validator("skills", "job_titles", "domains", "locations")
    @classmethod
    def _clean_lists(cls, v: list[str] | None) -> list[str] | None:
        return None if v is None else clean_list(v)

    @field_validator("seniority", "summary")
    @classmethod
    def _clean_strings(cls, v: str | None) -> str | None:
        return clean_text(v)


class ResumeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    file_url: str
    original_filename: str
    content_type: str
    is_active: bool
    uploaded_at: datetime
    skill_profile: SkillProfileOut | None = None


# --- Companies & jobs ----------------------------------------------------


class CompanyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    logo_url: str | None = None
    short_description: str | None = None


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

    # Per-user state attached by the router. The match figures are read from
    # the cached JobMatch row - showing them costs a database join, never an
    # API call. They are null until the user asks for an analysis.
    is_saved: bool = False
    has_match: bool = False
    has_documents: bool = False
    match_percentage: int | None = None
    requirements_met_count: int | None = None
    requirements_missing_count: int | None = None


class SavedJobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job: JobOut
    saved_at: datetime


# --- Match analysis ------------------------------------------------------


class JobMatchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    resume_id: int
    match_percentage: int
    requirements_met: list[str]
    requirements_missing: list[str]
    rationale: str | None = None
    generated_at: datetime


class JobDetailOut(BaseModel):
    job: JobOut
    match: JobMatchOut | None = None
    documents: list[GeneratedDocumentOut] = Field(default_factory=list)


# --- Generated documents -------------------------------------------------


class GeneratedDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    resume_id: int
    kind: DocumentKind
    content: dict
    edited_content: dict | None = None
    created_at: datetime
    updated_at: datetime


class DocumentGenerateRequest(BaseModel):
    kind: DocumentKind
    # Optional user steering, e.g. "emphasise my backend work".
    instructions: str | None = Field(default=None, max_length=1000)

    @field_validator("instructions")
    @classmethod
    def _clean(cls, v: str | None) -> str | None:
        return clean_text(v)


class DocumentUpdate(BaseModel):
    """The user's edits. Never overwrites the original AI output."""

    edited_content: dict


class HistoryEntryOut(BaseModel):
    job: JobOut
    documents: list[GeneratedDocumentOut]
    last_generated_at: datetime


JobDetailOut.model_rebuild()
