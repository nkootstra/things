#!/usr/bin/env bash
set -euo pipefail

IMAGE="${1:?usage: verify-published-docker.sh <image-ref>}"

for attempt in {1..24}; do
  echo "Attempt ${attempt}: pulling ${IMAGE} from GHCR"
  if docker pull "$IMAGE"; then
    ./scripts/smoke-test-docker.sh "$IMAGE"
    echo "Published Docker verification passed"
    exit 0
  fi
  sleep 10
done

echo "Failed to pull ${IMAGE} from GHCR after multiple attempts" >&2
exit 1
