"""Verify every external integration actually works.

Configuration being *present* is not the same as it *working* - a wrong model name
or an R2 token without write permission both look fine in the env vars
and fail silently at the moment you need them. This connects to each service for
real and reports what happened.

    python -m app.tasks doctor
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




def check_ai() -> tuple[str, str, str]:
    """Make a real (tiny) call - a key can be present, malformed, and unusable."""
    if not settings.ai_enabled:
        return _line(
            FAIL if settings.is_production else SKIP,
            "Gemini API",
            "GEMINI_API_KEY unset - resume analysis, matching and generation are all off",
        )
    from app.services import ai

    try:
        reply = ai.ping()
        return _line(OK, "Gemini API", f"{settings.gemini_model} replied {reply!r}")
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)[:160]
        # A wrong model name is the most likely failure, so name the alternatives.
        try:
            models = [m for m in ai.list_models() if "flash" in m.lower()][:4]
            if models:
                detail += f" | flash models on this key: {', '.join(models)}"
        except Exception:  # noqa: BLE001
            pass
        return _line(FAIL, "Gemini API", detail)



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


def run() -> int:
    results = [
        check_database(),
        check_migrations(),
        check_frontend_urls(),
        check_ai(),
        check_media_storage(),
    ]

    print(f"\nPromptlyHired doctor  (ENV={settings.env})")
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
