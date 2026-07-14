#!/bin/sh
# Optional end-to-end Hermes chat-completions smoke test.
#
# This can call an upstream LLM depending on the Hermes profile, so it is not
# run by verify-hermes.sh unless HERMES_RUN_CHAT_TEST=1 is set.

set +e

export HOME="${HOME:-/root}"
export PATH="/usr/local/bin:/usr/local/sbin:/usr/syno/bin:/usr/syno/sbin:/usr/bin:/usr/sbin:/bin:/sbin:$PATH"

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
cd "$SCRIPT_DIR" || exit 1

LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"
mkdir -p "$LOG_DIR"
LOG="${1:-$LOG_DIR/hermes-chat-test.log}"
BODY="$LOG_DIR/.hermes-chat-body.$$"
HEADERS="$LOG_DIR/.hermes-chat-headers.$$"
PAYLOAD="$LOG_DIR/.hermes-chat-payload.$$"
DEPLOY_VERSION="$(cat "$SCRIPT_DIR/VERSION" 2>/dev/null || echo unknown)"
CHAT_TIMEOUT="${HERMES_CHAT_TIMEOUT:-300}"

cleanup() {
  rm -f "$BODY" "$HEADERS" "$PAYLOAD"
}
trap cleanup EXIT

: > "$LOG"

KEY="$(awk -F= '/^API_SERVER_KEY=/ {print substr($0, index($0, "=") + 1)}' .env | tail -n 1 | tr -d '\r\n')"

sh "$SCRIPT_DIR/wait-hermes-api.sh" "$LOG_DIR/hermes-wait.log" >> "$LOG" 2>&1
WAIT_RC=$?
if [ "$WAIT_RC" -ne 0 ]; then
  echo "CHAT_CHECK=FAILED_WAIT" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

cat > "$PAYLOAD" <<'JSON'
{
  "model": "hermes-agent",
  "stream": false,
  "messages": [
    {
      "role": "user",
      "content": "Use the kmu-wiki-search skill to search KMU Wiki for exchange student promotion documents from source_year 2026. Return a short answer with one document_id, doc_no, or cited source from the returned kmuwiki API evidence. If the skill cannot be used, say so explicitly."
    }
  ]
}
JSON

{
  echo "DEPLOY_VERSION=$DEPLOY_VERSION"
  echo
  echo "----- DATE -----"
  date
  echo
  echo "----- CHAT TEST -----"
  echo "endpoint=/v1/chat/completions"
  echo "model=hermes-agent"
  echo "timeout_seconds=$CHAT_TIMEOUT"
  echo
  echo "----- PROVIDER ENV PRESENCE -----"
  docker exec kmuwiki-hermes sh -lc "python - <<'PY'
import os
keys = ['OPENROUTER_API_KEY','OPENAI_API_KEY','ANTHROPIC_API_KEY','GEMINI_API_KEY','GOOGLE_API_KEY','XAI_API_KEY','DEEPSEEK_API_KEY','GROQ_API_KEY','TOGETHER_API_KEY']
for key in keys:
    value = os.environ.get(key, '')
    print(f'ENV_{key}=' + ('SET' if value else 'EMPTY'))
for path in ['/opt/data/.env', '/opt/data/home/.hermes/.env']:
    print('DOTENV_PATH=' + path)
    try:
        text = open(path, encoding='utf-8', errors='ignore').read().splitlines()
    except OSError:
        text = []
    for key in keys:
        found = any(line.startswith(key + '=') and line.split('=', 1)[1].strip() for line in text)
        print(f'DOTENV_{key}=' + ('SET' if found else 'EMPTY'))
for path in ['/opt/data/config.yaml', '/opt/data/home/.hermes/config.yaml']:
    print('CONFIG_PATH=' + path)
    try:
        lines = open(path, encoding='utf-8', errors='ignore').read().splitlines()
    except OSError:
        lines = []
    for needle in ['provider:', 'default:', 'base_url:', 'api_mode:']:
        value = next((line.strip() for line in lines if line.strip().startswith(needle)), '')
        print('CONFIG_' + needle.rstrip(':').upper() + '=' + (value or 'EMPTY'))
PY"
} >> "$LOG" 2>&1

STATUS="$(curl -sS -D "$HEADERS" -o "$BODY" -w '%{http_code}' \
  --max-time "$CHAT_TIMEOUT" \
  -H "Authorization: Bearer $KEY" \
  -H "Content-Type: application/json" \
  --data-binary "@$PAYLOAD" \
  http://127.0.0.1:8642/v1/chat/completions 2>>"$LOG")"
CURL_RC=$?

{
  cat "$HEADERS" 2>/dev/null
  cat "$BODY" 2>/dev/null
  echo
  echo "HTTP_STATUS=$STATUS"
  echo "CURL_EXIT_CODE=$CURL_RC"
} >> "$LOG" 2>&1

if [ "$CURL_RC" -ne 0 ] || [ "$STATUS" != "200" ]; then
  if grep -q 'No inference provider configured' "$BODY"; then
    echo "CHAT_CHECK=FAILED_NO_INFERENCE_PROVIDER" >> "$LOG"
    echo "Wrote $LOG"
    exit 1
  fi
  echo "CHAT_CHECK=FAILED_HTTP" >> "$LOG"
  echo "Wrote $LOG"
  exit 1
fi

if grep -q '"choices"' "$BODY" && grep -Eiq 'kmu-wiki-search|document_id|doc_no|citation|source|evidence' "$BODY"; then
  echo "CHAT_CHECK=FOUND_EVIDENCE_RESPONSE" >> "$LOG"
  echo "Wrote $LOG"
  exit 0
fi

echo "CHAT_CHECK=NO_EVIDENCE_MARKER" >> "$LOG"
echo "Wrote $LOG"
exit 1
