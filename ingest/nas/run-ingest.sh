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
TS="$(date +%Y%m%d-%H%M%S)"
LOG="$LOG_DIR/ingest-$CMD-$TS.log"

echo "[$(date)] start: $DC run --rm worker $CMD" | tee -a "$LOG"

# --rm: 1회성 배치. 실패해도 로그를 남기고 정리까지 진행하도록 errexit 일시 해제.
set +e
$DC -f "$COMPOSE_FILE" run --rm worker "$CMD" >>"$LOG" 2>&1
RC=$?
set -e

echo "[$(date)] end: exit=$RC" | tee -a "$LOG"

# 오래된 로그 정리(30일)
find "$LOG_DIR" -name 'ingest-*.log' -mtime +30 -delete 2>/dev/null || true

exit $RC
