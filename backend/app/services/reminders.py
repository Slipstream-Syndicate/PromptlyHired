"""Follow-up reminders for applications that have gone quiet.

An application counts as stale when its status has not changed for
FOLLOW_UP_AFTER_DAYS and it is not already finished (offer/rejected/withdrawn).

Reminders repeat on a cadence rather than every run: `last_reminder_at` on the
Application is what stops a weekly cron turning into weekly spam about the same
silent application forever.

    python -m app.tasks reminders
"""

from __future__ import annotations

import html
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models import Application, Job, User
from app.services.analytics import is_stale
from app.services.email import send_email
from app.services.push import send_to_user

logger = logging.getLogger(__name__)


def _due_for_reminder(app: Application, now: datetime) -> bool:
    if not is_stale(app, now):
        return False
    if app.last_reminder_at is None:
        return True
    last = app.last_reminder_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    return now - last >= timedelta(days=settings.reminder_repeat_days)


def _render(user: User, apps: list[Application], now: datetime) -> tuple[str, str, str]:
    count = len(apps)
    subject = f"Follow up on {count} application{'s' if count != 1 else ''}?"

    def days_quiet(app: Application) -> int:
        updated = app.status_updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        return (now - updated).days

    lines = [
        f"Hi {user.name},",
        "",
        f"These have had no update in over {settings.follow_up_after_days} days:",
        "",
    ]
    rows = []
    for app in apps:
        quiet = days_quiet(app)
        lines.append(
            f"* {app.job.title} at {app.job.company.name} "
            f"- {app.status.value.replace('_', ' ')}, quiet for {quiet} days"
        )
        if app.job.url:
            lines.append(f"  {app.job.url}")
        # Job text is external and untrusted - escape before embedding in HTML.
        rows.append(
            "<li style='margin-bottom:12px'>"
            f"<strong>{html.escape(app.job.title)}</strong><br>"
            f"{html.escape(app.job.company.name)} &middot; "
            f"{html.escape(app.status.value.replace('_', ' '))} &middot; "
            f"quiet for {quiet} days"
            + (
                f"<br><a href='{html.escape(app.job.url, quote=True)}'>View posting</a>"
                if app.job.url
                else ""
            )
            + "</li>"
        )
    lines += ["", f"Open JobTrail: {settings.app_base_url}"]

    html_body = (
        '<div style="font-family:system-ui,-apple-system,Segoe UI,sans-serif">'
        f"<p>Hi {html.escape(user.name)},</p>"
        f"<p>These have had no update in over {settings.follow_up_after_days} days:</p>"
        f"<ul style='padding-left:18px'>{''.join(rows)}</ul>"
        f"<p><a href='{html.escape(settings.app_base_url, quote=True)}'>Open JobTrail</a></p>"
        "</div>"
    )
    return subject, "\n".join(lines), html_body


def send_reminders(db: Session) -> dict[str, int]:
    """Email/push each user about their stale applications. Costs no API quota."""
    now = datetime.now(timezone.utc)
    users = list(db.scalars(select(User)))

    users_notified = 0
    applications_flagged = 0

    for user in users:
        apps = list(
            db.scalars(
                select(Application)
                .options(selectinload(Application.job).selectinload(Job.company))
                .where(Application.user_id == user.id)
            )
        )
        due = [a for a in apps if _due_for_reminder(a, now)]
        if not due:
            continue

        due.sort(key=lambda a: a.status_updated_at)
        subject, text_body, html_body = _render(user, due, now)
        send_email(user.email, subject, text_body, html_body)
        send_to_user(
            db,
            user.id,
            {
                "title": subject,
                "body": f"{due[0].job.title} at {due[0].job.company.name}"
                + (f" and {len(due) - 1} more" if len(due) > 1 else ""),
                "url": "/applications",
            },
        )

        for app in due:
            app.last_reminder_at = now
        db.commit()

        users_notified += 1
        applications_flagged += len(due)

    return {"users_notified": users_notified, "applications_flagged": applications_flagged}
