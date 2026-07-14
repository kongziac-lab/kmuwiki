#!/bin/sh
# KMU Wiki 인제스트 배치 — Synology DS920+ 작업 스케줄러(사용자 정의 스크립트)용.
#
# 등록: DSM > 제어판 > 작업 스케줄러 > 생성 > 예약된 작업 > 사용자 정의 스크립트
#   - 사용자: root
#   - 스케줄: 매일 야간(예: 03:00)
#   - 실행 명령: sh /volume1/jdh/repo/ingest/nas/run-ingest.sh
#
# 전제: 이 저장소가 NAS에 복제되어 있고(REPO_DIR), Container Manager(Docker) 설치됨.
# 로그는 공유폴더의 logs/ 에 날짜별로 남긴다.

set -eu

# --- 환경(설치 위치에 맞게 조정) ---
REPO_DIR="/volume1/jdh/repo"              # docker-compose.yml 이 있는 ingest/의 상위 저장소 경로
COMPOSE_FILE="$REPO_DIR/ingest/docker-compose.yml"
WORKER_ENV="$REPO_DIR/ingest/.env.worker"
LOG_DIR="/volume1/jdh/logs"
CMD="${1:-run}"                            # run(기본) 또는 backfill

# Synology의 docker 바이너리 경로(DSM7 Container Manager)
export PATH="/usr/local/bin:$PATH"

# Compose 명령 자동 감지: 이 NAS(Docker v1)는 하이픈 docker-compose, 신형은 docker compose.
if command -v docker-compose >/dev/null 2>&1; then
  DC="docker-compose"
elif docker compose version >/dev/null 2>&1; then
  DC="docker compose"
else
  echo "ERROR: docker-compose / docker compose 를 찾을 수 없음 (PATH 확인)"; exit 1
fi

mkdir -p "$LOG_DIR"
[ -f "$WORKER_ENV" ] || { echo "ERROR: $WORKER_ENV not found"; exit 1; }
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/ingest-$CMD-$TS.log"

echo "[$(date)] start: $DC run --rm worker $CMD" | tee -a "$LOG"

# 0) 스테이징: 00_inbox 검증 → 01_raw 반입(실패해도 인제스트는 계속 — 기존 원본 처리).
set +e
echo "[$(date)] stage: $DC run --rm stager" | tee -a "$LOG"
$DC --env-file "$WORKER_ENV" -f "$COMPOSE_FILE" run --rm stager >>"$LOG" 2>&1
RC_STAGE=$?
[ "$RC_STAGE" -ne 0 ] && echo "[$(date)] stage FAILED (exit=$RC_STAGE) — 계속 진행" | tee -a "$LOG"

# 1) 인제스트. --rm: 1회성 배치. 실패해도 로그·정리까지 진행하도록 errexit 해제 상태 유지.
$DC --env-file "$WORKER_ENV" -f "$COMPOSE_FILE" run --rm worker "$CMD" >>"$LOG" 2>&1
RC=$?
set -e

# 종료코드: 둘 중 나쁜 쪽(스케줄러 알림용)
if [ "$RC" -eq 0 ] && [ "$RC_STAGE" -ne 0 ]; then RC=$RC_STAGE; fi

echo "[$(date)] end: exit=$RC (stage=$RC_STAGE)" | tee -a "$LOG"

# 오래된 로그 정리(30일)
find "$LOG_DIR" -name 'ingest-*.log' -mtime +30 -delete 2>/dev/null || true

exit $RC
