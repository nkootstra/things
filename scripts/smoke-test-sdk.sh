#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-$ROOT_DIR/dist}"
WHEEL="$(find "$DIST_DIR" -maxdepth 1 -name 'things_sdk-*.whl' | head -n 1)"

if [[ -z "$WHEEL" ]]; then
  echo "No things-sdk wheel found in $DIST_DIR" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 -m venv "$TMP_DIR/venv"
source "$TMP_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet "$WHEEL"

python - <<'PY'
from things_sdk import (
    Area,
    ChecklistItem,
    CloudClientProtocol,
    SyncCircuitOpenError,
    SyncState,
    Tag,
    Task,
    TaskService,
    ThingsClient,
    create_engine_and_session,
)

assert ThingsClient is not None
assert TaskService is not None
assert CloudClientProtocol is not None
assert Task is not None
assert Area is not None
assert Tag is not None
assert ChecklistItem is not None
assert SyncState is not None
assert SyncCircuitOpenError is not None

engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
assert engine is not None
assert session_factory is not None
print("SDK smoke test passed")
PY
