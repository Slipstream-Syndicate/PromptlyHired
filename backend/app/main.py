from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.routers import (
    analytics,
    applications,
    auth,
    follows,
    jobs,
    profile,
    push,
    saved,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # Refuse to boot a production deployment that is insecure. Failing loudly at
    # startup beats discovering a default signing key in the wild.
    blockers = settings.production_blockers()
    if blockers:
        for problem in blockers:
            logger.error("CONFIG ERROR: %s", problem)
        raise RuntimeError(
            "Refusing to start with insecure production config: " + "; ".join(blockers)
        )

    for warning in settings.production_warnings():
        logger.warning("DEGRADED: %s", warning)

    ready = settings.readiness()
    logger.info(
        "Feature readiness: %s",
        ", ".join(f"{k}={v}" for k, v in ready.items()),
    )

    if not settings.uses_s3:
        Path(settings.media_local_dir).mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="JobTrail API",
    version="1.0.0",
    description="Job search and application tracking.",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

# Locked to the real frontend origins - never "*". Credentials are off because
# the access token travels in the Authorization header, not a cookie.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Baseline hardening headers.

    The API serves JSON and user-uploaded images, never HTML, so it locks itself
    out of scripting and framing entirely. HSTS is only meaningful over TLS, so
    it is set in production where the platform terminates HTTPS.
    """
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault(
        "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
    )
    if settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.include_router(auth.router)
app.include_router(jobs.router)
app.include_router(saved.router)
app.include_router(follows.router)
app.include_router(applications.router)
app.include_router(profile.router)
app.include_router(push.router)
app.include_router(analytics.router)


# Dev-only: in production these are served straight from the S3/R2 bucket.
if not settings.uses_s3:
    Path(settings.media_local_dir).mkdir(parents=True, exist_ok=True)
    app.mount("/media", StaticFiles(directory=settings.media_local_dir), name="media")


@app.get("/health", tags=["meta"])
def health() -> dict[str, object]:
    """Liveness probe plus a readiness report.

    Deliberately exposes only booleans about which optional integrations are
    configured - never the credentials themselves - so a deployment can be
    verified from a browser without reading server logs.
    """
    return {"status": "ok", **settings.readiness()}
