"""Saved jobs - the shortlist. Job-level, and never triggers notifications."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Job, SavedJob
from app.schemas import SavedJobOut
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api/saved", tags=["saved"])


@router.get("", response_model=list[SavedJobOut])
def list_saved(user: CurrentUser, db: DbSession) -> list[SavedJobOut]:
    saved = list(
        db.scalars(
            select(SavedJob)
            .options(selectinload(SavedJob.job).selectinload(Job.company))
            .where(SavedJob.user_id == user.id)
            .order_by(SavedJob.saved_at.desc())
        )
    )
    decorated = decorate_jobs(db, user, [s.job for s in saved])
    return [
        SavedJobOut(job=job, saved_at=row.saved_at) for row, job in zip(saved, decorated)
    ]


@router.post("/{job_id}", response_model=SavedJobOut, status_code=status.HTTP_201_CREATED)
def save_job(job_id: int, user: CurrentUser, db: DbSession) -> SavedJobOut:
    job = db.scalar(select(Job).options(selectinload(Job.company)).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    existing = db.scalar(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id)
    )
    if existing is None:
        existing = SavedJob(user_id=user.id, job_id=job_id)
        db.add(existing)
        db.commit()
        db.refresh(existing)

    return SavedJobOut(job=decorate_jobs(db, user, [job])[0], saved_at=existing.saved_at)


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
def unsave_job(job_id: int, user: CurrentUser, db: DbSession) -> Response:
    row = db.scalar(
        select(SavedJob).where(SavedJob.user_id == user.id, SavedJob.job_id == job_id)
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
