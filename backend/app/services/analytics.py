"""Funnel analytics over the user's own applications.

Everything here is scoped to one user - this reports on your job search, not on
the job market.

Rates are computed against applications that have had a real chance to move.
"Response rate" counts applications that ever left the `applied` state, which is
why ApplicationEvent history exists: the current status alone cannot tell you
whether something went applied -> rejected or sat untouched.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Application, ApplicationEvent, ApplicationStatus, Company, Job, User

# Reaching any of these means the employer actually came back to you.
RESPONDED_STATUSES = {
    ApplicationStatus.online_assessment,
    ApplicationStatus.interview,
    ApplicationStatus.offer,
    ApplicationStatus.rejected,
}
# Nothing further will happen on these, so they are never "awaiting a reply".
TERMINAL_STATUSES = {
    ApplicationStatus.offer,
    ApplicationStatus.rejected,
    ApplicationStatus.withdrawn,
}


def _pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 1) if whole else 0.0


def is_stale(app: Application, now: datetime | None = None) -> bool:
    """Quiet for too long, and still capable of moving."""
    if app.status in TERMINAL_STATUSES:
        return False
    now = now or datetime.now(timezone.utc)
    updated = app.status_updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    return (now - updated).days >= settings.follow_up_after_days


def funnel(db: Session, user: User) -> dict:
    apps = list(
        db.scalars(
            select(Application)
            .options(selectinload(Application.job).selectinload(Job.company))
            .where(Application.user_id == user.id)
        )
    )
    total = len(apps)

    events = list(
        db.scalars(
            select(ApplicationEvent)
            .join(Application, Application.id == ApplicationEvent.application_id)
            .where(Application.user_id == user.id)
            .order_by(ApplicationEvent.changed_at)
        )
    )
    events_by_app: dict[int, list[ApplicationEvent]] = {}
    for event in events:
        events_by_app.setdefault(event.application_id, []).append(event)

    def ever_reached(app: Application, statuses: set[ApplicationStatus]) -> bool:
        if app.status in statuses:
            return True
        return any(e.to_status in statuses for e in events_by_app.get(app.id, []))

    responded = sum(1 for a in apps if ever_reached(a, RESPONDED_STATUSES))
    interviewed = sum(
        1 for a in apps if ever_reached(a, {ApplicationStatus.interview, ApplicationStatus.offer})
    )
    offers = sum(1 for a in apps if ever_reached(a, {ApplicationStatus.offer}))
    rejected = sum(1 for a in apps if ever_reached(a, {ApplicationStatus.rejected}))

    # Days from applying to the first status change, per application.
    response_days: list[int] = []
    for app in apps:
        first_move = next(
            (e for e in events_by_app.get(app.id, []) if e.to_status in RESPONDED_STATUSES),
            None,
        )
        if first_move is None:
            continue
        changed = first_move.changed_at
        if changed.tzinfo is None:
            changed = changed.replace(tzinfo=timezone.utc)
        delta = (changed.date() - app.applied_date).days
        if delta >= 0:
            response_days.append(delta)

    by_status = Counter(a.status.value for a in apps)

    # Per-company breakdown, most-applied first.
    per_company: dict[int, dict] = {}
    for app in apps:
        company: Company = app.job.company
        row = per_company.setdefault(
            company.id,
            {"company": company.name, "applications": 0, "responses": 0, "interviews": 0, "offers": 0},
        )
        row["applications"] += 1
        if ever_reached(app, RESPONDED_STATUSES):
            row["responses"] += 1
        if ever_reached(app, {ApplicationStatus.interview, ApplicationStatus.offer}):
            row["interviews"] += 1
        if ever_reached(app, {ApplicationStatus.offer}):
            row["offers"] += 1

    companies = sorted(
        per_company.values(), key=lambda r: (-r["applications"], r["company"])
    )
    for row in companies:
        row["response_rate"] = _pct(row["responses"], row["applications"])

    # Applications per week over the last 12 weeks.
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    buckets = {week_start - timedelta(weeks=i): 0 for i in range(11, -1, -1)}
    for app in apps:
        start = app.applied_date - timedelta(days=app.applied_date.weekday())
        if start in buckets:
            buckets[start] += 1
    over_time = [{"week": k.isoformat(), "applications": v} for k, v in buckets.items()]

    stale = [a for a in apps if is_stale(a)]

    return {
        "total_applications": total,
        "by_status": {s.value: by_status.get(s.value, 0) for s in ApplicationStatus},
        "responded": responded,
        "response_rate": _pct(responded, total),
        "interviews": interviewed,
        "interview_rate": _pct(interviewed, total),
        "offers": offers,
        "offer_rate": _pct(offers, total),
        "rejected": rejected,
        "awaiting_reply": sum(1 for a in apps if a.status not in TERMINAL_STATUSES),
        "median_days_to_response": (
            round(statistics.median(response_days), 1) if response_days else None
        ),
        "companies": companies[:20],
        "applications_over_time": over_time,
        "needs_follow_up": [
            {
                "application_id": a.id,
                "title": a.job.title,
                "company": a.job.company.name,
                "status": a.status.value,
                "days_quiet": (
                    datetime.now(timezone.utc)
                    - (
                        a.status_updated_at
                        if a.status_updated_at.tzinfo
                        else a.status_updated_at.replace(tzinfo=timezone.utc)
                    )
                ).days,
            }
            for a in sorted(stale, key=lambda x: x.status_updated_at)
        ],
        "follow_up_after_days": settings.follow_up_after_days,
        # History only exists from the point this feature shipped, so funnels
        # for older applications are based on their current status alone.
        "tracked_events": len(events),
    }
