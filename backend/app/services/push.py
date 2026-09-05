"""Web push delivery.

Push is the enhancement channel, email is the reliable one - so every failure
here is logged and swallowed rather than raised. A user with no working
subscription still gets the digest email.

Subscriptions that the push service reports as gone (404/410) are deleted, which
is the only way a browser tells us the user uninstalled or revoked permission.
"""

from __future__ import annotations

import json
import logging

from pywebpush import WebPushException, webpush
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import PushSubscription

logger = logging.getLogger(__name__)


def _vapid_claims() -> dict[str, str]:
    return {"sub": settings.vapid_subject}


def send_to_subscription(sub: PushSubscription, payload: dict) -> bool:
    """Return True if delivered. Raises nothing."""
    try:
        webpush(
            subscription_info={
                "endpoint": sub.endpoint,
                "keys": {"p256dh": sub.p256dh, "auth": sub.auth},
            },
            data=json.dumps(payload),
            vapid_private_key=settings.vapid_private_key,
            vapid_claims=_vapid_claims(),
            timeout=10,
        )
        return True
    except WebPushException as exc:
        status = getattr(exc.response, "status_code", None)
        if status in (404, 410):
            logger.info("Push subscription gone (%s) - will be pruned", status)
            raise SubscriptionGone from exc
        logger.warning("Push failed (%s): %s", status, exc)
        return False
    except Exception:  # noqa: BLE001 - push must never break a request
        logger.exception("Unexpected push failure")
        return False


class SubscriptionGone(Exception):
    """The push service says this subscription no longer exists."""


def send_to_user(db: Session, user_id: int, payload: dict) -> int:
    """Push to every device a user has registered. Returns delivered count."""
    if not settings.push_enabled:
        logger.info("VAPID keys not configured - skipping push")
        return 0

    subs = list(
        db.scalars(select(PushSubscription).where(PushSubscription.user_id == user_id))
    )
    delivered = 0
    stale: list[PushSubscription] = []

    for sub in subs:
        try:
            if send_to_subscription(sub, payload):
                delivered += 1
        except SubscriptionGone:
            stale.append(sub)

    for sub in stale:
        db.delete(sub)
    if stale:
        db.commit()
        logger.info("Pruned %d dead push subscription(s)", len(stale))

    return delivered
