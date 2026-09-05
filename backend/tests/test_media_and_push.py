"""Profile picture uploads and web-push subscription lifecycle."""

import io
from types import SimpleNamespace

from PIL import Image
from sqlalchemy import select


def png_bytes(size=(600, 400), mode="RGBA"):
    buf = io.BytesIO()
    Image.new(mode, size, (10, 120, 90, 255)).save(buf, format="PNG")
    return buf.getvalue()


# --- Uploads --------------------------------------------------------------


def test_upload_is_reencoded_and_bounded(client, auth):
    """Re-encoding is the security boundary: it proves the bytes are an image
    and strips anything embedded alongside."""
    headers, _, _ = auth()
    r = client.post(
        "/api/profile/picture",
        headers=headers,
        files={"file": ("avatar.png", png_bytes((900, 700)), "image/png")},
    )
    assert r.status_code == 200
    url = r.json()["profile_picture_url"]
    assert url and url.endswith(".jpg")  # re-encoded, not stored as received

    from app.config import settings

    stored = client.get(url) if url.startswith("http") else None
    if stored is None:
        from pathlib import Path

        path = Path(settings.media_local_dir) / url[len("/media/") :]
        img = Image.open(path)
        assert img.format == "JPEG" and img.mode == "RGB"
        assert max(img.size) <= settings.avatar_max_px


def test_upload_rejects_a_non_image_claiming_to_be_png(client, auth):
    headers, _, _ = auth()
    r = client.post(
        "/api/profile/picture",
        headers=headers,
        files={"file": ("x.png", b"absolutely not an image", "image/png")},
    )
    assert r.status_code == 422


def test_upload_rejects_disallowed_content_type(client, auth):
    headers, _, _ = auth()
    r = client.post(
        "/api/profile/picture",
        headers=headers,
        files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")},
    )
    assert r.status_code == 415


def test_upload_rejects_oversized_file(client, auth):
    from app.config import settings

    headers, _, _ = auth()
    payload = b"\x89PNG\r\n\x1a\n" + b"0" * (settings.max_upload_bytes + 1024)
    r = client.post(
        "/api/profile/picture",
        headers=headers,
        files={"file": ("big.png", payload, "image/png")},
    )
    assert r.status_code == 413


def test_remove_picture(client, auth):
    headers, _, _ = auth()
    client.post(
        "/api/profile/picture",
        headers=headers,
        files={"file": ("a.png", png_bytes(), "image/png")},
    )
    r = client.delete("/api/profile/picture", headers=headers)
    assert r.status_code == 200 and r.json()["profile_picture_url"] is None


def test_upload_requires_auth(client):
    r = client.post(
        "/api/profile/picture", files={"file": ("a.png", png_bytes(), "image/png")}
    )
    assert r.status_code == 401


# --- Push -----------------------------------------------------------------

SUB = {
    "endpoint": "https://fcm.googleapis.com/fcm/send/test-endpoint",
    "keys": {"p256dh": "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U",
             "auth": "tBHItJI5svbpez7KI4CCXg"},
}


def test_push_config_exposes_the_public_key_only(client, auth):
    headers, _, _ = auth()
    body = client.get("/api/push/config", headers=headers).json()
    assert set(body) == {"enabled", "public_key", "subscriptions"}
    assert "private" not in str(body).lower()


def test_subscribe_is_idempotent_then_unsubscribes(client, auth):
    headers, _, _ = auth()
    sub = dict(SUB, endpoint=SUB["endpoint"] + "-a")

    assert client.post("/api/push/subscribe", json=sub, headers=headers).status_code == 201
    client.post("/api/push/subscribe", json=sub, headers=headers)
    assert client.get("/api/push/config", headers=headers).json()["subscriptions"] == 1

    assert client.post("/api/push/unsubscribe", json=sub, headers=headers).status_code == 204
    assert client.get("/api/push/config", headers=headers).json()["subscriptions"] == 0


def test_test_push_to_a_dead_endpoint_fails_cleanly(client, auth):
    """Must be a clean 409, never a 500."""
    headers, _, _ = auth()
    sub = dict(SUB, endpoint=SUB["endpoint"] + "-b")
    client.post("/api/push/subscribe", json=sub, headers=headers)
    assert client.post("/api/push/test", headers=headers).status_code == 409


def test_gone_subscriptions_are_pruned_but_transient_failures_are_kept(client, auth, db, monkeypatch):
    from pywebpush import WebPushException

    import app.services.push as push
    from app.models import PushSubscription, User

    headers, email, _ = auth()
    user = db.scalar(select(User).where(User.email == email))
    db.add(PushSubscription(user_id=user.id, endpoint="https://x.invalid/gone", p256dh="x", auth="y"))
    db.commit()

    def gone(**kwargs):
        raise WebPushException("gone", response=SimpleNamespace(status_code=410))

    monkeypatch.setattr(push, "webpush", gone)
    push.send_to_user(db, user.id, {"title": "t", "body": "b", "url": "/"})
    remaining = list(db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)))
    assert remaining == []

    db.add(PushSubscription(user_id=user.id, endpoint="https://x.invalid/flaky", p256dh="x", auth="y"))
    db.commit()

    def flaky(**kwargs):
        raise WebPushException("boom", response=SimpleNamespace(status_code=500))

    monkeypatch.setattr(push, "webpush", flaky)
    push.send_to_user(db, user.id, {"title": "t", "body": "b", "url": "/"})
    kept = list(db.scalars(select(PushSubscription).where(PushSubscription.user_id == user.id)))
    assert len(kept) == 1
