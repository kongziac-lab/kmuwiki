#!/bin/sh
# Start KMU Wiki Hermes Agent on Synology DS920+.
#
# Usage on NAS:
#   cd /volume1/jdh/repo/deploy/hermes
#   sh start-hermes.sh

set -eu

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-kmuwiki_hermes}"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -f .env ]; then
  cp .env.example .env
  if command -v openssl >/dev/null 2>&1; then
    KEY="$(openssl rand -hex 32)"
    sed -i "s/^API_SERVER_KEY=.*/API_SERVER_KEY=$KEY/" .env
  fi
  echo "Created $SCRIPT_DIR/.env"
  echo "Edit .env before starting Hermes:"
  echo "  - KMUWIKI_API_BASE_URL"
  echo "  - NEXT_PUBLIC_SUPABASE_URL"
  echo "  - NEXT_PUBLIC_SUPABASE_ANON_KEY"
  echo "  - KMUWIKI_AUTH_EMAIL"
  echo "  - KMUWIKI_AUTH_PASSWORD"
  echo "  - optional KMUWIKI_AUTH_TOKEN override"
  echo "  - optional KMUWIKI_API_SECRET"
  echo "  - optional OPENROUTER_API_KEY or OPENAI_API_KEY for Hermes chat"
  exit 2
fi

# Windows edits can leave CRLF endings. A trailing CR in API_SERVER_KEY breaks
# HTTP headers as "Missing expected LF after header value".
sed -i 's/\r$//' .env 2>/dev/null || true

if grep -q '^API_SERVER_KEY=change-me' .env || grep -q '^API_SERVER_KEY=0\{32,\}$' .env; then
  echo "ERROR: set a strong API_SERVER_KEY in .env first"
  exit 2
fi

if grep -q '^KMUWIKI_AUTH_TOKEN=$' .env; then
  echo "KMUWIKI_AUTH_TOKEN is empty; the kmuwiki skill will use dedicated-account login if configured."
fi

if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  echo "ERROR: docker compose / docker-compose not found"
  exit 1
fi

if [ "${HERMES_SKIP_PULL:-0}" = "1" ]; then
  echo "Skipping image pull because HERMES_SKIP_PULL=1"
else
  $DC -f docker-compose.yml pull
fi

# Clear a stale one-off preparation container from an interrupted DSM task.
docker rm -f "${COMPOSE_PROJECT_NAME}_hermes_run" >/dev/null 2>&1 || true
PREP_TIMEOUT="${HERMES_PREP_TIMEOUT:-300}"

# Pre-seed /opt/data/.env and the local skills directory inside the actual
# Docker volume. Hermes scans HERMES_HOME/skills, so the custom skill is copied
# to /opt/data/skills/kmu-wiki-search before the gateway starts. The repository
# bind mount under /opt/data/skills/kmuwiki remains as the source of truth for
# updates and for direct smoke-test helper paths.
if command -v timeout >/dev/null 2>&1; then
  PREP_PREFIX="timeout $PREP_TIMEOUT"
else
  PREP_PREFIX=""
fi

$PREP_PREFIX $DC -f docker-compose.yml run --rm --entrypoint sh hermes -lc '
  set -eu
  mkdir -p /opt/data/logs /opt/data/sessions /opt/data/memories /opt/data/cron /opt/data/home/.hermes/skills/kmuwiki
  if [ -d /opt/data/skills/kmuwiki/kmu-wiki-search ]; then
    rm -rf /opt/data/skills/kmu-wiki-search
    cp -R /opt/data/skills/kmuwiki/kmu-wiki-search /opt/data/skills/
    rm -rf /opt/data/home/.hermes/skills/kmu-wiki-search
    cp -R /opt/data/skills/kmuwiki/kmu-wiki-search /opt/data/home/.hermes/skills/
    rm -rf /opt/data/home/.hermes/skills/kmuwiki/kmu-wiki-search
    cp -R /opt/data/skills/kmuwiki/kmu-wiki-search /opt/data/home/.hermes/skills/kmuwiki/
  fi
  umask 077
  {
    printf "API_SERVER_ENABLED=%s\n" "${API_SERVER_ENABLED:-true}"
    printf "API_SERVER_HOST=%s\n" "${API_SERVER_HOST:-0.0.0.0}"
    printf "API_SERVER_PORT=%s\n" "${API_SERVER_PORT:-8642}"
    printf "HOME=%s\n" "${HOME:-/opt/data/home}"
    printf "HERMES_HOME=%s\n" "${HERMES_HOME:-/opt/data}"
    [ -n "${API_SERVER_KEY:-}" ] && printf "API_SERVER_KEY=%s\n" "$API_SERVER_KEY"
    [ -n "${API_SERVER_CORS_ORIGINS:-}" ] && printf "API_SERVER_CORS_ORIGINS=%s\n" "$API_SERVER_CORS_ORIGINS"
    [ -n "${KMUWIKI_API_BASE_URL:-}" ] && printf "KMUWIKI_API_BASE_URL=%s\n" "$KMUWIKI_API_BASE_URL"
    [ -n "${KMUWIKI_AUTH_TOKEN:-}" ] && printf "KMUWIKI_AUTH_TOKEN=%s\n" "$KMUWIKI_AUTH_TOKEN"
    [ -n "${NEXT_PUBLIC_SUPABASE_URL:-}" ] && printf "NEXT_PUBLIC_SUPABASE_URL=%s\n" "$NEXT_PUBLIC_SUPABASE_URL"
    [ -n "${NEXT_PUBLIC_SUPABASE_ANON_KEY:-}" ] && printf "NEXT_PUBLIC_SUPABASE_ANON_KEY=%s\n" "$NEXT_PUBLIC_SUPABASE_ANON_KEY"
    [ -n "${SUPABASE_URL:-}" ] && printf "SUPABASE_URL=%s\n" "$SUPABASE_URL"
    [ -n "${SUPABASE_ANON_KEY:-}" ] && printf "SUPABASE_ANON_KEY=%s\n" "$SUPABASE_ANON_KEY"
    [ -n "${KMUWIKI_AUTH_EMAIL:-}" ] && printf "KMUWIKI_AUTH_EMAIL=%s\n" "$KMUWIKI_AUTH_EMAIL"
    [ -n "${KMUWIKI_AUTH_PASSWORD:-}" ] && printf "KMUWIKI_AUTH_PASSWORD=%s\n" "$KMUWIKI_AUTH_PASSWORD"
    [ -n "${KMUWIKI_API_SECRET:-}" ] && printf "KMUWIKI_API_SECRET=%s\n" "$KMUWIKI_API_SECRET"
    [ -n "${KMUWIKI_DEFAULT_K:-}" ] && printf "KMUWIKI_DEFAULT_K=%s\n" "$KMUWIKI_DEFAULT_K"
    [ -n "${KMUWIKI_DEFAULT_SOURCE_YEAR:-}" ] && printf "KMUWIKI_DEFAULT_SOURCE_YEAR=%s\n" "$KMUWIKI_DEFAULT_SOURCE_YEAR"
    [ -n "${KMUWIKI_DEFAULT_DEPT:-}" ] && printf "KMUWIKI_DEFAULT_DEPT=%s\n" "$KMUWIKI_DEFAULT_DEPT"
    for PROVIDER_VAR in OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY GEMINI_API_KEY GOOGLE_API_KEY XAI_API_KEY DEEPSEEK_API_KEY GROQ_API_KEY TOGETHER_API_KEY; do
      eval "PROVIDER_VALUE=\${$PROVIDER_VAR:-}"
      [ -n "$PROVIDER_VALUE" ] && printf "%s=%s\n" "$PROVIDER_VAR" "$PROVIDER_VALUE"
    done
  } > /opt/data/.env
  chmod 700 /opt/data /opt/data/logs /opt/data/sessions /opt/data/memories /opt/data/cron /opt/data/home /opt/data/home/.hermes /opt/data/home/.hermes/skills /opt/data/home/.hermes/skills/kmuwiki 2>/dev/null || true
  chmod 600 /opt/data/.env 2>/dev/null || true
  chown 10000:10000 /opt/data /opt/data/.env /opt/data/logs /opt/data/sessions /opt/data/memories /opt/data/cron /opt/data/home /opt/data/home/.hermes /opt/data/home/.hermes/skills /opt/data/home/.hermes/skills/kmuwiki 2>/dev/null || true
  chown -R 10000:10000 /opt/data/skills/kmu-wiki-search /opt/data/home/.hermes/skills/kmu-wiki-search /opt/data/home/.hermes/skills/kmuwiki/kmu-wiki-search 2>/dev/null || true
  echo "Hermes data volume prepared"
'

if [ "${HERMES_FORCE_RECREATE:-0}" = "1" ]; then
  $DC -f docker-compose.yml up -d --force-recreate
else
  $DC -f docker-compose.yml up -d
fi
$DC -f docker-compose.yml ps
