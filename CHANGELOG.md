# Changelog

All notable changes to this project are documented here.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).  
Both packages (`things-api` and `things-sdk`) are versioned together.

> **Which package should I use?**  
> See the [repository README](README.md#which-package-should-i-use) for guidance on when to use the HTTP service vs the Python SDK.

---

## [0.2.0] — 2026-04-25

### Added
- `things-sdk` extracted as a standalone, independently installable Python package
- `packages/things-sdk/` workspace package with own `pyproject.toml`
- `things_sdk` public API (`ThingsClient`, `TaskService`, `pull_sync`, `push_sync`, `configure_sync`, domain models)
- `CloudClientProtocol` — typed protocol contract for cloud client implementations
- `SyncConfig` — injectable protocol for sync configuration
- `EntityHandler` strategy pattern for cloud sync entity types
- `EntityNotFoundError` and `ThingsSDKError` — SDK-native exceptions (no FastAPI dependency in SDK)
- SDK examples directory (`examples/sdk/`)
- Post-release verification workflow: installs `things-sdk` from PyPI and pulls Docker image from GHCR after each release
- SDK and Docker artifact smoke tests in CI
- `verify-published-sdk.sh` and `verify-published-docker.sh` scripts
- `scripts/release.sh` — automated version bump, test, commit, tag, and push
- `pyrightconfig.json` — pyright type-checking foundation
- `typecheck` job in CI pipeline
- Alembic baseline migration
- `/ready` endpoint with DB connectivity and sync degradation checks
- Circuit-breaker for cloud sync with half-open probe behavior
- Distributed scheduler leadership lock with heartbeat
- Manual sync concurrency lock (`POST /api/sync`)
- API key rotation support (`API_KEY_NEXT`)
- Sync metrics: `last_pull_skipped`, `sync_errors_total`, `consecutive_sync_errors`, `circuit_open_until`
- Multi-arch Docker images (`linux/amd64` + `linux/arm64`)
- Edge/sha image tags published on every push to `main`
- `ENABLE_SCHEDULER`, `SCHEDULER_LOCK_SECONDS`, `SCHEDULER_HEARTBEAT_SECONDS` config
- SOLID service layer: `SyncService`, `TaskService`, `HealthService`, `SchedulerLeadershipService`, `SchedulerRuntimeController`
- Service protocol contracts (`SyncServiceProtocol`, `TaskServiceProtocol`, `TaskCommandMapperProtocol`)
- Architecture guardrail tests

### Fixed
- UUID length mismatch: task UUIDs generated as 22 chars to match schema
- Timing-safe API key comparison using `secrets.compare_digest`
- Cloud client resources always closed after use (manual sync + scheduler)
- Sync item failure no longer rolls back previously applied valid items in same batch (savepoint per item)

### Changed
- `API_KEY` minimum length enforced at 32 characters
- `API_KEY_NEXT` also enforces minimum length when set

---

## [0.1.1] — 2026-04-24

### Added
- Multi-arch Docker image builds (`linux/amd64`, `linux/arm64`)
- CI Docker job: builds and pushes `edge` + `sha-*` image tags on push to `main`
- PR Docker builds (no push) for validation

---

## [0.1.0] — 2026-04-24

### Added
- Initial release
- FastAPI service syncing bidirectionally with Things Cloud
- `GET /api/tasks`, `POST /api/tasks`, `PATCH /api/tasks/{uuid}`, `DELETE /api/tasks/{uuid}`
- `GET /api/areas`, `GET /api/tags`
- `GET /api/sync/status`, `POST /api/sync`
- `GET /health`, `GET /ready`
- Background sync scheduler with configurable interval
- Pull sync with retry and error handling
- Push sync for locally modified tasks
- SQLite persistence via SQLAlchemy async
- Docker image published to GHCR
- GitHub Actions CI/release pipeline
