FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock* README.md ./
COPY packages/things-sdk/pyproject.toml packages/things-sdk/README.md packages/things-sdk/
COPY src/things_sdk/ packages/things-sdk/src/things_sdk/
RUN uv sync --frozen --no-dev --no-install-project

COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim

WORKDIR /app
COPY --from=builder /app/.venv /app/.venv
ENV PATH="/app/.venv/bin:$PATH"

RUN mkdir -p /app/data

EXPOSE 8000
CMD ["uvicorn", "things_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
