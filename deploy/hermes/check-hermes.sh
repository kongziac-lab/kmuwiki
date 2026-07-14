#!/bin/sh
# Write a Hermes health/API diagnostic log without printing secrets.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kmuwiki_hermes}"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-check.log}"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"
: > "$LOG"
TMP_HEADERS="$LOG_DIR/.hermes-check-headers.$$"
TMP_BODY="$LOG_DIR/.hermes-check-body.$$"
CHECK_RC=0

cleanup() {
  rm -f "$TMP_HEADERS" "$TMP_BODY"
}
trap cleanup EXIT

if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  echo "ERROR: docker compose / docker-compose not found" >> "$LOG"
  exit 1
fi

sh "$SCRIPT_DIR/wait-hermes-api.sh" "$LOG_DIR/hermes-wait.log" >> "$LOG" 2>&1
WAIT_RC=$?
if [ "$WAIT_RC" -ne 0 ]; then
  CHECK_RC=1
fi

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- PS -----"
  $DC -f docker-compose.yml ps
  echo
  echo "----- LOGS -----"
  $DC -f docker-compose.yml logs --no-color --tail=160 hermes
  echo
  echo "----- ENV CHECK -----"
} >> "$LOG" 2>&1

KEY="$(awk -F= '/^API_SERVER_KEY=/ {print substr($0, index($0, "=") + 1)}' .env | tail -n 1 | tr -d '\r\n')"
{
  echo "API_SERVER_KEY length: ${#KEY}"
} >> "$LOG" 2>&1

check_url() {
  NAME="$1"
  URL="$2"
  REQUIRED="$3"
  AUTH="$4"

  {
    echo
    echo "----- $NAME -----"
  } >> "$LOG" 2>&1

  if [ "$AUTH" = "auth" ]; then
    STATUS="$(curl -sS -D "$TMP_HEADERS" -o "$TMP_BODY" -w '%{http_code}' \
      -H "Authorization: Bearer $KEY" \
      "$URL" 2>>"$LOG")"
  else
    STATUS="$(curl -sS -D "$TMP_HEADERS" -o "$TMP_BODY" -w '%{http_code}' \
      "$URL" 2>>"$LOG")"
  fi
  CURL_RC=$?

  {
    cat "$TMP_HEADERS" 2>/dev/null
    cat "$TMP_BODY" 2>/dev/null
    echo
    echo "HTTP_STATUS=$STATUS"
    echo "CURL_EXIT_CODE=$CURL_RC"
  } >> "$LOG" 2>&1

  if [ "$REQUIRED" = "required" ]; then
    if [ "$CURL_RC" -ne 0 ] || [ "$STATUS" != "200" ]; then
      CHECK_RC=1
    fi
  fi
}

# /health is useful when present, but older Hermes images may not expose it.
check_url "/health" "http://127.0.0.1:8642/health" "optional" "noauth"
check_url "/v1/capabilities" "http://127.0.0.1:8642/v1/capabilities" "required" "auth"
check_url "/v1/models" "http://127.0.0.1:8642/v1/models" "required" "auth"

echo "Wrote $LOG"
exit "$CHECK_RC"
