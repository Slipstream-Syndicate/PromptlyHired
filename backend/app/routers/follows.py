"""Followed companies - company-level, and the only thing that drives
notifications. Reached from Profile, not from the bottom nav.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.deps import CurrentUser, DbSession
from app.models import Company, Follow
from app.schemas import CompanyOut, FollowOut

router = APIRouter(prefix="/api/follows", tags=["follows"])


@router.get("", response_model=list[FollowOut])
def list_follows(user: CurrentUser, db: DbSession) -> list[Follow]:
    return list(
        db.scalars(
            select(Follow)
            .options(selectinload(Follow.company))
            .where(Follow.user_id == user.id)
            .order_by(Follow.created_at.desc())
        )
    )


@router.post("/{company_id}", response_model=FollowOut, status_code=status.HTTP_201_CREATED)
def follow_company(company_id: int, user: CurrentUser, db: DbSession) -> FollowOut:
    company = db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Company not found.")

    row = db.scalar(
        select(Follow).where(Follow.user_id == user.id, Follow.company_id == company_id)
    )
    if row is None:
        row = Follow(user_id=user.id, company_id=company_id)
        db.add(row)
        db.commit()
        db.refresh(row)

    return FollowOut(company=CompanyOut.model_validate(company), created_at=row.created_at)


@router.delete("/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
def unfollow_company(company_id: int, user: CurrentUser, db: DbSession) -> Response:
    row = db.scalar(
        select(Follow).where(Follow.user_id == user.id, Follow.company_id == company_id)
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
