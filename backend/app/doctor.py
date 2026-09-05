"""Verify every external integration actually works.

Configuration being *present* is not the same as it *working* - a typo'd SMTP
password or an R2 token without write permission both look fine in the env vars
and fail silently at the moment you need them. This connects to each service for
real and reports what happened.

    python -m app.tasks doctor
    python -m app.tasks doctor --email you@example.com   # also sends a test email
"""

from __future__ import annotations

import uuid

from app.config import settings

OK, FAIL, SKIP = "PASS", "FAIL", "SKIP"


def _line(status: str, name: str, detail: str = "") -> tuple[str, str, str]:
    return status, name, detail


def check_database() -> tuple[str, str, str]:
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            version = conn.execute(text("SHOW server_version")).scalar()
        return _line(OK, "Database", f"connected, Postgres {version}")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "Database", str(exc)[:200])


def check_migrations() -> tuple[str, str, str]:
    try:
        from sqlalchemy import text

        from app.db import engine

        with engine.connect() as conn:
            current = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
        if not current:
            return _line(FAIL, "Migrations", "alembic_version is empty - run 'alembic upgrade head'")
        return _line(OK, "Migrations", f"at revision {current}")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "Migrations", f"no alembic_version table ({str(exc)[:120]})")


def check_job_source() -> tuple[str, str, str]:
    if not settings.rapidapi_key:
        return _line(SKIP, "JSearch", "RAPIDAPI_KEY unset - feed serves sample listings")
    import asyncio

    from app.services import jsearch

    try:
        jobs, source, _ = asyncio.run(
            jsearch.search("software engineer", None, None, None)
        )
        return _line(OK, "JSearch", f"{len(jobs)} listings from {source} (1 API call used)")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "JSearch", str(exc)[:200])


def check_adzuna() -> tuple[str, str, str]:
    if not settings.adzuna_enabled:
        return _line(SKIP, "Adzuna", "not configured (optional secondary source)")
    import asyncio

    from app.services import adzuna

    try:
        jobs = asyncio.run(adzuna.search("software engineer", None))
        return _line(OK, "Adzuna", f"{len(jobs)} listings (country={settings.adzuna_country})")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "Adzuna", str(exc)[:200])


def check_email(send_to: str | None) -> tuple[str, str, str]:
    if not settings.email_enabled:
        return _line(
            FAIL if settings.is_production else SKIP,
            "Email (SMTP)",
            "SMTP_HOST unset - digests and reminders are only logged, never sent",
        )
    if not send_to:
        return _line(
            OK, "Email (SMTP)", f"configured ({settings.smtp_host}); "
            "re-run with --email you@example.com to send a real test"
        )

    from app.services.email import send_email

    sent = send_email(
        send_to,
        "JobTrail: SMTP is working",
        "If you are reading this, digests and follow-up reminders will reach you.",
        "<p>If you are reading this, digests and follow-up reminders will reach you.</p>",
    )
    if sent:
        return _line(OK, "Email (SMTP)", f"test email delivered to {send_to}")
    return _line(FAIL, "Email (SMTP)", "send failed - check credentials and sender verification")


def check_push() -> tuple[str, str, str]:
    if not settings.push_enabled:
        return _line(SKIP, "Web push", "VAPID keys unset - push disabled (email still works)")
    # A malformed key only surfaces when a real push is attempted, so validate shape.
    import base64

    try:
        raw = settings.vapid_public_key + "=" * (-len(settings.vapid_public_key) % 4)
        decoded = base64.urlsafe_b64decode(raw)
        if len(decoded) != 65 or decoded[0] != 4:
            return _line(FAIL, "Web push", "VAPID_PUBLIC_KEY is not an uncompressed P-256 point")
        return _line(OK, "Web push", "VAPID keypair looks valid")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "Web push", f"VAPID_PUBLIC_KEY is not valid base64url ({exc})")


def check_media_storage() -> tuple[str, str, str]:
    if not settings.uses_s3:
        detail = "MEDIA_STORAGE is local - uploads are WIPED on every redeploy"
        return _line(FAIL if settings.is_production else SKIP, "Media storage", detail)

    # Round-trip a real object: credentials that can read but not write are a
    # common misconfiguration that only shows up on a user's first upload.
    from app.services.storage import _s3_client

    key = f"healthcheck/{uuid.uuid4().hex}.txt"
    try:
        client = _s3_client()
        client.put_object(Bucket=settings.s3_bucket, Key=key, Body=b"ok")
        client.delete_object(Bucket=settings.s3_bucket, Key=key)
        if not settings.s3_public_base_url:
            return _line(FAIL, "Media storage", "S3_PUBLIC_BASE_URL is not set - uploads would have no URL")
        return _line(OK, "Media storage", f"read/write verified on {settings.s3_bucket}")
    except Exception as exc:  # noqa: BLE001
        return _line(FAIL, "Media storage", str(exc)[:200])


def check_frontend_urls() -> tuple[str, str, str]:
    problems = settings.production_blockers()
    if problems:
        return _line(FAIL, "Frontend URLs", "; ".join(problems)[:250])
    if settings.is_production:
        return _line(OK, "Frontend URLs", f"CORS={settings.cors_origins}, APP_BASE_URL={settings.app_base_url}")
    return _line(SKIP, "Frontend URLs", "development mode - production checks not applied")


def run(send_to: str | None = None) -> int:
    results = [
        check_database(),
        check_migrations(),
        check_frontend_urls(),
        check_job_source(),
        check_adzuna(),
        check_email(send_to),
        check_push(),
        check_media_storage(),
    ]

    print(f"\nJobTrail doctor  (ENV={settings.env})")
    print("=" * 72)
    for status, name, detail in results:
        print(f"  [{status}] {name:16} {detail}")
    print("=" * 72)

    failures = [r for r in results if r[0] == FAIL]
    skipped = [r for r in results if r[0] == SKIP]
    if failures:
        print(f"{len(failures)} check(s) FAILED - the app will not fully work until these are fixed.\n")
        return 1
    print(f"All active checks passed. {len(skipped)} optional integration(s) not configured.\n")
    return 0
