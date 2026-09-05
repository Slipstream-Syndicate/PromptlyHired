#!/usr/bin/env sh
# Production entrypoint: migrate, then serve.
#
# Migrations run before the server binds so a deploy either comes up with the
# right schema or fails loudly - never serves traffic against an old one.
set -e

echo "Running database migrations..."
python -m alembic upgrade head

echo "Starting API on port ${PORT:-8000}..."
exec python -m uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers "${WEB_CONCURRENCY:-1}" \
  --proxy-headers \
  --forwarded-allow-ips '*'
