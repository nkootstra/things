#!/bin/sh
# Docker entrypoint for things-api.
#
# Runs Alembic migrations against DATABASE_URL before starting the
# FastAPI server. ``alembic upgrade head`` is idempotent — on a fresh
# database it creates the schema, and on an existing database it applies
# only outstanding migrations. Failing fast here is intentional: if the
# schema can't be brought to head, the API must not start with a stale
# or partially-migrated DB.
set -eu

cd /app

echo "[entrypoint] Running Alembic migrations..."
alembic upgrade head
echo "[entrypoint] Migrations complete. Starting uvicorn."

exec uvicorn things_api.main:app --host 0.0.0.0 --port 8000 "$@"
