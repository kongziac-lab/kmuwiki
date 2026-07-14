#!/bin/sh
# Summarize Hermes verification logs without printing secrets.

set +e

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
OUT="${1:-$LOG_DIR/hermes-status.log}"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"
: > "$OUT"

append_file_status() {
  NAME="$1"
  FILE="$2"
  {
    echo
    echo "===== $NAME ====="
    if [ -f "$FILE" ]; then
      echo "file=$FILE"
      echo "size=$(wc -c < "$FILE" | tr -d ' ')"
      echo "mtime=$(date -r "$FILE" 2>/dev/null || ls -l "$FILE" | awk '{print $6, $7, $8}')"
    else
      echo "missing=$FILE"
    fi
  } >> "$OUT" 2>&1
}

append_matches() {
  FILE="$1"
  PATTERN="$2"
  if [ -f "$FILE" ]; then
    grep -E "$PATTERN" "$FILE" >> "$OUT" 2>&1 || true
  fi
}

VERIFY="$LOG_DIR/hermes-verify.log"
CHECK="$LOG_DIR/hermes-check.log"
WAIT="$LOG_DIR/hermes-wait.log"
SKILLS="$LOG_DIR/hermes-skills-test.log"
SEARCH="$LOG_DIR/hermes-kmuwiki-test.log"
WORKFLOW="$LOG_DIR/hermes-kmuwiki-workflow-test.log"
CHAT="$LOG_DIR/hermes-chat-test.log"
SYNC="$LOG_DIR/hermes-env-sync.log"

{
  echo "Hermes status summary"
  date
  echo "log_dir=$LOG_DIR"
  echo "deploy_version=$DEPLOY_VERSION"
} >> "$OUT"

append_file_status "verify" "$VERIFY"
append_matches "$VERIFY" 'DEPLOY_VERSION=|deploy_version=|start-hermes=|wait-hermes-api=|check-hermes=|test-hermes-skills=|test-kmuwiki=|test-kmuwiki-workflow=|test-hermes-chat=|STEP_EXIT_CODE=|SKIPPED:'

append_file_status "api-wait" "$WAIT"
append_matches "$WAIT" 'DEPLOY_VERSION=|attempt=|HERMES_API_READY='

append_file_status "api-check" "$CHECK"
append_matches "$CHECK" 'API_SERVER_KEY length|HTTP_STATUS=|CURL_EXIT_CODE='

append_file_status "skills" "$SKILLS"
append_matches "$SKILLS" 'HTTP_STATUS=|CURL_EXIT_CODE=|SKILL_CHECK='

append_file_status "kmuwiki-search" "$SEARCH"
append_matches "$SEARCH" 'KMUWIKI_API_BASE_URL=|NEXT_PUBLIC_SUPABASE_URL=|NEXT_PUBLIC_SUPABASE_ANON_KEY=|KMUWIKI_AUTH_EMAIL=|KMUWIKI_AUTH_PASSWORD=|EXIT_CODE=|doc_no|document_id|filename|Supabase login failed|HTTP 401|HTTP 403'

append_file_status "kmuwiki-workflow" "$WORKFLOW"
append_matches "$WORKFLOW" 'EXIT_CODE=|WORKFLOW_CHECK=|"search"|"hermes"|Supabase login failed|HTTP 401|HTTP 403'

append_file_status "hermes-chat" "$CHAT"
append_matches "$CHAT" 'DEPLOY_VERSION=|endpoint=|model=|ENV_OPENROUTER_API_KEY=|ENV_OPENAI_API_KEY=|ENV_ANTHROPIC_API_KEY=|ENV_GEMINI_API_KEY=|ENV_GOOGLE_API_KEY=|DOTENV_OPENROUTER_API_KEY=|DOTENV_OPENAI_API_KEY=|DOTENV_ANTHROPIC_API_KEY=|DOTENV_GEMINI_API_KEY=|DOTENV_GOOGLE_API_KEY=|CONFIG_PROVIDER=|CONFIG_DEFAULT=|CONFIG_BASE_URL=|CONFIG_API_MODE=|HTTP_STATUS=|CURL_EXIT_CODE=|CHAT_CHECK=|document_id|doc_no|citation|source|evidence|FAILED|error'

append_file_status "env-sync" "$SYNC"
append_matches "$SYNC" 'DEPLOY_VERSION=|OPENROUTER_API_KEY=|OPENAI_API_KEY=|ANTHROPIC_API_KEY=|GEMINI_API_KEY=|GOOGLE_API_KEY=|provider:|default:|base_url:|api_mode:|ENV_SYNC=|RESTART_EXIT_CODE=|container_env_files_synced=|container_config_files_synced='

echo "Wrote $OUT"
