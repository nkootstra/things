FROM python:3.12-slim AS builder

# Pinned to match pyproject build-backend (uv_build>=0.9.1,<1). Bump deliberately;
# consider replacing with an immutable digest pin once Renovate/Dependabot is in place.
COPY --from=ghcr.io/astral-sh/uv:0.9.1 /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY packages/things-sdk/ packages/things-sdk/
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

# Alembic config + migration scripts must travel with the image so the
# entrypoint can run ``alembic upgrade head`` against DATABASE_URL.
COPY alembic.ini ./alembic.ini
COPY alembic/ ./alembic/
COPY scripts/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

RUN mkdir -p /app/data \
    && groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --home-dir /app --no-create-home app \
    && chown -R app:app /app/data
USER app

EXPOSE 8000
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
