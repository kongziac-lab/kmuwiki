#!/bin/sh
# Wait until the Hermes API server is ready to accept requests.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-wait.log}"
WAIT_SECONDS="${HERMES_WAIT_SECONDS:-120}"
INTERVAL="${HERMES_WAIT_INTERVAL:-2}"
URL="${HERMES_HEALTH_URL:-http://127.0.0.1:8642/health}"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

: > "$LOG"

START="$(date +%s)"
ATTEMPT=0

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo "----- WAIT HERMES API -----"
  date
  echo "url=$URL"
  echo "timeout_seconds=$WAIT_SECONDS"
} >> "$LOG"

while :; do
  ATTEMPT=$((ATTEMPT + 1))
  STATUS="$(curl -sS -o /dev/null -w '%{http_code}' "$URL" 2>>"$LOG")"
  CURL_RC=$?
  NOW="$(date +%s)"
  ELAPSED=$((NOW - START))

  {
    echo "attempt=$ATTEMPT elapsed=${ELAPSED}s status=$STATUS curl_exit=$CURL_RC"
  } >> "$LOG"

  if [ "$CURL_RC" -eq 0 ] && [ "$STATUS" = "200" ]; then
    echo "HERMES_API_READY=1" >> "$LOG"
    echo "Wrote $LOG"
    exit 0
  fi

  if [ "$ELAPSED" -ge "$WAIT_SECONDS" ]; then
    echo "HERMES_API_READY=0" >> "$LOG"
    echo "Wrote $LOG"
    exit 1
  fi

  sleep "$INTERVAL"
done
