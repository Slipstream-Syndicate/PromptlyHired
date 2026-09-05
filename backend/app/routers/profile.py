from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import JobPreferences, User
from app.schemas import PreferencesIn, PreferencesOut, UserOut, UserUpdate
from app.services.storage import (
    ALLOWED_CONTENT_TYPES,
    UploadError,
    delete_avatar,
    store_avatar,
)

router = APIRouter(prefix="/api/profile", tags=["profile"])


def _prefs_for(db, user: User) -> JobPreferences:
    prefs = db.scalar(select(JobPreferences).where(JobPreferences.user_id == user.id))
    if prefs is None:
        prefs = JobPreferences(user_id=user.id)
        db.add(prefs)
        db.commit()
        db.refresh(prefs)
    return prefs


@router.get("", response_model=UserOut)
def get_profile(user: CurrentUser) -> User:
    return user


@router.patch("", response_model=UserOut)
def update_profile(payload: UserUpdate, user: CurrentUser, db: DbSession) -> User:
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"]:
        user.name = fields["name"]
    if "profile_picture_url" in fields:
        user.profile_picture_url = fields["profile_picture_url"]
    db.commit()
    db.refresh(user)
    return user


@router.get("/preferences", response_model=PreferencesOut)
def get_preferences(user: CurrentUser, db: DbSession) -> JobPreferences:
    """The same fields the homepage search filters read and write."""
    return _prefs_for(db, user)


@router.put("/preferences", response_model=PreferencesOut)
def replace_preferences(
    payload: PreferencesIn, user: CurrentUser, db: DbSession
) -> JobPreferences:
    prefs = _prefs_for(db, user)
    prefs.keywords = payload.keywords
    prefs.location = payload.location
    prefs.salary_min = payload.salary_min
    prefs.salary_max = payload.salary_max
    prefs.job_type = payload.job_type
    db.commit()
    db.refresh(prefs)
    return prefs


@router.post("/picture", response_model=UserOut)
async def upload_picture(
    user: CurrentUser, db: DbSession, file: UploadFile = File(...)
) -> User:
    """Replace the profile picture.

    The image is re-encoded server-side (see services/storage.py), so the
    declared content type is a first filter, not the security boundary.
    """
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Upload a JPEG, PNG or WebP image.",
        )

    # Read with a hard ceiling so a huge body cannot exhaust memory.
    raw = await file.read(settings.max_upload_bytes + 1)
    if len(raw) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Image is too large (max {limit_mb} MB).",
        )

    try:
        url = store_avatar(user.id, raw)
    except UploadError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc

    previous = user.profile_picture_url
    user.profile_picture_url = url
    db.commit()
    db.refresh(user)
    delete_avatar(previous)
    return user


@router.delete("/picture", response_model=UserOut)
def remove_picture(user: CurrentUser, db: DbSession) -> User:
    previous = user.profile_picture_url
    user.profile_picture_url = None
    db.commit()
    db.refresh(user)
    delete_avatar(previous)
    return user
