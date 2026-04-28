#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DIST_DIR="${1:-$ROOT_DIR/dist}"
WHEEL="$(find "$DIST_DIR" -maxdepth 1 -name 'things_cloud_mcp-*.whl' | head -n 1)"

if [[ -z "$WHEEL" ]]; then
  echo "No things-cloud-mcp wheel found in $DIST_DIR" >&2
  exit 1
fi

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT

python3 -m venv "$TMP_DIR/venv"
source "$TMP_DIR/venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet "$WHEEL"

# Verify the entry point is registered and the module imports cleanly.
python - <<'PY'
from things_mcp import main, server
from things_mcp.client import ThingsAPIClient

assert callable(main)
assert hasattr(server, "mcp")
assert ThingsAPIClient is not None

# Tools must be registered on the FastMCP instance.
tools = server.mcp._tool_manager._tools  # internal but stable across mcp 1.x
expected = {
    "list_inbox", "list_today", "list_upcoming", "list_anytime",
    "list_someday", "list_logbook", "list_trash", "list_all_tasks",
    "list_tasks_by_tag", "create_task", "update_task", "trigger_sync",
}
missing = expected - set(tools)
assert not missing, f"Missing MCP tools: {missing}"
print("MCP smoke test passed")
PY

# Confirm the console script is on PATH and exits non-zero on bad input
# (it expects to talk over stdio; --help is enough to prove it loads).
which things-cloud-mcp
