#!/bin/sh
# Run a kmuwiki helper smoke test inside the Hermes container and write a
# diagnostic log without printing secrets.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-kmuwiki-test.log}"
QUERY="${KMUWIKI_TEST_QUERY:-교환학생 홍보}"
SOURCE_YEAR="${KMUWIKI_TEST_SOURCE_YEAR:-2026}"
HELPER="/opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

: > "$LOG"

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- DATE -----"
  date
  echo
  echo "----- CONTAINER -----"
  docker ps -a --filter name=kmuwiki-hermes --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  echo
  echo "----- HELPER PATH -----"
  docker exec kmuwiki-hermes sh -lc "ls -l '$HELPER'"
  echo
  echo "----- ENV PRESENCE (masked) -----"
} >> "$LOG" 2>&1

docker exec -i kmuwiki-hermes python - >> "$LOG" 2>&1 <<'PY'
import os

for key in [
    "KMUWIKI_API_BASE_URL",
    "KMUWIKI_AUTH_TOKEN",
    "NEXT_PUBLIC_SUPABASE_URL",
    "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    "KMUWIKI_AUTH_EMAIL",
    "KMUWIKI_AUTH_PASSWORD",
    "KMUWIKI_API_SECRET",
]:
    value = os.environ.get(key, "")
    print(f"{key}={'SET' if value.strip() else 'EMPTY'}")
PY

{
  echo
  echo "----- SEARCH TEST -----"
  echo "query=$QUERY"
  echo "source_year=$SOURCE_YEAR"
} >> "$LOG" 2>&1

if command -v timeout >/dev/null 2>&1; then
  timeout 180 docker exec kmuwiki-hermes python "$HELPER" search \
    --query "$QUERY" \
    --source-year "$SOURCE_YEAR" >> "$LOG" 2>&1
  RC=$?
else
  docker exec kmuwiki-hermes python "$HELPER" search \
    --query "$QUERY" \
    --source-year "$SOURCE_YEAR" >> "$LOG" 2>&1
  RC=$?
fi

{
  echo
  echo "EXIT_CODE=$RC"
  echo "Wrote $LOG"
} >> "$LOG" 2>&1

echo "Wrote $LOG"
exit "$RC"
