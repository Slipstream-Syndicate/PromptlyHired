"""Email delivery.

Email is the reliable notification channel for MVP - web push comes later as an
enhancement, not a replacement. With no SMTP host configured the message is
logged instead of sent, so local development needs no mail server.
"""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.config import settings

logger = logging.getLogger(__name__)


def send_email(to: str, subject: str, text_body: str, html_body: str | None = None) -> bool:
    if not settings.smtp_host:
        logger.info(
            "SMTP not configured - would have emailed %s\nSubject: %s\n%s",
            to,
            subject,
            text_body,
        )
        return False

    message = EmailMessage()
    message["From"] = settings.smtp_from
    message["To"] = to
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=20) as server:
            server.starttls()
            if settings.smtp_user:
                server.login(settings.smtp_user, settings.smtp_password)
            server.send_message(message)
    except (smtplib.SMTPException, OSError):
        logger.exception("Failed to send email to %s", to)
        return False

    logger.info("Sent %r to %s", subject, to)
    return True
