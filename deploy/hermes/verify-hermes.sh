#!/bin/sh
# End-to-end operational check for the DS920+ Hermes deployment.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-verify.log}"
STEP_TIMEOUT="${HERMES_STEP_TIMEOUT:-900}"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"
: > "$LOG"

run_step() {
  NAME="$1"
  shift
  {
    echo
    echo "===== $NAME ====="
    date
    if command -v timeout >/dev/null 2>&1; then
      timeout "$STEP_TIMEOUT" "$@"
    else
      "$@"
    fi
    RC=$?
    echo "STEP_EXIT_CODE=$RC"
  } >> "$LOG" 2>&1
  return "$RC"
}

{
  echo "Writing verification log to $LOG"
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo "SCRIPT=$SCRIPT_DIR/verify-hermes.sh"
} >> "$LOG"
echo "Writing verification log to $LOG"

if [ "${HERMES_SKIP_START:-0}" = "1" ]; then
  {
    echo
    echo "===== start-hermes ====="
    date
    echo "SKIPPED: HERMES_SKIP_START=1"
    echo "STEP_EXIT_CODE=0"
  } >> "$LOG" 2>&1
  START_RC=0
else
  run_step "start-hermes" sh "$SCRIPT_DIR/start-hermes.sh"
  START_RC=$?
fi

run_step "wait-hermes-api" sh "$SCRIPT_DIR/wait-hermes-api.sh" "$LOG_DIR/hermes-wait.log"
WAIT_RC=$?

run_step "check-hermes" sh "$SCRIPT_DIR/check-hermes.sh" "$LOG_DIR/hermes-check.log"
CHECK_RC=$?

run_step "test-hermes-skills" sh "$SCRIPT_DIR/test-hermes-skills.sh" "$LOG_DIR/hermes-skills-test.log"
SKILLS_RC=$?

run_step "test-kmuwiki" sh "$SCRIPT_DIR/test-kmuwiki.sh" "$LOG_DIR/hermes-kmuwiki-test.log"
TEST_RC=$?

run_step "test-kmuwiki-workflow" sh "$SCRIPT_DIR/test-kmuwiki-workflow.sh" "$LOG_DIR/hermes-kmuwiki-workflow-test.log"
WORKFLOW_RC=$?

CHAT_RC=0
CHAT_STATUS="SKIPPED"
if [ "${HERMES_RUN_CHAT_TEST:-0}" = "1" ]; then
  run_step "test-hermes-chat" sh "$SCRIPT_DIR/test-hermes-chat.sh" "$LOG_DIR/hermes-chat-test.log"
  CHAT_RC=$?
  CHAT_STATUS="$CHAT_RC"
else
  {
    echo
    echo "===== test-hermes-chat ====="
    date
    echo "SKIPPED: set HERMES_RUN_CHAT_TEST=1 to call /v1/chat/completions"
    echo "STEP_EXIT_CODE=0"
  } >> "$LOG" 2>&1
fi

{
  echo
  echo "===== SUMMARY ====="
  echo "start-hermes=$START_RC"
  echo "wait-hermes-api=$WAIT_RC"
  echo "check-hermes=$CHECK_RC"
  echo "test-hermes-skills=$SKILLS_RC"
  echo "test-kmuwiki=$TEST_RC"
  echo "test-kmuwiki-workflow=$WORKFLOW_RC"
  echo "test-hermes-chat=$CHAT_STATUS"
  echo "logs=$LOG_DIR"
  echo "deploy_version=$DEPLOY_VERSION"
} >> "$LOG" 2>&1

if [ "$START_RC" -eq 0 ] && [ "$WAIT_RC" -eq 0 ] && [ "$CHECK_RC" -eq 0 ] && [ "$SKILLS_RC" -eq 0 ] && [ "$TEST_RC" -eq 0 ] && [ "$WORKFLOW_RC" -eq 0 ] && [ "$CHAT_RC" -eq 0 ]; then
  exit 0
fi
exit 1
