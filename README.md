# Things API

RESTful API over Things3 data. Syncs bidirectionally with Things Cloud via the reverse-engineered sync protocol and exposes your tasks, projects, areas, and tags over HTTP/HTTPS.

> Looking for the Python library instead of the HTTP service? See [`packages/things-sdk/README.md`](packages/things-sdk/README.md).

## Which package should I use?

This repository ships **two related products**:

| Use case | What to use |
|---|---|
| You want a hosted/self-hosted HTTP/HTTPS API | `things-api` |
| You want to build a CLI, script, worker, MCP server, or integration in Python | `things-sdk` |

If you just want to run a server and call it over HTTP/HTTPS, continue with the API docs below.
If you want to embed the core functionality directly in Python, jump to the SDK README.

## Quick Start

```sh
cp .env.example .env
# Edit .env with your Things Cloud credentials and a strong API key

docker compose up -d
```

The API is available at `http://localhost:3117`. Interactive docs at `http://localhost:3117/docs`.

## Configuration

All settings are configured via environment variables (or a `.env` file):

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `API_KEY` | Yes | — | Primary API key for authentication. Must be at least 32 characters. Passed via `X-API-Key` header. |
| `API_KEY_NEXT` | No | — | Optional secondary API key for zero-downtime key rotation. |
| `THINGS_EMAIL` | Yes | — | Your Things Cloud account email |
| `THINGS_PASSWORD` | Yes | — | Your Things Cloud account password |
| `SYNC_INTERVAL_SECONDS` | No | `0` | Background sync interval in seconds. `0` disables background sync. Recommended: `60`. |
| `ENABLE_SCHEDULER` | No | `true` | Enable background scheduler in this process. |
| `SCHEDULER_LOCK_SECONDS` | No | `30` | Distributed scheduler leadership lease duration. Only the lock owner runs background sync. |
| `SCHEDULER_HEARTBEAT_SECONDS` | No | `10` | Lease renewal interval for scheduler leadership. |
| `MANUAL_SYNC_LOCK_SECONDS` | No | `120` | Lease duration for manual sync lock to prevent overlapping `POST /api/sync` runs. |
| `SYNC_RETRY_ATTEMPTS` | No | `3` | Number of retry attempts for transient cloud pull/push failures. |
| `SYNC_RETRY_BASE_SECONDS` | No | `0.25` | Exponential backoff base delay for retries. |
| `SYNC_CIRCUIT_BREAKER_FAILURES` | No | `3` | Consecutive sync failures required to open the circuit breaker. |
| `SYNC_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | No | `60` | Cooldown period while breaker is open before a half-open probe is allowed. |
| `READINESS_MAX_SYNC_ERRORS` | No | `5` | Degrade `/ready` when total sync errors exceed this threshold. |
| `DATABASE_URL` | No | `sqlite+aiosqlite:///./data/things.db` | SQLAlchemy database URL |

## API Endpoints

All `/api/*` endpoints require the `X-API-Key` header.

### Tasks

```
GET    /api/tasks          # List all non-trashed tasks
GET    /api/tasks/{uuid}   # Get a single task
POST   /api/tasks          # Create a task
PATCH  /api/tasks/{uuid}   # Update a task
DELETE /api/tasks/{uuid}   # Soft-delete (trash) a task
```

### Read-only

```
GET    /api/areas           # List all areas
GET    /api/tags            # List all tags
```

### Sync

```
GET    /api/sync/status     # Current sync state (status, head index, last sync time, errors)
POST   /api/sync            # Manually trigger a full pull + push cycle (rate limited; overlap protected by lock)
```

### Health

```
GET    /health              # Liveness check (no auth required)
GET    /ready               # Readiness check (DB + sync degradation/circuit state)
```

### Create a task

```sh
curl -X POST http://localhost:3117/api/tasks \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"title": "Buy milk", "schedule": 1}'
```

### Update a task

```sh
curl -X PATCH http://localhost:3117/api/tasks/{uuid} \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{"status": 3}'
```

Status values: `0` = pending, `2` = cancelled, `3` = completed.
Schedule values: `0` = inbox, `1` = anytime, `2` = someday.
Type values: `0` = task, `1` = project.

## How Sync Works

The sync mechanism mirrors how Things3 itself operates:

| Trigger | Behavior |
|---------|----------|
| API write (create/update/delete) | Task is flagged for push. Next sync cycle sends it to Things Cloud. |
| Background interval | Pulls remote changes, then pushes local changes. Configurable via `SYNC_INTERVAL_SECONDS`. |
| Manual trigger | `POST /api/sync` runs an immediate pull + push cycle. |

Things Cloud uses an event-sourced model with a monotonically increasing index. Each sync pulls all changes since the last known index and applies them locally. Conflicts are resolved with remote-wins semantics.

## Local Development

The repository uses a uv workspace:
- root package: `things-api`
- workspace package: `things-sdk`

```sh
# Install both packages in editable mode
uv sync
```

You can then run the API or import `things_sdk` directly in local scripts/tests.


Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# Install dependencies
uv sync

# Run the dev server
uv run uvicorn things_api.main:app --reload

# Run tests
uv run pytest -v

# Run migrations
uv run alembic upgrade head
```

## Deploying with Docker

```sh
docker compose up -d
```

The Docker setup uses a named volume (`things-data`) to persist the SQLite database across container restarts. The `docker-compose.yml` pulls the published image from `ghcr.io/nkootstra/things`.

For local development, build from source instead:

```sh
docker compose -f docker-compose.dev.yml up -d
```

For production, put a reverse proxy (Caddy, nginx, Traefik) in front for TLS termination:

```
                   ┌──────────┐      ┌──────────────┐
  HTTPS :443  ───▶ │  Caddy   │ ───▶ │  Things API  │
                   │  (TLS)   │      │  :8000       │
                   └──────────┘      └──────────────┘
```

## CI / Release smoke checks

The automation now verifies that published artifacts are actually usable:
- **SDK smoke test**: build wheel, install it into a clean virtualenv, import `things_sdk`, and verify basic engine creation
- **Docker smoke test**: build image, boot container, and verify `/health`, `/ready`, and authenticated `GET /api/tasks`

This means a green release is not just "built" — it has also been smoke-tested as an installable SDK and runnable container image.

## Releasing a New Version

Releases are fully automated via GitHub Actions. Pushing a version tag triggers the pipeline:

```
preflight (tests) ─┬─▶ build (Docker image) ─▶ release (GitHub release)
                   └─▶ publish-sdk (PyPI)
```

To release:

```sh
# 1. Update versions in both pyproject.toml files
#    - Root pyproject.toml (things-api version)
#    - packages/things-sdk/pyproject.toml (things-sdk version)
# 2. Commit the version bump
git add pyproject.toml packages/things-sdk/pyproject.toml
git commit -m "release: v0.2.0"

# 3. Tag and push
git tag v0.2.0
git push && git push --tags
```

This will:
- Run all tests (preflight gate)
- Build and push the Docker image to `ghcr.io/nkootstra/things` with tags `0.2.0`, `0.2`, and `latest`
- Publish `things-sdk` to PyPI
- Create a GitHub release with auto-generated release notes

> **Note:** PyPI publishing uses [trusted publishers](https://docs.pypi.org/trusted-publishers/). You must configure the GitHub Actions publisher for `things-sdk` on PyPI before the first publish.

## Project Structure

This project is a monorepo with two packages:

| Package | Path | Description |
|---|---|---|
| `things-sdk` | `packages/things-sdk/` | Reusable core library — models, cloud client, sync engine, task operations |
| `things-api` | root | FastAPI HTTP service built on top of the SDK |

You can use them together (run the API) or install only the SDK for scripts, CLIs, or other integrations.

### SDK standalone usage

```python
from things_sdk import ThingsClient, TaskService, configure_sync, create_engine_and_session, init_db, pull_sync

engine, session_factory = create_engine_and_session("sqlite+aiosqlite:///data/things.db")
await init_db(engine)
configure_sync(my_config)

client = ThingsClient(email="...", password="...")
async with session_factory() as session:
    await pull_sync(client, session)
    tasks = await TaskService().list_tasks(session)
await client.close()
```

See [`packages/things-sdk/README.md`](packages/things-sdk/README.md) for full SDK documentation.

### Directory layout

```
packages/things-sdk/src/things_sdk/   # SDK (reusable core)
├── __init__.py              # Public API exports
├── protocols.py             # CloudClientProtocol, SyncConfig
├── tasks.py                 # TaskService
├── cloud/
│   ├── client.py            # ThingsCloudClient
│   ├── handlers.py          # Entity handler strategy pattern
│   ├── schema.py            # Wire format Pydantic models
│   └── sync.py              # Sync engine + circuit breaker
└── db/
    ├── engine.py            # Engine factory
    └── models.py            # Domain models

src/things_api/                       # API (HTTP adapter)
├── main.py                  # FastAPI app, lifespan, scheduler
├── config.py                # pydantic-settings configuration
├── auth.py                  # API key authentication
├── api/
│   └── routes.py            # HTTP endpoints
├── cloud/
│   └── scheduler.py         # Background sync loop
└── services/
    ├── contracts.py          # API-layer service protocols
    ├── health_service.py     # Readiness checks
    ├── sync_service.py       # Manual sync orchestration
    ├── task_service.py       # Re-exports SDK TaskService
    ├── task_command_mapper.py# Request DTO mapping
    ├── scheduler_leadership.py # Distributed lock
    └── scheduler_runtime.py  # Scheduler lifecycle
```
