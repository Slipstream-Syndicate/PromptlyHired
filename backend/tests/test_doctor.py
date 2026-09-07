"""The doctor must be honest: report real failures, never a false green."""

from app import doctor
from app.config import Settings


def test_database_and_migrations_pass_against_the_test_db(database):
    assert doctor.check_database()[0] == "PASS"
    assert doctor.check_migrations()[0] == "PASS"


def test_missing_ai_key_is_a_hard_failure_in_production(monkeypatch):
    """AI is the product now - a deployment without a key is broken, not degraded."""
    prod = Settings(
        env="production", jwt_secret="x" * 48,
        cors_origins=["https://a.netlify.app"], app_base_url="https://a.netlify.app",
    )
    monkeypatch.setattr(doctor, "settings", prod)
    status, name, detail = doctor.check_ai()
    assert status == "FAIL"
    assert "GEMINI_API_KEY" in detail



def test_missing_ai_key_is_only_a_skip_in_development(monkeypatch):
    monkeypatch.setattr(doctor, "settings", Settings(env="development"))
    assert doctor.check_ai()[0] == "SKIP"



def test_local_media_is_a_hard_failure_in_production(monkeypatch):
    prod = Settings(
        env="production", jwt_secret="x" * 48,
        cors_origins=["https://a.netlify.app"], app_base_url="https://a.netlify.app",
    )
    monkeypatch.setattr(doctor, "settings", prod)
    status, _, detail = doctor.check_media_storage()
    assert status == "FAIL"
    assert "WIPED" in detail



def test_production_url_misconfiguration_is_reported(monkeypatch):
    monkeypatch.setattr(
        doctor, "settings",
        Settings(env="production", jwt_secret="change-me-in-production"),
    )
    assert doctor.check_frontend_urls()[0] == "FAIL"
