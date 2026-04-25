#!/usr/bin/env bash
set -euo pipefail

IMAGE_TAG="${1:-things:test}"
CONTAINER_NAME="things-smoke-test"
PORT="${SMOKE_PORT:-38000}"
API_KEY="aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

cleanup() {
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker run -d \
  --name "$CONTAINER_NAME" \
  -p "$PORT":8000 \
  -e API_KEY="$API_KEY" \
  "$IMAGE_TAG" >/dev/null

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

HEALTH="$(curl -fsS "http://127.0.0.1:$PORT/health")"
READY="$(curl -fsS "http://127.0.0.1:$PORT/ready")"
TASKS="$(curl -fsS -H "X-API-Key: $API_KEY" "http://127.0.0.1:$PORT/api/tasks")"

[[ "$HEALTH" == *'"status":"ok"'* ]]
[[ "$READY" == *'"status":"ready"'* ]]
[[ "$TASKS" == '[]' ]]

echo "Docker smoke test passed"
