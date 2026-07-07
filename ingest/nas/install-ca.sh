#!/bin/sh
# NAS 시스템 CA 신뢰 저장소 갱신 + Docker 재시작.
#   원인: DSM 기본 CA 번들이 오래돼(2020) Docker Hub 정상 인증서를 검증 못 함.
#   해결: 최신 CA 번들(cacert.pem, Windows에서 Y:\로 받음)을 시스템 번들에 합침.
#
# 실행(붙여넣기 말고 직접 타이핑 권장):
#   sudo sh /volume1/jdh/repo/ingest/nas/install-ca.sh
#
# 멱등적: 여러 번 실행해도 원본(.orig)을 기준으로 다시 합치므로 중복 누적 없음.

set -eu

SRC="${1:-/volume1/jdh/cacert.pem}"
SYS="/etc/ssl/certs/ca-certificates.crt"

if [ ! -f "$SRC" ]; then
  echo "ERROR: 최신 CA 번들이 없습니다: $SRC"
  echo "  Windows 브라우저로 https://curl.se/ca/cacert.pem 를 Y:\\cacert.pem 로 저장하세요."
  exit 1
fi

if [ ! -f "$SYS" ]; then
  echo "ERROR: 시스템 CA 번들 경로가 다릅니다: $SYS 없음"
  echo "  'ls -l /etc/ssl/certs/' 결과를 확인해 경로를 알려주세요."
  exit 1
fi

# 최초 1회 원본 백업(깨끗한 기준점).
if [ ! -f "$SYS.orig" ]; then
  cp "$SYS" "$SYS.orig"
  echo "원본 백업 생성: $SYS.orig"
fi

# 원본 + 최신 번들 → 시스템 번들 (append 아님, 재생성이라 중복 누적 없음).
cat "$SYS.orig" "$SRC" > "$SYS"
echo "CA 번들 갱신 완료: 총 $(grep -c 'BEGIN CERTIFICATE' "$SYS") 개 인증서"

# Docker 재시작(패키지명 Docker).
if command -v synopkg >/dev/null 2>&1; then
  echo "Docker 재시작 중..."
  synopkg restart Docker >/dev/null 2>&1 \
    && echo "Docker 재시작 완료" \
    || echo "자동 재시작 실패 — DSM 패키지 센터에서 Docker 중지→실행 하세요."
else
  echo "DSM 패키지 센터에서 Docker 를 중지→실행 하세요."
fi

echo "완료. 이제 다시 빌드:"
echo "  cd /volume1/jdh/repo/ingest && sudo docker-compose build"
