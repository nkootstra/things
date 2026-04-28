#!/usr/bin/env bash
set -euo pipefail

VERSION="${1:?usage: verify-published-mcp.sh <version>}"
PACKAGE="things-mcp==${VERSION}"
TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

for attempt in {1..24}; do
  echo "Attempt ${attempt}: installing ${PACKAGE} from PyPI"

  python3 -m venv "$TMP_DIR/venv"
  source "$TMP_DIR/venv/bin/activate"
  pip install --quiet --upgrade pip >/dev/null

  if pip install --quiet "$PACKAGE"; then
    python - <<'PY'
from things_mcp import main, server
from things_mcp.client import ThingsAPIClient

assert callable(main)
assert hasattr(server, "mcp")
assert ThingsAPIClient is not None
print("Published MCP verification passed")
PY
    which things-mcp
    exit 0
  fi

  deactivate || true
  rm -rf "$TMP_DIR/venv"
  sleep 10
done

echo "Failed to install ${PACKAGE} from PyPI after multiple attempts" >&2
exit 1
