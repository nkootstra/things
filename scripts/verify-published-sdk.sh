#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?usage: verify-published-sdk.sh <version>}"
PACKAGE="things-sdk==${VERSION}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for attempt in {1..24}; do
  echo "Attempt ${attempt}: installing ${PACKAGE} from PyPI"

  python3 -m venv "$TMP_DIR/venv"
  source "$TMP_DIR/venv/bin/activate"
  pip install --quiet --upgrade pip >/dev/null

  if pip install --quiet "$PACKAGE"; then
    python - <<'PY'
from things_sdk import (
    ThingsClient,
    TaskService,
    create_engine_and_session,
    CloudClientProtocol,
    SyncConfig,
)
assert ThingsClient is not None
assert TaskService is not None
assert CloudClientProtocol is not None
assert SyncConfig is not None
engine, session_factory = create_engine_and_session("sqlite+aiosqlite://")
assert engine is not None
assert session_factory is not None
print("Published SDK verification passed")
PY
    exit 0
  fi

  deactivate || true
  rm -rf "$TMP_DIR/venv"
  sleep 10
done

echo "Failed to install ${PACKAGE} from PyPI after multiple attempts" >&2
exit 1
