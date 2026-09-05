from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import settings
from app.deps import CurrentUser, DbSession
from app.models import PushSubscription
from app.services.push import send_to_user

router = APIRouter(prefix="/api/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str = Field(min_length=1, max_length=255)
    auth: str = Field(min_length=1, max_length=255)


class PushSubscriptionIn(BaseModel):
    endpoint: str = Field(min_length=1, max_length=1024)
    keys: PushKeys


class PushStatus(BaseModel):
    enabled: bool
    public_key: str | None = None
    subscriptions: int


@router.get("/config", response_model=PushStatus)
def push_config(user: CurrentUser, db: DbSession) -> PushStatus:
    """The frontend needs the VAPID public key to subscribe at all."""
    count = len(
        list(
            db.scalars(
                select(PushSubscription.id).where(PushSubscription.user_id == user.id)
            )
        )
    )
    return PushStatus(
        enabled=settings.push_enabled,
        public_key=settings.vapid_public_key or None,
        subscriptions=count,
    )


@router.post("/subscribe", status_code=status.HTTP_201_CREATED)
def subscribe(
    payload: PushSubscriptionIn, user: CurrentUser, db: DbSession, request: Request
) -> dict[str, str]:
    if not settings.push_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Push notifications are not configured on this server.",
        )

    existing = db.scalar(
        select(PushSubscription).where(PushSubscription.endpoint == payload.endpoint)
    )
    if existing is not None:
        # Same browser, possibly a different account - reassign it.
        existing.user_id = user.id
        existing.p256dh = payload.keys.p256dh
        existing.auth = payload.keys.auth
    else:
        db.add(
            PushSubscription(
                user_id=user.id,
                endpoint=payload.endpoint,
                p256dh=payload.keys.p256dh,
                auth=payload.keys.auth,
                user_agent=(request.headers.get("user-agent") or "")[:255] or None,
            )
        )
    db.commit()
    return {"status": "subscribed"}


@router.post("/unsubscribe", status_code=status.HTTP_204_NO_CONTENT)
def unsubscribe(payload: PushSubscriptionIn, user: CurrentUser, db: DbSession) -> Response:
    row = db.scalar(
        select(PushSubscription).where(
            PushSubscription.endpoint == payload.endpoint,
            PushSubscription.user_id == user.id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/test")
def send_test(user: CurrentUser, db: DbSession) -> dict[str, int]:
    """Let the user prove notifications work on this device before relying on them."""
    delivered = send_to_user(
        db,
        user.id,
        {
            "title": "JobTrail notifications are on",
            "body": "You will get a nudge here when companies you follow post new roles.",
            "url": "/",
        },
    )
    if delivered == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="No active subscription on this account. Enable notifications first.",
        )
    return {"delivered": delivered}
