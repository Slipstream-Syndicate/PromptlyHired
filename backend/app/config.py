from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Render, Railway, Heroku and Fly all hand out DATABASE_URL as "postgres://".
# SQLAlchemy 2 does not recognise that scheme at all, and even "postgresql://"
# would pick psycopg2 (not installed) rather than psycopg 3. Normalising here
# means the deploy platform's value can be pasted in untouched.
_PG_SCHEME_FIXES = {
    "postgres://": "postgresql+psycopg://",
    "postgresql://": "postgresql+psycopg://",
    "postgresql+psycopg2://": "postgresql+psycopg://",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    env: str = "development"
    database_url: str = "postgresql+psycopg://jobtrail:jobtrail@localhost:5433/jobtrail"
    # Platforms inject the port to bind. Honoured by start.sh / the Dockerfile.
    port: int = 8000

    # Auth. Short-lived access token + long-lived rotating refresh token.
    jwt_secret: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 30

    # Locked to the real frontend origins - never "*". NoDecode keeps
    # pydantic-settings from trying to JSON-parse the comma-separated env value
    # before the validator below splits it.
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173", "http://127.0.0.1:5173"]
    )
    app_base_url: str = "http://localhost:5173"

    # --- Job sources ---
    # There are none. Jobs enter the system only when a user pastes a link to
    # one, which is why this project costs nothing to run. Every job-board API
    # worth using is paid, partner-only, or forbids the scraping that would
    # replace it.

    # --- Gemini (free tier) ---
    # Server-side only; the key never reaches the browser.
    gemini_api_key: str = ""
    # A pinned model, not the "-latest" alias: that alias is shared by every
    # default install and returns 503 "high demand" under load, while a pinned
    # sibling answers immediately. Run `python -m app.tasks doctor` to list what
    # this key can call, and `gemini-flash-lite-latest` is a good fallback.
    gemini_model: str = "gemini-3.8-flash"
    # Deeper reasoning for document drafting; extraction and scoring do not
    # need it and it costs latency against a low free-tier rate limit.
    gemini_thinking_level: str = "low"
    # The free tier allows single-digit requests per minute, so this is about
    # staying inside the quota rather than controlling spend.
    ai_calls_per_hour: int = 60

    # --- Uploads (resumes and profile pictures) ---
    # Local disk is dev-only: Render/Railway wipe it on every redeploy, so
    # deployments need an S3-compatible bucket (Cloudflare R2).
    media_storage: str = "local"
    media_local_dir: str = "media"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""
    s3_region: str = "auto"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_resume_bytes: int = 10 * 1024 * 1024
    avatar_max_px: int = 512

    # Shared rate-limit store. Without it the limiter is per-process, so more
    # than one worker or instance multiplies the effective limit.
    redis_url: str = ""

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, v):
        if isinstance(v, str):
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    @field_validator("database_url", mode="before")
    @classmethod
    def _normalise_db_scheme(cls, v):
        if isinstance(v, str):
            for old, new in _PG_SCHEME_FIXES.items():
                if v.startswith(old):
                    return new + v[len(old) :]
        return v

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    @property
    def ai_enabled(self) -> bool:
        return bool(self.gemini_api_key)

    @property
    def uses_s3(self) -> bool:
        return self.media_storage.lower() == "s3" and bool(self.s3_bucket)

    def readiness(self) -> dict[str, object]:
        """What is actually wired up, and what is silently degraded.

        Exposed on /health so a deployment can be checked without reading logs.
        """
        return {
            "env": self.env,
            "ai_features": self.ai_enabled,
            "durable_media_storage": self.uses_s3,
            "shared_rate_limit_store": bool(self.redis_url),
        }

    def production_blockers(self) -> list[str]:
        """Misconfiguration that must stop a production boot outright."""
        problems: list[str] = []
        if not self.is_production:
            return problems
        if self.jwt_secret == "change-me-in-production" or len(self.jwt_secret) < 32:
            problems.append(
                "JWT_SECRET must be a real secret of at least 32 characters "
                "(generate: python -c \"import secrets; print(secrets.token_urlsafe(64))\")"
            )
        if not self.cors_origins:
            problems.append("CORS_ORIGINS must list your deployed frontend origin.")
        if any(o == "*" for o in self.cors_origins):
            problems.append('CORS_ORIGINS must not be "*".')
        if any(
            o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
            for o in self.cors_origins
        ):
            problems.append("CORS_ORIGINS must use https:// for a deployed frontend.")
        if self.app_base_url.startswith("http://") and "localhost" not in self.app_base_url:
            problems.append("APP_BASE_URL must be the https:// URL of your frontend.")
        return problems

    def production_warnings(self) -> list[str]:
        """Things that will work but degrade quietly in production."""
        if not self.is_production:
            return []
        warnings: list[str] = []
        if not self.uses_s3:
            warnings.append(
                "MEDIA_STORAGE is not 's3': resumes and profile pictures are written to "
                "local disk and WILL be deleted on the next redeploy. Configure Cloudflare R2."
            )
        if not self.ai_enabled:
            warnings.append(
                "GEMINI_API_KEY is unset: resume analysis, match scoring and document "
                "generation are all disabled. That is the core of the product."
            )
        if not self.redis_url:
            warnings.append(
                "REDIS_URL is unset: rate limiting is per-process, so it is only accurate "
                "on a single instance with a single worker."
            )
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
