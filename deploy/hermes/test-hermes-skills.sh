#!/bin/sh
# Verify that Hermes API exposes the kmuwiki skill.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-skills-test.log}"
BODY="$LOG_DIR/.hermes-skills-body.$$"
HEADERS="$LOG_DIR/.hermes-skills-headers.$$"
DISCOVERY_SKILL="/opt/data/skills/kmu-wiki-search/SKILL.md"
MOUNTED_SOURCE_SKILL="/opt/data/skills/kmuwiki/kmu-wiki-search/SKILL.md"
PROFILE_DISCOVERY_SKILL="/opt/data/home/.hermes/skills/kmu-wiki-search/SKILL.md"
LEGACY_DISCOVERY_SKILL="/opt/data/home/.hermes/skills/kmuwiki/kmu-wiki-search/SKILL.md"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"

cleanup() {
  rm -f "$BODY" "$HEADERS"
}
trap cleanup EXIT

: > "$LOG"

KEY="$(awk -F= '/^API_SERVER_KEY=/ {print substr($0, index($0, "=") + 1)}' .env | tail -n 1 | tr -d '\r\n')"

sh "$SCRIPT_DIR/wait-hermes-api.sh" "$LOG_DIR/hermes-wait.log" >> "$LOG" 2>&1
WAIT_RC=$?
if [ "$WAIT_RC" -ne 0 ]; then
  echo "SKILL_CHECK=FAILED_WAIT" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- DATE -----"
  date
  echo
  echo "----- DISCOVERY PATH -----"
  docker exec kmuwiki-hermes sh -lc "ls -l '$DISCOVERY_SKILL'"
  docker exec kmuwiki-hermes sh -lc "ls -l '$MOUNTED_SOURCE_SKILL'"
  docker exec kmuwiki-hermes sh -lc "ls -l '$PROFILE_DISCOVERY_SKILL'"
  docker exec kmuwiki-hermes sh -lc "ls -l '$LEGACY_DISCOVERY_SKILL'"
  echo
  echo "----- DISCOVERY TREE -----"
  docker exec kmuwiki-hermes sh -lc "find /opt/data/skills -maxdepth 3 -name SKILL.md -print 2>/dev/null | sort | sed -n '1,160p'"
  echo
  echo "----- PROFILE DISCOVERY TREE -----"
  docker exec kmuwiki-hermes sh -lc "find /opt/data/home/.hermes/skills -maxdepth 3 -name SKILL.md -print 2>/dev/null | sort | sed -n '1,120p'"
  echo
  echo "----- KMU SKILL FRONTMATTER -----"
  docker exec kmuwiki-hermes sh -lc "sed -n '1,40p' '$DISCOVERY_SKILL' 2>/dev/null || sed -n '1,40p' '$MOUNTED_SOURCE_SKILL' 2>/dev/null || sed -n '1,40p' '$LEGACY_DISCOVERY_SKILL' 2>/dev/null"
  echo
  echo "----- HERMES RUNTIME PATHS -----"
  docker exec kmuwiki-hermes sh -lc "env | grep -E '^(HERMES_HOME|HOME|API_SERVER_HOST|API_SERVER_PORT)=' | sort"
  docker exec kmuwiki-hermes sh -lc "python -c 'from hermes_constants import get_hermes_home, get_skills_dir; print(\"HERMES_HOME_RESOLVED=\" + str(get_hermes_home())); print(\"SKILLS_DIR_RESOLVED=\" + str(get_skills_dir()))' 2>/dev/null || echo HERMES_CONSTANTS_SCAN=SKIPPED"
  echo
  echo "----- HERMES COMMANDS -----"
  docker exec kmuwiki-hermes sh -lc "command -v hermes 2>/dev/null || true"
  docker exec kmuwiki-hermes sh -lc "hermes --help 2>/dev/null | sed -n '1,80p' || true"
  echo
  echo "----- /v1/skills -----"
} >> "$LOG" 2>&1

STATUS="$(curl -sS -D "$HEADERS" -o "$BODY" -w '%{http_code}' \
  -H "Authorization: Bearer $KEY" \
  http://127.0.0.1:8642/v1/skills 2>>"$LOG")"
CURL_RC=$?

{
  cat "$HEADERS" 2>/dev/null
  cat "$BODY" 2>/dev/null
  echo
  echo "HTTP_STATUS=$STATUS"
  echo "CURL_EXIT_CODE=$CURL_RC"
} >> "$LOG" 2>&1

if [ "$CURL_RC" -ne 0 ] || [ "$STATUS" != "200" ]; then
  echo "SKILL_CHECK=FAILED_HTTP" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

if grep -q 'kmu-wiki-search' "$BODY"; then
  echo "SKILL_CHECK=FOUND" >> "$LOG"
  echo "Wrote $LOG"
  exit 0
fi

echo "SKILL_CHECK=NOT_FOUND" >> "$LOG"
echo "Wrote $LOG"
exit 1
