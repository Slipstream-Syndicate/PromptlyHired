"""Applications - created when a job is actually applied to.

"Saved" is not a status here; the shortlist is the separate SavedJob entity.
Creating an application is what moves a job off the Saved tab.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Application, ApplicationEvent, Job, SavedJob
from app.schemas import ApplicationCreate, ApplicationOut, ApplicationUpdate
from app.services.analytics import is_stale
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api/applications", tags=["applications"])


def _to_out(db, user, row: Application) -> ApplicationOut:
    updated = row.status_updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return ApplicationOut(
        id=row.id,
        job=decorate_jobs(db, user, [row.job])[0],
        status=row.status,
        applied_date=row.applied_date,
        status_updated_at=row.status_updated_at,
        notes=row.notes,
        needs_follow_up=is_stale(row),
        days_since_update=(datetime.now(timezone.utc) - updated).days,
    )


@router.get("", response_model=list[ApplicationOut])
def list_applications(user: CurrentUser, db: DbSession) -> list[ApplicationOut]:
    rows = list(
        db.scalars(
            select(Application)
            .options(selectinload(Application.job).selectinload(Job.company))
            .where(Application.user_id == user.id)
            .order_by(Application.status_updated_at.desc())
        )
    )
    return [_to_out(db, user, row) for row in rows]


@router.post("", response_model=ApplicationOut, status_code=status.HTTP_201_CREATED)
def create_application(
    payload: ApplicationCreate, user: CurrentUser, db: DbSession
) -> ApplicationOut:
    job = db.scalar(
        select(Job).options(selectinload(Job.company)).where(Job.id == payload.job_id)
    )
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    existing = db.scalar(
        select(Application).where(
            Application.user_id == user.id, Application.job_id == payload.job_id
        )
    )
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You have already logged an application for this job.",
        )

    row = Application(
        user_id=user.id,
        job_id=payload.job_id,
        status=payload.status,
        applied_date=payload.applied_date or date.today(),
        notes=payload.notes,
    )
    db.add(row)
    db.flush()
    # Seed the history so the funnel can measure from the moment of applying.
    db.add(ApplicationEvent(application_id=row.id, from_status=None, to_status=row.status))

    if payload.unsave:
        saved = db.scalar(
            select(SavedJob).where(
                SavedJob.user_id == user.id, SavedJob.job_id == payload.job_id
            )
        )
        if saved is not None:
            db.delete(saved)

    db.commit()
    db.refresh(row)
    row.job = job
    return _to_out(db, user, row)


@router.patch("/{application_id}", response_model=ApplicationOut)
def update_application(
    application_id: int, payload: ApplicationUpdate, user: CurrentUser, db: DbSession
) -> ApplicationOut:
    row = db.scalar(
        select(Application)
        .options(selectinload(Application.job).selectinload(Job.company))
        .where(Application.id == application_id, Application.user_id == user.id)
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Application not found."
        )

    fields = payload.model_dump(exclude_unset=True)
    if "status" in fields and fields["status"] is not None:
        if fields["status"] != row.status:
            db.add(
                ApplicationEvent(
                    application_id=row.id,
                    from_status=row.status,
                    to_status=fields["status"],
                )
            )
            row.status_updated_at = datetime.now(timezone.utc)
            # A real move restarts the follow-up clock.
            row.last_reminder_at = None
        row.status = fields["status"]
    if "applied_date" in fields and fields["applied_date"] is not None:
        row.applied_date = fields["applied_date"]
    if "notes" in fields:
        row.notes = fields["notes"]

    db.commit()
    db.refresh(row)
    return _to_out(db, user, row)


@router.delete("/{application_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_application(application_id: int, user: CurrentUser, db: DbSession) -> Response:
    row = db.scalar(
        select(Application).where(
            Application.id == application_id, Application.user_id == user.id
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
