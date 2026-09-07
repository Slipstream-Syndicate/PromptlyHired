"""Profile picture storage.

Two backends behind one function. Local disk is dev-only - Render and Railway
wipe the filesystem on every redeploy, so anything deployed must point at an
S3-compatible bucket (Cloudflare R2 free tier is the intended target).

Uploads are re-encoded through Pillow rather than stored as received: that
verifies the bytes really are an image, strips any embedded payload or EXIF,
and bounds the dimensions.
"""

from __future__ import annotations

import io
import logging
import uuid
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.config import settings

logger = logging.getLogger(__name__)

ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp"}


class UploadError(ValueError):
    """Upload was rejected - the message is safe to show the user."""


def process_image(raw: bytes) -> bytes:
    """Validate, flatten and resize to a square-bounded JPEG."""
    if len(raw) > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes // (1024 * 1024)
        raise UploadError(f"Image is too large (max {limit_mb} MB).")

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise UploadError("That file is not a readable image.") from exc

    # Drop alpha onto white so the re-encode to JPEG is predictable.
    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGBA")
        background = Image.new("RGB", image.size, (255, 255, 255))
        background.paste(image, mask=image.split()[-1])
        image = background
    else:
        image = image.convert("RGB")

    max_px = settings.avatar_max_px
    if max(image.size) > max_px:
        image.thumbnail((max_px, max_px), Image.LANCZOS)

    out = io.BytesIO()
    image.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()


def _s3_client():
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url or None,
        aws_access_key_id=settings.s3_access_key_id or None,
        aws_secret_access_key=settings.s3_secret_access_key or None,
        region_name=settings.s3_region,
    )


def store_avatar(user_id: int, raw: bytes) -> str:
    """Store the processed image and return its public URL."""
    data = process_image(raw)
    key = f"avatars/{user_id}/{uuid.uuid4().hex}.jpg"

    if settings.uses_s3:
        client = _s3_client()
        client.put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=data,
            ContentType="image/jpeg",
            CacheControl="public, max-age=31536000, immutable",
        )
        base = settings.s3_public_base_url.rstrip("/")
        if not base:
            raise UploadError("S3_PUBLIC_BASE_URL is not configured.")
        return f"{base}/{key}"

    root = Path(settings.media_local_dir)
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    logger.info("Stored avatar on local disk at %s (dev only)", path)
    # Served by the /media mount in main.py.
    return f"/media/{key}"


def delete_stored_file(url: str | None) -> None:
    """Best-effort cleanup of a stored object (avatar or resume); never fatal."""
    if not url:
        return
    try:
        if settings.uses_s3:
            base = settings.s3_public_base_url.rstrip("/")
            if base and url.startswith(base):
                _s3_client().delete_object(
                    Bucket=settings.s3_bucket, Key=url[len(base) + 1 :]
                )
        elif url.startswith("/media/"):
            path = Path(settings.media_local_dir) / url[len("/media/") :]
            path.unlink(missing_ok=True)
    except Exception:  # noqa: BLE001 - cleanup must never break the request
        logger.warning("Could not delete stored file %s", url, exc_info=True)


def store_resume(user_id: int, raw: bytes, filename: str, content_type: str) -> str:
    """Store an uploaded resume verbatim and return its URL.

    Unlike avatars, the bytes are NOT re-encoded - a resume must stay the exact
    file the user uploaded so they can download the original back. Safety comes
    from never serving it as an inline document: the extension is fixed from the
    declared type, and the content is only ever parsed, never executed.
    """
    ext = {
        "application/pdf": "pdf",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
        "text/plain": "txt",
    }.get(content_type, "bin")
    key = f"resumes/{user_id}/{uuid.uuid4().hex}.{ext}"

    if settings.uses_s3:
        base = settings.s3_public_base_url.rstrip("/")
        if not base:
            raise UploadError("S3_PUBLIC_BASE_URL is not configured.")
        _s3_client().put_object(
            Bucket=settings.s3_bucket,
            Key=key,
            Body=raw,
            ContentType=content_type,
            # Force a download rather than letting a browser render an uploaded
            # file in the bucket's origin.
            ContentDisposition=f'attachment; filename="{Path(filename).name}"',
        )
        return f"{base}/{key}"

    path = Path(settings.media_local_dir) / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    logger.info("Stored resume on local disk at %s (dev only)", path)
    return f"/media/{key}"
