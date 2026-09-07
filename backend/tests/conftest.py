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
os.environ["ANTHROPIC_API_KEY"] = ""
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


# --- Resume + AI fixtures -------------------------------------------------

SAMPLE_RESUME = """
Alex Morgan
alex.morgan@example.com | London, UK

SUMMARY
Backend engineer with six years building Python services at scale.

EXPERIENCE
Senior Backend Engineer, Monzo (2021-2026)
- Designed and shipped payment reconciliation services in Python and PostgreSQL
- Led migration of a monolith to event-driven services on AWS
- Mentored three junior engineers

Backend Engineer, Deliveroo (2020-2021)
- Built order-routing APIs with FastAPI and Redis
- Cut p99 latency by 40% through query optimisation

SKILLS
Python, FastAPI, PostgreSQL, Docker, AWS, Kubernetes, Redis

EDUCATION
BSc Computer Science, University of Manchester
"""


class _FakeExtraction:
    skills = ["Python", "FastAPI", "PostgreSQL", "AWS"]
    job_titles = ["Backend Engineer", "Senior Backend Engineer"]
    domains = ["Fintech", "Food delivery"]
    locations = ["London, UK"]
    seniority = "senior"
    years_experience = 6.0
    summary = "Backend engineer with six years of Python experience."


class _FakeMatch:
    def __init__(self, pct=72):
        self.match_percentage = pct
        self.requirements_met = ["Python", "PostgreSQL"]
        self.requirements_missing = ["Go", "Kafka"]
        self.rationale = "Strong Python background; no Go or streaming experience."


class _FakeDoc:
    def __init__(self, payload):
        self._payload = payload

    def model_dump(self):
        return self._payload


@pytest.fixture
def ai_stub(monkeypatch):
    """Stub every Claude call. The suite must never spend real money."""
    from app.services import ai

    calls = {"extract": 0, "match": 0, "resume": 0, "cover": 0}

    def extract(text):
        calls["extract"] += 1
        return _FakeExtraction()

    def match(resume_text, title, company, description):
        calls["match"] += 1
        return _FakeMatch()

    def gen_resume(resume_text, title, company, description, summary="", instructions=None):
        calls["resume"] += 1
        return _FakeDoc({
            "full_name": "Alex Morgan",
            "headline": f"Backend Engineer for {company}",
            "summary": "Six years of Python.",
            "sections": [{"heading": "Experience", "bullets": ["Built services"]}],
            "skills": ["Python"],
            "instructions_seen": instructions,
        })

    def gen_cover(resume_text, title, company, description, summary="", instructions=None):
        calls["cover"] += 1
        return _FakeDoc({
            "greeting": "Dear Hiring Manager,",
            "paragraphs": [f"I am applying for {title}."],
            "closing": "Kind regards, Alex",
            "instructions_seen": instructions,
        })

    monkeypatch.setattr(ai, "extract_skill_profile", extract)
    monkeypatch.setattr(ai, "analyze_match", match)
    monkeypatch.setattr(ai, "generate_resume", gen_resume)
    monkeypatch.setattr(ai, "generate_cover_letter", gen_cover)
    # The routers imported the module, so patching the module attributes is
    # enough - they call ai.<fn> rather than holding direct references.
    return calls


@pytest.fixture
def with_resume(client, ai_stub):
    """Register a user and give them an active resume + skill profile."""

    def _make():
        import uuid as _uuid

        email = f"r-{_uuid.uuid4().hex[:10]}@example.com"
        tokens = client.post(
            "/api/auth/signup",
            json={"email": email, "password": "correct horse battery", "name": "Alex"},
        ).json()
        headers = {"Authorization": f"Bearer {tokens['access_token']}"}
        resume = client.post(
            "/api/resumes",
            headers=headers,
            files={"file": ("cv.txt", SAMPLE_RESUME.encode(), "text/plain")},
        )
        assert resume.status_code == 201, resume.text
        return headers, resume.json()

    return _make
