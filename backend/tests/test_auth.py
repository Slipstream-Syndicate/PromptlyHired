"""Auth: registration, login, token rotation, and the brute-force limiter."""

import uuid

import pytest

PW = "correct horse battery"


def test_health_reports_readiness(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    # Readiness flags let a deployment be checked without reading logs.
    for key in ("live_job_listings", "ai_features", "durable_media_storage"):
        assert key in body


def test_signup_returns_tokens(client):
    email = f"s-{uuid.uuid4().hex[:8]}@example.com"
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "A"})
    assert r.status_code == 201
    assert r.json()["access_token"] and r.json()["refresh_token"]


def test_duplicate_signup_conflicts(client):
    email = f"d-{uuid.uuid4().hex[:8]}@example.com"
    client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "A"})
    r = client.post("/api/auth/signup", json={"email": email, "password": PW, "name": "B"})
    assert r.status_code == 409


@pytest.mark.parametrize(
    "password,expected",
    [("short", 422), ("x" * 73, 422)],  # under 8, and over bcrypt's 72-byte limit
)
def test_password_bounds_rejected(client, password, expected):
    r = client.post(
        "/api/auth/signup",
        json={"email": f"p-{uuid.uuid4().hex[:8]}@example.com", "password": password, "name": "A"},
    )
    assert r.status_code == expected


def test_wrong_password_is_401(client, auth):
    _, email, _ = auth()
    r = client.post("/api/auth/login", json={"email": email, "password": "nope-nope-nope"})
    assert r.status_code == 401


def test_unknown_email_is_401_not_404(client):
    """Must not reveal whether an account exists."""
    r = client.post("/api/auth/login", json={"email": "nobody@example.com", "password": PW})
    assert r.status_code == 401


def test_me_requires_auth(client, auth):
    assert client.get("/api/auth/me").status_code == 401
    headers, email, _ = auth()
    r = client.get("/api/auth/me", headers=headers)
    assert r.status_code == 200 and r.json()["email"] == email


def test_refresh_rotates_and_revokes_the_old_token(client, auth):
    _, _, tokens = auth()
    old = tokens["refresh_token"]

    r = client.post("/api/auth/refresh", json={"refresh_token": old})
    assert r.status_code == 200
    new = r.json()["refresh_token"]
    assert new != old

    # Replaying a spent refresh token must fail.
    assert client.post("/api/auth/refresh", json={"refresh_token": old}).status_code == 401


def test_logout_revokes_the_refresh_token(client, auth):
    headers, _, tokens = auth()
    token = tokens["refresh_token"]
    assert client.post("/api/auth/logout", json={"refresh_token": token}).status_code == 204
    assert client.post("/api/auth/refresh", json={"refresh_token": token}).status_code == 401


def test_login_is_rate_limited(client):
    """10 attempts per 5 minutes, then 429."""
    from app.rate_limit import reset_all

    reset_all()
    payload = {"email": "nobody@example.com", "password": "wrong"}
    codes = [client.post("/api/auth/login", json=payload).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429 and codes[11] == 429
    reset_all()


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-frame-options"] == "DENY"
