"""Pure logic: source normalisation, cross-source merge, and deploy config.

No network and no database - these are the pieces most likely to break silently
on a deployment, so they are worth pinning down exactly.
"""

from datetime import date

import pytest

from app.config import Settings
from app.models import JobType
from app.services import adzuna, sources
from app.services.jsearch import NormalizedJob

ADZUNA_FIXTURE = {
    "id": "4321",
    "title": "Senior <strong>Backend</strong> Engineer",
    "company": {"display_name": "Acme Ltd"},
    "location": {"display_name": "London, UK", "area": ["UK", "London"]},
    "salary_min": 60000,
    "salary_max": 80000,
    "salary_is_predicted": "1",
    "redirect_url": "https://adzuna.test/job/4321",
    "created": "2026-08-20T09:00:00Z",
    "description": "Build things.",
    "contract_time": "full_time",
    "contract_type": "permanent",
}


def mk(title, company, source, ext):
    return NormalizedJob(
        external_id=ext, source_api=source, title=title, company_name=company,
        company_logo_url=None, location="London", salary_range=None, salary_min=None,
        salary_max=None, url="https://x.test", posted_date=date.today(), description="",
        job_type=None, source_publisher=source,
    )


# --- Adzuna normalisation -------------------------------------------------


def test_adzuna_normalises_a_result():
    n = adzuna.normalize(ADZUNA_FIXTURE)
    assert n is not None
    assert n.company_name == "Acme Ltd"
    assert n.url == "https://adzuna.test/job/4321"
    assert n.posted_date == date(2026, 8, 20)
    assert n.job_type is JobType.full_time
    assert n.source_publisher == "Adzuna"


def test_adzuna_strips_search_highlighting_from_titles():
    assert adzuna.normalize(ADZUNA_FIXTURE).title == "Senior Backend Engineer"


def test_predicted_salary_is_labelled_an_estimate():
    """Adzuna guesses salaries; presenting a guess as stated would mislead."""
    assert "(est.)" in adzuna.normalize(ADZUNA_FIXTURE).salary_range


def test_stated_salary_is_not_labelled_an_estimate():
    stated = dict(ADZUNA_FIXTURE, salary_is_predicted="0")
    assert "(est.)" not in adzuna.normalize(stated).salary_range


def test_adzuna_rejects_incomplete_records():
    assert adzuna.normalize({"id": "x"}) is None
    assert adzuna.normalize({"id": "x", "title": "T"}) is None


# --- Cross-source merge ---------------------------------------------------


def test_merge_drops_cross_source_duplicates():
    """The same vacancy has a different id per aggregator, so ids cannot dedupe it."""
    a = [mk("Backend Engineer", "Monzo", "jsearch", "1")]
    b = [mk("backend  engineer", "MONZO", "adzuna", "9")]
    merged = sources.merge(a, b)
    assert len(merged) == 1
    assert merged[0].source_api == "jsearch"  # primary wins


def test_merge_keeps_distinct_listings():
    a = [mk("Backend Engineer", "Monzo", "jsearch", "1")]
    b = [mk("SRE", "Cloudflare", "adzuna", "9")]
    assert len(sources.merge(a, b)) == 2


# --- Deployment configuration --------------------------------------------


@pytest.mark.parametrize(
    "raw",
    ["postgres://u:p@h/db", "postgresql://u:p@h/db", "postgresql+psycopg2://u:p@h/db"],
)
def test_platform_database_urls_are_normalised(raw):
    """Render/Railway/Heroku hand out postgres://, which SQLAlchemy 2 rejects."""
    assert Settings(database_url=raw).database_url.startswith("postgresql+psycopg://")


def test_country_code_is_mapped_per_provider():
    """JSearch wants 'uk'; Adzuna's URL path wants 'gb'."""
    s = Settings(job_country="uk")
    assert s.jsearch_country == "uk"
    assert s.adzuna_country == "gb"


def test_production_refuses_a_default_jwt_secret():
    s = Settings(env="production", jwt_secret="change-me-in-production")
    assert any("JWT_SECRET" in p for p in s.production_blockers())


def test_production_refuses_wildcard_or_insecure_cors():
    assert any("*" in p for p in Settings(env="production", jwt_secret="x" * 40,
                                          cors_origins=["*"]).production_blockers())
    assert any("https" in p for p in Settings(env="production", jwt_secret="x" * 40,
                                              cors_origins=["http://app.example.com"]).production_blockers())


def test_valid_production_config_has_no_blockers():
    s = Settings(
        env="production",
        jwt_secret="x" * 48,
        cors_origins=["https://jobtrail.netlify.app"],
        app_base_url="https://jobtrail.netlify.app",
    )
    assert s.production_blockers() == []


def test_development_never_blocks():
    assert Settings(env="development").production_blockers() == []


def test_production_warns_about_ephemeral_media_and_missing_ai():
    s = Settings(
        env="production",
        jwt_secret="x" * 48,
        cors_origins=["https://jobtrail.netlify.app"],
        app_base_url="https://jobtrail.netlify.app",
    )
    warnings = " ".join(s.production_warnings())
    assert "MEDIA_STORAGE" in warnings
    assert "ANTHROPIC_API_KEY" in warnings


def test_s3_config_silences_the_media_warning():
    s = Settings(
        env="production",
        jwt_secret="x" * 48,
        cors_origins=["https://jobtrail.netlify.app"],
        app_base_url="https://jobtrail.netlify.app",
        media_storage="s3",
        s3_bucket="jobtrail-media",
    )
    assert s.uses_s3
    assert not any("MEDIA_STORAGE" in w for w in s.production_warnings())
