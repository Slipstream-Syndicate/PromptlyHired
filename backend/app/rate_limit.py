"""Brute-force protection for the auth endpoints.

Two backends behind one interface:
  * Redis, when REDIS_URL is set - correct across workers and instances.
  * In-process sliding window otherwise - correct only for a single worker.

Production logs a warning when it falls back, because a per-process limiter
silently multiplies the effective limit by the number of workers.
"""

# No `from __future__ import annotations` here on purpose: RateLimit is used as
# a callable *instance* dependency, and FastAPI cannot resolve string
# annotations on an instance (it has no __globals__), so `request: Request`
# would be misread as a query parameter.

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status

from app.config import settings

logger = logging.getLogger(__name__)


class SlidingWindowLimiter:
    def __init__(self, max_requests: int, window_seconds: int) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str):
        """Return None if allowed, else the number of seconds to wait."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] < cutoff:
                hits.popleft()
            if len(hits) >= self.max_requests:
                return max(1, int(hits[0] + self.window_seconds - now))
            hits.append(now)
            if len(self._hits) > 10_000:
                self._evict(cutoff)
            return None

    def _evict(self, cutoff: float) -> None:
        stale = [k for k, v in self._hits.items() if not v or v[-1] < cutoff]
        for k in stale:
            del self._hits[k]

    def reset(self, key: str) -> None:
        with self._lock:
            self._hits.pop(key, None)


class RedisLimiter:
    """Fixed-window counter in Redis: INCR plus an EXPIRE on first hit."""

    def __init__(self, max_requests: int, window_seconds: int, client) -> None:
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.client = client

    def check(self, key: str):
        try:
            pipe = self.client.pipeline()
            pipe.incr(key)
            pipe.ttl(key)
            count, ttl = pipe.execute()
            if ttl < 0:
                self.client.expire(key, self.window_seconds)
                ttl = self.window_seconds
            if count > self.max_requests:
                return max(1, int(ttl))
            return None
        except Exception:  # noqa: BLE001
            # A limiter outage must not take auth down with it.
            logger.warning("Rate limit store unavailable, allowing request", exc_info=True)
            return None


_redis_client = None
_redis_failed = False


def _get_redis():
    global _redis_client, _redis_failed
    if _redis_client is not None or _redis_failed or not settings.redis_url:
        return _redis_client
    try:
        import redis

        client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        logger.info("Rate limiting backed by Redis")
    except Exception:  # noqa: BLE001
        _redis_failed = True
        logger.warning("REDIS_URL set but unreachable - using in-process limiter", exc_info=True)
    return _redis_client


def client_ip(request: Request) -> str:
    # Railway/Render/Vercel sit behind a proxy, so trust the first hop of
    # X-Forwarded-For when present.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


class RateLimit:
    """FastAPI dependency: `Depends(RateLimit("login", 10, 300))`."""

    def __init__(self, bucket: str, max_requests: int, window_seconds: int) -> None:
        self.bucket = bucket
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._local = SlidingWindowLimiter(max_requests, window_seconds)

    def _limiter(self):
        client = _get_redis()
        if client is not None:
            return RedisLimiter(self.max_requests, self.window_seconds, client)
        return self._local

    def __call__(self, request: Request) -> None:
        key = f"ratelimit:{self.bucket}:{client_ip(request)}"
        retry_after = self._limiter().check(key)
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


login_rate_limit = RateLimit("login", max_requests=10, window_seconds=300)
signup_rate_limit = RateLimit("signup", max_requests=5, window_seconds=3600)
refresh_rate_limit = RateLimit("refresh", max_requests=60, window_seconds=3600)


def reset_all() -> None:
    """Clear every in-process counter.

    Exists for tests: the suite signs up far more than 5 users an hour from one
    client IP, which would otherwise trip the signup limiter and fail unrelated
    tests. Not wired to any route.
    """
    for limiter in (login_rate_limit, signup_rate_limit, refresh_rate_limit):
        limiter._local._hits.clear()
