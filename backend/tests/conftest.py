"""Shared pytest fixtures.

Every test runs against a real Postgres database, not SQLite: the schema uses
native enums and server-side defaults, so a SQLite stand-in would test something
that is not what production runs.

The API key is forced empty so the suite uses local fixtures and never spends
JSearch quota.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
ADMIN_URL = os.environ.get(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg://jobtrail:jobtrail@localhost:5433/postgres",
)
TEST_DB = os.environ.get("TEST_DATABASE_NAME", "jobtrail_pytest")

# Must be set before app.config is imported anywhere.
os.environ["DATABASE_URL"] = ADMIN_URL.rsplit("/", 1)[0] + f"/{TEST_DB}"
os.environ["RAPIDAPI_KEY"] = ""
os.environ["ADZUNA_APP_ID"] = ""
os.environ["ADZUNA_APP_KEY"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["REDIS_URL"] = ""
os.environ.setdefault("JWT_SECRET", "test-secret-not-used-in-production-abcdefgh")


def _run_sql(sql: str) -> None:
    from sqlalchemy import create_engine, text

    engine = create_engine(ADMIN_URL, isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text(sql))
    engine.dispose()


@pytest.fixture(scope="session", autouse=True)
def database():
    """Create a throwaway database, migrate it, drop it afterwards."""
    _run_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')
    _run_sql(f'CREATE DATABASE "{TEST_DB}"')

    # Run migrations in a subprocess so Alembic gets a clean interpreter state.
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND_DIR,
        capture_output=True,
        text=True,
        env={**os.environ},
    )
    if result.returncode != 0:
        raise RuntimeError(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")

    yield

    from app.db import engine

    engine.dispose()
    _run_sql(f'DROP DATABASE IF EXISTS "{TEST_DB}"')


@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """The suite signs up many users from one client IP; without this the
    5-per-hour signup limiter would fail unrelated tests."""
    from app.rate_limit import reset_all

    reset_all()
    yield


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def db():
    from app.db import SessionLocal

    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def auth(client):
    """A registered user; returns (headers, email, tokens)."""

    def _make(name="Test User"):
        email = f"t-{uuid.uuid4().hex[:10]}@example.com"
        tokens = client.post(
            "/api/auth/signup",
            json={"email": email, "password": "correct horse battery", "name": name},
        ).json()
        return (
            {"Authorization": f"Bearer {tokens['access_token']}"},
            email,
            tokens,
        )

    return _make
