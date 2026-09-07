"""Tailored resume / cover letter generation, editing, and the History view."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import DocumentKind, GeneratedDocument, Job, JobMatch
from app.rate_limit import ai_rate_limit
from app.routers.resumes import require_active_resume
from app.schemas import (
    DocumentGenerateRequest,
    DocumentUpdate,
    GeneratedDocumentOut,
    HistoryEntryOut,
)
from app.services import ai
from app.services.user_state import decorate_jobs

router = APIRouter(prefix="/api", tags=["documents"])


def _match_summary(match: JobMatch | None) -> str:
    if match is None:
        return ""
    met = ", ".join(match.requirements_met[:10])
    missing = ", ".join(match.requirements_missing[:10])
    return f"Already satisfied: {met or 'none identified'}\nGaps: {missing or 'none identified'}"


@router.post(
    "/jobs/{job_id}/documents",
    response_model=GeneratedDocumentOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(ai_rate_limit)],
)
def generate_document(
    job_id: int, payload: DocumentGenerateRequest, user: CurrentUser, db: DbSession
) -> GeneratedDocument:
    """Generate a tailored document. Always creates a draft, never sends anything."""
    job = db.scalar(select(Job).options(selectinload(Job.company)).where(Job.id == job_id))
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found.")

    resume = require_active_resume(db, user)
    match = db.scalar(
        select(JobMatch).where(
            JobMatch.user_id == user.id,
            JobMatch.job_id == job_id,
            JobMatch.resume_id == resume.id,
        )
    )

    generator = (
        ai.generate_resume if payload.kind is DocumentKind.resume else ai.generate_cover_letter
    )
    try:
        result = generator(
            resume.extracted_text or "",
            job.title,
            job.company.name,
            job.description or "",
            _match_summary(match),
            payload.instructions,
        )
    except ai.AIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except ai.AIError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    document = GeneratedDocument(
        user_id=user.id,
        job_id=job_id,
        resume_id=resume.id,
        kind=payload.kind,
        content=result.model_dump(),
        model_used=settings.claude_model,
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    return document


@router.get("/documents/{document_id}", response_model=GeneratedDocumentOut)
def get_document(document_id: int, user: CurrentUser, db: DbSession) -> GeneratedDocument:
    document = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id, GeneratedDocument.user_id == user.id
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")
    return document


@router.patch("/documents/{document_id}", response_model=GeneratedDocumentOut)
def update_document(
    document_id: int, payload: DocumentUpdate, user: CurrentUser, db: DbSession
) -> GeneratedDocument:
    """Save the user's edits.

    Writes to `edited_content` only - the original AI output is never
    overwritten, so "reset to generated" always works.
    """
    document = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id, GeneratedDocument.user_id == user.id
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    document.edited_content = payload.edited_content
    db.commit()
    db.refresh(document)
    return document


@router.post("/documents/{document_id}/reset", response_model=GeneratedDocumentOut)
def reset_document(document_id: int, user: CurrentUser, db: DbSession) -> GeneratedDocument:
    """Discard edits and fall back to the generated original. Costs nothing."""
    document = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id, GeneratedDocument.user_id == user.id
        )
    )
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Document not found.")

    document.edited_content = None
    db.commit()
    db.refresh(document)
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: int, user: CurrentUser, db: DbSession) -> Response:
    document = db.scalar(
        select(GeneratedDocument).where(
            GeneratedDocument.id == document_id, GeneratedDocument.user_id == user.id
        )
    )
    if document is not None:
        db.delete(document)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/history", response_model=list[HistoryEntryOut])
def history(user: CurrentUser, db: DbSession) -> list[HistoryEntryOut]:
    """Jobs this user has generated documents for, most recent first.

    Derived from GeneratedDocument rather than stored separately - there is no
    such thing as a history entry without a document.
    """
    documents = list(
        db.scalars(
            select(GeneratedDocument)
            .options(
                selectinload(GeneratedDocument.job).selectinload(Job.company)
            )
            .where(GeneratedDocument.user_id == user.id)
            .order_by(GeneratedDocument.created_at.desc())
        )
    )
    if not documents:
        return []

    grouped: dict[int, list[GeneratedDocument]] = {}
    for document in documents:
        grouped.setdefault(document.job_id, []).append(document)

    jobs = {j.id: j for j in (d.job for d in documents)}
    decorated = {j.id: out for j, out in zip(jobs.values(), decorate_jobs(db, user, jobs.values()))}

    entries = [
        HistoryEntryOut(
            job=decorated[job_id],
            documents=[GeneratedDocumentOut.model_validate(d) for d in docs],
            last_generated_at=max(d.created_at for d in docs),
        )
        for job_id, docs in grouped.items()
    ]
    entries.sort(key=lambda e: e.last_generated_at, reverse=True)
    return entries
