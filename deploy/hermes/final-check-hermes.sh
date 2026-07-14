#!/bin/sh
# Final DS920+ Hermes operational check.
#
# Runs the regular verification plus the optional chat-completions smoke test,
# then refreshes the short status summary. Access-log verification still belongs
# in the Supabase SQL Editor so no admin/service key is stored in Hermes.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ "$(id -u 2>/dev/null || echo 1)" != "0" ] && [ "${HERMES_SKIP_SUDO:-0}" != "1" ]; then
  if command -v sudo >/dev/null 2>&1; then
    echo "Docker on Synology usually requires root. Re-running final check with sudo..."
    exec sudo -E env HOME=/root PATH="$PATH" sh "$SCRIPT_DIR/final-check-hermes.sh" "$@"
  fi
  echo "ERROR: Docker requires root/admin privileges, and sudo was not found."
  echo "Run this script as root from DSM Task Scheduler, or SSH as a user with Docker privileges."
  exit 1
fi

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/hermes-final-check.log"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"
: > "$LOG"

{
  echo "Hermes final check"
  date
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo "SCRIPT=$SCRIPT_DIR/final-check-hermes.sh"
  echo
  echo "Running HERMES_SYNC_RESTART=1 sh sync-hermes-env.sh"
} >> "$LOG" 2>&1

HERMES_SYNC_RESTART=1 sh "$SCRIPT_DIR/sync-hermes-env.sh" "$LOG_DIR/hermes-env-sync.log" >> "$LOG" 2>&1
SYNC_RC=$?

{
  echo
  echo "ENV_SYNC_EXIT_CODE=$SYNC_RC"
  echo
  echo "Running HERMES_RUN_CHAT_TEST=1 HERMES_SKIP_START=1 sh verify-hermes.sh"
} >> "$LOG" 2>&1

HERMES_RUN_CHAT_TEST=1 \
HERMES_SKIP_START="${HERMES_SKIP_START:-1}" \
HERMES_STEP_TIMEOUT="${HERMES_STEP_TIMEOUT:-1800}" \
sh "$SCRIPT_DIR/verify-hermes.sh" "$LOG_DIR/hermes-verify.log" >> "$LOG" 2>&1
VERIFY_RC=$?

{
  echo
  echo "VERIFY_EXIT_CODE=$VERIFY_RC"
  echo
  echo "Running sh status-hermes.sh"
} >> "$LOG" 2>&1

sh "$SCRIPT_DIR/status-hermes.sh" "$LOG_DIR/hermes-status.log" >> "$LOG" 2>&1
STATUS_RC=$?

{
  echo "STATUS_EXIT_CODE=$STATUS_RC"
  echo
  echo "Supabase access-log SQL:"
  echo "$SCRIPT_DIR/access-log-check.sql"
  echo
  if [ "$SYNC_RC" -eq 0 ] && [ "$VERIFY_RC" -eq 0 ] && [ "$STATUS_RC" -eq 0 ]; then
    echo "FINAL_CHECK=PASSED"
  else
    echo "FINAL_CHECK=FAILED"
  fi
  echo "Wrote $LOG"
} >> "$LOG" 2>&1

cat "$LOG"

if [ "$SYNC_RC" -eq 0 ] && [ "$VERIFY_RC" -eq 0 ] && [ "$STATUS_RC" -eq 0 ]; then
  exit 0
fi
exit 1
