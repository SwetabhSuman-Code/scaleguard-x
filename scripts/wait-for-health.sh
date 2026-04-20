#!/usr/bin/env bash
set -euo pipefail

TARGET_URL="${SCALEGUARD_BASE_URL:-http://localhost:8000}/health"
TIMEOUT_SECONDS="${WAIT_FOR_HEALTH_TIMEOUT_SECONDS:-90}"
SLEEP_SECONDS="${WAIT_FOR_HEALTH_POLL_SECONDS:-2}"
DEADLINE=$((SECONDS + TIMEOUT_SECONDS))

echo "Waiting for ${TARGET_URL} ..."

while (( SECONDS < DEADLINE )); do
  if curl --silent --fail "${TARGET_URL}" >/dev/null; then
    echo "ScaleGuard X API is healthy."
    exit 0
  fi

  sleep "${SLEEP_SECONDS}"
done

echo "Timed out waiting for ${TARGET_URL}" >&2
exit 1
