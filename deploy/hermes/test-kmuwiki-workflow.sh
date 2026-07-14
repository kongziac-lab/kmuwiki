#!/bin/sh
# Run the Hermes-oriented kmuwiki workflow helper: search + recurring-work draft.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-kmuwiki-workflow-test.log}"
QUERY="${KMUWIKI_TEST_QUERY:-교환학생 홍보}"
SOURCE_YEAR="${KMUWIKI_TEST_SOURCE_YEAR:-2026}"
TARGET_YEAR="${KMUWIKI_TEST_TARGET_YEAR:-2027}"
K="${KMUWIKI_TEST_K:-3}"
HELPER="/opt/data/skills/kmuwiki/kmu-wiki-search/scripts/kmuwiki_api.py"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

: > "$LOG"

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- DATE -----"
  date
  echo
  echo "----- WORKFLOW TEST -----"
  echo "query=$QUERY"
  echo "source_year=$SOURCE_YEAR"
  echo "target_year=$TARGET_YEAR"
  echo "k=$K"
} >> "$LOG" 2>&1

if command -v timeout >/dev/null 2>&1; then
  timeout 240 docker exec kmuwiki-hermes python "$HELPER" workflow \
    --query "$QUERY" \
    --source-year "$SOURCE_YEAR" \
    --target-year "$TARGET_YEAR" \
    --k "$K" >> "$LOG" 2>&1
  RC=$?
else
  docker exec kmuwiki-hermes python "$HELPER" workflow \
    --query "$QUERY" \
    --source-year "$SOURCE_YEAR" \
    --target-year "$TARGET_YEAR" \
    --k "$K" >> "$LOG" 2>&1
  RC=$?
fi

{
  echo
  echo "EXIT_CODE=$RC"
} >> "$LOG" 2>&1

if [ "$RC" -ne 0 ]; then
  echo "WORKFLOW_CHECK=FAILED" >> "$LOG"
  echo "Wrote $LOG"
  exit "$RC"
fi

if grep -q '"search"' "$LOG" && grep -q '"hermes"' "$LOG"; then
  echo "WORKFLOW_CHECK=FOUND_KEYS" >> "$LOG"
  echo "Wrote $LOG"
  exit 0
fi

echo "WORKFLOW_CHECK=MISSING_KEYS" >> "$LOG"
echo "Wrote $LOG"
exit 1
