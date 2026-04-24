# Things API

RESTful API over Things3 data. Syncs bidirectionally with Things Cloud via the reverse-engineered sync protocol and exposes your tasks, projects, areas, and tags over HTTP.

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
| `API_KEY` | Yes | — | API key for authentication. Must be at least 32 characters. Passed via `X-API-Key` header. |
| `THINGS_EMAIL` | Yes | — | Your Things Cloud account email |
| `THINGS_PASSWORD` | Yes | — | Your Things Cloud account password |
| `SYNC_INTERVAL_SECONDS` | No | `0` | Background sync interval in seconds. `0` disables background sync. Recommended: `60`. |
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
POST   /api/sync            # Manually trigger a full pull + push cycle (rate limited to 1/min)
```

### Health

```
GET    /health              # Health check (no auth required)
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

Requires Python 3.12+ and [uv](https://docs.astral.sh/uv/).

```sh
# Install dependencies
uv sync

# Run the dev server
uv run uvicorn things_api.main:app --reload

# Run tests
uv run pytest -v
```

## Deploying with Docker

```sh
docker compose up -d
```

The Docker setup uses a named volume (`things-data`) to persist the SQLite database across container restarts.

For production, put a reverse proxy (Caddy, nginx, Traefik) in front for TLS termination:

```
                   ┌──────────┐      ┌──────────────┐
  HTTPS :443  ───▶ │  Caddy   │ ───▶ │  Things API  │
                   │  (TLS)   │      │  :8000       │
                   └──────────┘      └──────────────┘
```

## Project Structure

```
src/things_api/
├── main.py              # FastAPI app, lifespan, scheduler wiring
├── config.py            # pydantic-settings configuration
├── auth.py              # API key authentication
├── api/
│   └── routes.py        # All API endpoints
├── cloud/
│   ├── client.py        # Things Cloud HTTP client
│   ├── schema.py        # Wire format Pydantic models
│   ├── sync.py          # Pull and push sync engines
│   └── scheduler.py     # Background sync loop
└── db/
    ├── engine.py        # SQLAlchemy async engine + session
    └── models.py        # ORM models (Task, Area, Tag, ChecklistItem, SyncState)
```
