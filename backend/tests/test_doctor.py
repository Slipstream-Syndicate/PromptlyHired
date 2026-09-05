"""The doctor must be honest: report real failures, never a false green."""

from app import doctor
from app.config import Settings


def test_database_and_migrations_pass_against_the_test_db(database):
    assert doctor.check_database()[0] == "PASS"
    assert doctor.check_migrations()[0] == "PASS"


def test_missing_email_is_a_hard_failure_in_production(monkeypatch):
    prod = Settings(
        env="production", jwt_secret="x" * 48,
        cors_origins=["https://a.netlify.app"], app_base_url="https://a.netlify.app",
    )
    monkeypatch.setattr(doctor, "settings", prod)
    status, name, detail = doctor.check_email(None)
    assert status == "FAIL"
    assert "SMTP_HOST" in detail


def test_missing_email_is_only_a_skip_in_development(monkeypatch):
    monkeypatch.setattr(doctor, "settings", Settings(env="development"))
    assert doctor.check_email(None)[0] == "SKIP"


def test_local_media_is_a_hard_failure_in_production(monkeypatch):
    prod = Settings(
        env="production", jwt_secret="x" * 48,
        cors_origins=["https://a.netlify.app"], app_base_url="https://a.netlify.app",
    )
    monkeypatch.setattr(doctor, "settings", prod)
    status, _, detail = doctor.check_media_storage()
    assert status == "FAIL"
    assert "WIPED" in detail


def test_malformed_vapid_key_is_caught(monkeypatch):
    """A bad key otherwise only surfaces when a real push is attempted."""
    monkeypatch.setattr(
        doctor, "settings",
        Settings(vapid_private_key="x", vapid_public_key="not-a-real-key"),
    )
    assert doctor.check_media_storage() is not None  # sanity
    assert doctor.check_push()[0] == "FAIL"


def test_valid_vapid_key_passes(monkeypatch):
    import base64
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    key = ec.generate_private_key(ec.SECP256R1())
    pub = key.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    encoded = base64.urlsafe_b64encode(pub).decode().rstrip("=")
    monkeypatch.setattr(
        doctor, "settings", Settings(vapid_private_key="x", vapid_public_key=encoded)
    )
    assert doctor.check_push()[0] == "PASS"


def test_production_url_misconfiguration_is_reported(monkeypatch):
    monkeypatch.setattr(
        doctor, "settings",
        Settings(env="production", jwt_secret="change-me-in-production"),
    )
    assert doctor.check_frontend_urls()[0] == "FAIL"
