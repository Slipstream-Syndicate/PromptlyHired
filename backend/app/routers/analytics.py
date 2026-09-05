from __future__ import annotations

from fastapi import APIRouter

from app.deps import CurrentUser, DbSession
from app.services.analytics import funnel

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("/funnel")
def application_funnel(user: CurrentUser, db: DbSession) -> dict:
    """Funnel over this user's own applications - never anyone else's."""
    return funnel(db, user)
