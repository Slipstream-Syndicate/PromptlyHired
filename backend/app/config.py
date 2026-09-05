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

# JSearch and Adzuna disagree on the code for the same market: JSearch wants
# "uk", Adzuna's URL path wants "gb". One user-facing setting, mapped per API.
_ADZUNA_COUNTRY_ALIASES = {"uk": "gb", "en": "gb"}


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

    # One market setting for every job source (see _ADZUNA_COUNTRY_ALIASES).
    job_country: str = "us"

    rapidapi_key: str = ""
    jsearch_host: str = "jsearch.p.rapidapi.com"
    # Serve identical searches from memory for this long. The free plan is
    # ~200 calls/month, and building a UI means re-running the same search
    # constantly; 0 disables the cache.
    jsearch_cache_ttl_minutes: int = 15
    # Each digest run costs one upstream call per followed company.
    digest_max_companies: int = 5

    # Adzuna: secondary job source for broader coverage. Unset = disabled,
    # and JSearch alone still serves the feed.
    adzuna_app_id: str = ""
    adzuna_app_key: str = ""

    # Follow-up reminders: nudge about applications that have gone quiet.
    follow_up_after_days: int = 14
    reminder_repeat_days: int = 7

    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "JobTrail <no-reply@jobtrail.app>"
    app_base_url: str = "http://localhost:5173"

    # Web push. Email stays the reliable channel; push is the enhancement, so
    # an unset keypair disables push without breaking notifications.
    vapid_private_key: str = ""
    vapid_public_key: str = ""
    vapid_subject: str = "mailto:admin@example.com"

    # Profile pictures. Local disk is dev-only: Render/Railway wipe it on every
    # redeploy, so deployments need an S3-compatible bucket (Cloudflare R2).
    media_storage: str = "local"
    media_local_dir: str = "media"
    s3_endpoint_url: str = ""
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_public_base_url: str = ""
    s3_region: str = "auto"
    max_upload_bytes: int = 5 * 1024 * 1024
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
    def jsearch_country(self) -> str:
        return self.job_country.lower()

    @property
    def adzuna_country(self) -> str:
        c = self.job_country.lower()
        return _ADZUNA_COUNTRY_ALIASES.get(c, c)

    @property
    def push_enabled(self) -> bool:
        return bool(self.vapid_private_key and self.vapid_public_key)

    @property
    def adzuna_enabled(self) -> bool:
        return bool(self.adzuna_app_id and self.adzuna_app_key)

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host)

    @property
    def uses_s3(self) -> bool:
        return self.media_storage.lower() == "s3" and bool(self.s3_bucket)

    def readiness(self) -> dict[str, object]:
        """What is actually wired up, and what is silently degraded.

        Exposed on /health so a deployment can be checked without reading logs.
        """
        return {
            "env": self.env,
            "live_job_listings": bool(self.rapidapi_key),
            "secondary_source_adzuna": self.adzuna_enabled,
            "email_notifications": self.email_enabled,
            "web_push": self.push_enabled,
            "durable_media_storage": self.uses_s3,
            "shared_rate_limit_store": bool(self.redis_url),
            "job_country": self.job_country,
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
        if any(o.startswith("http://") and "localhost" not in o and "127.0.0.1" not in o
               for o in self.cors_origins):
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
                "MEDIA_STORAGE is not 's3': profile pictures are written to local disk "
                "and WILL be deleted on the next redeploy. Configure Cloudflare R2."
            )
        if not self.email_enabled:
            warnings.append(
                "SMTP_HOST is unset: digest and reminder emails will be logged, not sent. "
                "Email is the baseline notification channel."
            )
        if not self.rapidapi_key:
            warnings.append("RAPIDAPI_KEY is unset: the feed will serve sample listings.")
        if not self.push_enabled:
            warnings.append("VAPID keys unset: web push is disabled (email still works).")
        if not self.redis_url:
            warnings.append(
                "REDIS_URL is unset: auth rate limiting is per-process, so it is only "
                "accurate on a single instance with a single worker."
            )
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
