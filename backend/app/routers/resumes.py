"""Resume upload and the AI-derived skill profile that drives job search."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import Resume, SkillProfile, User
from app.rate_limit import ai_rate_limit
from app.schemas import ResumeOut, SkillProfileOut, SkillProfileUpdate, clean_list, clean_text
from app.services import ai, resume_text
from app.services.storage import UploadError, delete_stored_file, store_resume

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


def active_resume(db, user: User) -> Resume | None:
    return db.scalar(
        select(Resume)
        .options(selectinload(Resume.skill_profile))
        .where(Resume.user_id == user.id, Resume.is_active.is_(True))
        .order_by(Resume.uploaded_at.desc())
    )


def require_active_resume(db, user: User) -> Resume:
    resume = active_resume(db, user)
    if resume is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Upload a resume first - it is what the search and matching are built on.",
        )
    return resume


@router.get("/active", response_model=ResumeOut | None)
def get_active(user: CurrentUser, db: DbSession) -> Resume | None:
    return active_resume(db, user)


@router.get("", response_model=list[ResumeOut])
def list_resumes(user: CurrentUser, db: DbSession) -> list[Resume]:
    return list(
        db.scalars(
            select(Resume)
            .options(selectinload(Resume.skill_profile))
            .where(Resume.user_id == user.id)
            .order_by(Resume.uploaded_at.desc())
        )
    )


@router.post(
    "",
    response_model=ResumeOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ai_rate_limit)],
)
async def upload_resume(
    user: CurrentUser, db: DbSession, file: UploadFile = File(...)
) -> Resume:
    """Store the resume, extract its text, and derive the skill profile.

    Uploading deactivates the previous resume rather than deleting it: existing
    matches and generated documents reference the resume they were built from.
    """
    if file.content_type not in resume_text.ALLOWED_RESUME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a PDF, DOCX or plain text resume.",
        )

    raw = await file.read(settings.max_resume_bytes + 1)
    if len(raw) > settings.max_resume_bytes:
        limit_mb = settings.max_resume_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"That file is too large (max {limit_mb} MB).",
        )

    # Parse before storing: a file we cannot read is not worth keeping.
    try:
        text = resume_text.extract(raw, file.content_type)
    except resume_text.ResumeParseError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    try:
        url = store_resume(user.id, raw, file.filename or "resume", file.content_type)
    except UploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    for previous in db.scalars(
        select(Resume).where(Resume.user_id == user.id, Resume.is_active.is_(True))
    ):
        previous.is_active = False

    resume = Resume(
        user_id=user.id,
        file_url=url,
        original_filename=(file.filename or "resume")[:255],
        content_type=file.content_type,
        extracted_text=text,
        is_active=True,
    )
    db.add(resume)
    db.flush()

    # Extraction failing must not lose the upload - the user can retry it.
    try:
        extracted = ai.extract_skill_profile(text)
        db.add(
            SkillProfile(
                resume_id=resume.id,
                skills=clean_list(extracted.skills),
                job_titles=clean_list(extracted.job_titles, max_items=12),
                domains=clean_list(extracted.domains, max_items=20),
                locations=clean_list(extracted.locations, max_items=10),
                seniority=clean_text(extracted.seniority),
                years_experience=max(0.0, min(80.0, float(extracted.years_experience or 0))),
                summary=clean_text(extracted.summary),
                model_used=settings.claude_model,
            )
        )
    except ai.AIUnavailable:
        pass  # No key configured; the profile can be filled in by hand.
    except ai.AIError:
        pass  # Surfaced to the user as "no profile yet, retry analysis".

    db.commit()
    db.refresh(resume)
    return resume


@router.post(
    "/{resume_id}/analyze",
    response_model=SkillProfileOut,
    dependencies=[Depends(ai_rate_limit)],
)
def reanalyze(resume_id: int, user: CurrentUser, db: DbSession) -> SkillProfile:
    """Re-derive the skill profile. Explicit, because it costs an API call."""
    resume = db.scalar(
        select(Resume)
        .options(selectinload(Resume.skill_profile))
        .where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found.")

    try:
        extracted = ai.extract_skill_profile(resume.extracted_text or "")
    except ai.AIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ai.AIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
        ) from exc

    profile = resume.skill_profile or SkillProfile(resume_id=resume.id)
    profile.skills = clean_list(extracted.skills)
    profile.job_titles = clean_list(extracted.job_titles, max_items=12)
    profile.domains = clean_list(extracted.domains, max_items=20)
    profile.locations = clean_list(extracted.locations, max_items=10)
    profile.seniority = clean_text(extracted.seniority)
    profile.years_experience = max(0.0, min(80.0, float(extracted.years_experience or 0)))
    profile.summary = clean_text(extracted.summary)
    profile.model_used = settings.claude_model
    profile.edited_by_user = False
    db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@router.patch("/{resume_id}/skill-profile", response_model=SkillProfileOut)
def update_skill_profile(
    resume_id: int, payload: SkillProfileUpdate, user: CurrentUser, db: DbSession
) -> SkillProfile:
    """The user's corrections win. Extraction is a draft, not an authority."""
    resume = db.scalar(
        select(Resume)
        .options(selectinload(Resume.skill_profile))
        .where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    if resume is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Resume not found.")

    profile = resume.skill_profile
    if profile is None:
        profile = SkillProfile(resume_id=resume.id)
        db.add(profile)

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(profile, field, value)
    profile.edited_by_user = True

    db.commit()
    db.refresh(profile)
    return profile


@router.delete("/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_resume(resume_id: int, user: CurrentUser, db: DbSession) -> Response:
    """Delete a resume and the file behind it.

    A CV is sensitive personal data, so the user must be able to remove it. This
    cascades to the skill profile, match analyses and generated documents built
    from it - all of them are derived from the resume and would be orphaned or
    misleading without it.
    """
    resume = db.scalar(
        select(Resume).where(Resume.id == resume_id, Resume.user_id == user.id)
    )
    if resume is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    file_url = resume.file_url
    was_active = resume.is_active
    db.delete(resume)
    db.flush()

    # Promote the most recent remaining resume so the feed keeps working.
    if was_active:
        fallback = db.scalar(
            select(Resume)
            .where(Resume.user_id == user.id)
            .order_by(Resume.uploaded_at.desc())
        )
        if fallback is not None:
            fallback.is_active = True

    db.commit()
    delete_stored_file(file_url)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
