## KMU Wiki 인제스트 워커 — NAS(DS920+) 온프레미스 허브용 경량 이미지.
#
# 설계 의도(docs/nas-hub-architecture.md 참조):
#   - torch/easyocr/transformers 제외 → 순수 파이썬 파서만(HWP=olefile 포함).
#     OCR은 KMU_OCR_BACKEND=none 으로 유예(pending_ocr), NER은 KMU_ENABLE_NER=0.
#   - 원본 ZIP은 read-only 로 마운트(워커는 읽기만). compose 참조.
#   - 비-root 실행. 컨테이너 내부에 비밀값을 굽지 않는다(env_file 주입).
#
# 빌드 컨텍스트는 이 파일이 있는 ingest/ 디렉터리.
#   docker build -t kmu-ingest-worker ./ingest

FROM python:3.12-slim

# 파이썬 런타임 위생
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 의존성만 먼저 복사 → 레이어 캐시 활용.
# requirements-worker.txt 의 torch/easyocr/transformers 는 주석 상태라 설치되지 않는다.
COPY requirements.txt requirements-worker.txt ./
RUN pip install -r requirements-worker.txt

# 워커 코드(파서·마스킹·이그레스 게이트·적재). .dockerignore 로 .env/.venv/tests 제외.
COPY kmu_ingest ./kmu_ingest

# 비-root 사용자로 실행(원본 마운트 blast radius 축소).
RUN useradd --create-home --uid 10001 worker \
    && chown -R worker:worker /app
USER worker

# NAS 기본값(compose/env_file 에서 덮어쓸 수 있음). 명시적 안전 기본.
ENV KMU_ZIP_DIR=/data/zips \
    KMU_OCR_BACKEND=none \
    KMU_ENABLE_NER=0 \
    KMU_EMBED_PROVIDER=cohere

# 기본은 1회성 배치(run). NAS 작업 스케줄러가 `docker compose run --rm` 으로 호출.
ENTRYPOINT ["python", "-m", "kmu_ingest.cli"]
CMD ["run"]
