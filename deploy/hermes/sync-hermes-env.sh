#!/bin/sh
# Sync whitelisted .env values into the running Hermes data volume.
#
# This avoids a slow docker-compose one-off preparation container during final
# checks. It never prints secret values.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-env-sync.log}"
TMP="$LOG_DIR/.hermes-env-sync.$$"
CONFIG_TMP="$LOG_DIR/.hermes-config-sync.$$"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

cleanup() {
  rm -f "$TMP" "$CONFIG_TMP"
}
trap cleanup EXIT

: > "$LOG"

if [ ! -f .env ]; then
  echo "ENV_SYNC=FAILED_NO_ENV" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

{
  printf "API_SERVER_ENABLED=true\n"
  printf "API_SERVER_HOST=0.0.0.0\n"
  printf "API_SERVER_PORT=8642\n"
  printf "HOME=/opt/data/home\n"
  printf "HERMES_HOME=/opt/data\n"
} > "$TMP"

while IFS= read -r RAW_LINE || [ -n "$RAW_LINE" ]; do
  LINE="$(printf "%s" "$RAW_LINE" | tr -d '\r')"
  case "$LINE" in
    ''|\#*) continue ;;
    *=*) ;;
    *) continue ;;
  esac
  KEY="${LINE%%=*}"
  case "$KEY" in
    API_SERVER_KEY|API_SERVER_CORS_ORIGINS|KMUWIKI_API_BASE_URL|KMUWIKI_AUTH_TOKEN|NEXT_PUBLIC_SUPABASE_URL|NEXT_PUBLIC_SUPABASE_ANON_KEY|SUPABASE_URL|SUPABASE_ANON_KEY|KMUWIKI_AUTH_EMAIL|KMUWIKI_AUTH_PASSWORD|KMUWIKI_API_SECRET|KMUWIKI_DEFAULT_K|KMUWIKI_DEFAULT_SOURCE_YEAR|KMUWIKI_DEFAULT_DEPT|OPENROUTER_API_KEY|OPENAI_API_KEY|ANTHROPIC_API_KEY|GEMINI_API_KEY|GOOGLE_API_KEY|XAI_API_KEY|DEEPSEEK_API_KEY|GROQ_API_KEY|TOGETHER_API_KEY|HERMES_MODEL_PROVIDER|HERMES_MODEL_NAME|HERMES_MODEL_BASE_URL|HERMES_MODEL_API_MODE)
      printf "%s\n" "$LINE" >> "$TMP"
      ;;
  esac
done < .env

env_value() {
  awk -F= -v key="$1" '$1 == key { value = substr($0, index($0, "=") + 1) } END { print value }' "$TMP"
}

has_env_value() {
  VALUE="$(env_value "$1")"
  [ -n "$VALUE" ]
}

MODEL_PROVIDER="$(env_value HERMES_MODEL_PROVIDER)"
MODEL_NAME="$(env_value HERMES_MODEL_NAME)"
MODEL_BASE_URL="$(env_value HERMES_MODEL_BASE_URL)"
MODEL_API_MODE="$(env_value HERMES_MODEL_API_MODE)"

if [ -z "$MODEL_PROVIDER" ]; then
  if has_env_value OPENROUTER_API_KEY; then
    MODEL_PROVIDER="openrouter"
  elif has_env_value OPENAI_API_KEY; then
    MODEL_PROVIDER="openai-api"
  elif has_env_value GEMINI_API_KEY || has_env_value GOOGLE_API_KEY; then
    MODEL_PROVIDER="gemini"
  elif has_env_value ANTHROPIC_API_KEY; then
    MODEL_PROVIDER="anthropic"
  fi
fi

if [ "$MODEL_PROVIDER" = "gemini" ]; then
  MODEL_NAME="${MODEL_NAME:-gemini-3.5-flash}"
  MODEL_BASE_URL="${MODEL_BASE_URL:-https://generativelanguage.googleapis.com/v1beta/openai}"
  MODEL_API_MODE="${MODEL_API_MODE:-chat_completions}"
fi

if [ -n "$MODEL_PROVIDER" ]; then
  {
    printf "model:\n"
    printf "  provider: %s\n" "$MODEL_PROVIDER"
    [ -n "$MODEL_NAME" ] && printf "  default: %s\n" "$MODEL_NAME"
    [ -n "$MODEL_BASE_URL" ] && printf "  base_url: %s\n" "$MODEL_BASE_URL"
    [ -n "$MODEL_API_MODE" ] && printf "  api_mode: %s\n" "$MODEL_API_MODE"
    printf "toolsets:\n"
    printf "  - hermes-cli\n"
  } > "$CONFIG_TMP"
fi

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- DATE -----"
  date
  echo
  echo "----- CONTAINER -----"
  docker ps --filter name=kmuwiki-hermes --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
  echo
  echo "----- PROVIDER KEYS IN HOST ENV FILE -----"
  for KEY in OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY XAI_API_KEY DEEPSEEK_API_KEY GROQ_API_KEY TOGETHER_API_KEY; do
    if grep -q "^$KEY=." "$TMP"; then
      echo "$KEY=SET"
    else
      echo "$KEY=EMPTY"
    fi
  done
  echo
  echo "----- MODEL CONFIG TO SYNC -----"
  if [ -s "$CONFIG_TMP" ]; then
    sed -n '1,80p' "$CONFIG_TMP"
  else
    echo "MODEL_CONFIG=SKIPPED_NO_PROVIDER"
  fi
  echo
  echo "----- SYNC -----"
} >> "$LOG" 2>&1

docker exec -i kmuwiki-hermes sh -lc '
  set -eu
  mkdir -p /opt/data/home/.hermes
  umask 077
  cat > /opt/data/.env
  cp /opt/data/.env /opt/data/home/.hermes/.env
  chmod 600 /opt/data/.env /opt/data/home/.hermes/.env 2>/dev/null || true
  chown 10000:10000 /opt/data/.env /opt/data/home/.hermes/.env 2>/dev/null || true
  echo "container_env_files_synced=1"
' < "$TMP" >> "$LOG" 2>&1
SYNC_RC=$?

if [ "$SYNC_RC" -ne 0 ]; then
  echo "ENV_SYNC=FAILED_DOCKER_EXEC" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

if [ -s "$CONFIG_TMP" ]; then
  docker exec -i kmuwiki-hermes sh -lc '
    set -eu
    mkdir -p /opt/data/home/.hermes
    cat > /opt/data/config.yaml
    cp /opt/data/config.yaml /opt/data/home/.hermes/config.yaml
    chmod 600 /opt/data/config.yaml /opt/data/home/.hermes/config.yaml 2>/dev/null || true
    chown 10000:10000 /opt/data/config.yaml /opt/data/home/.hermes/config.yaml 2>/dev/null || true
    echo "container_config_files_synced=1"
  ' < "$CONFIG_TMP" >> "$LOG" 2>&1
  CONFIG_RC=$?
  if [ "$CONFIG_RC" -ne 0 ]; then
    echo "ENV_SYNC=FAILED_CONFIG_SYNC" >> "$LOG"
    echo "Wrote $LOG"
    exit 1
  fi
fi

if [ "${HERMES_SYNC_RESTART:-0}" = "1" ]; then
  docker restart kmuwiki-hermes >> "$LOG" 2>&1
  RESTART_RC=$?
  echo "RESTART_EXIT_CODE=$RESTART_RC" >> "$LOG"
  if [ "$RESTART_RC" -ne 0 ]; then
    echo "ENV_SYNC=FAILED_RESTART" >> "$LOG"
    echo "Wrote $LOG"
    exit 1
  fi
fi

echo "ENV_SYNC=OK" >> "$LOG"
echo "Wrote $LOG"
exit 0
