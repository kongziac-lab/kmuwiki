# KMU Wiki 멀티모달 v2

## 모델 구성

멀티모달 v2는 한 모델이 아니라 역할을 분리한 검색 파이프라인이다.

| 단계 | 고정 모델/구성 | 역할 |
|---|---|---|
| 문서 구조 복원 | PaddleOCR `PP-StructureV3` | 페이지 레이아웃, 표·차트 영역, Markdown 복원 |
| 한국어 OCR | `korean_PP-OCRv5_mobile_rec` | 좌표가 있는 한국어·영문 OCR |
| 검색 임베딩 | Cohere `embed-v4.0`, 1024차원 | 텍스트·표·마스킹 이미지의 공통 벡터 |
| 후보 재정렬 | Cohere `rerank-v4.0-fast` | 최대 50개 텍스트 대리표현을 재정렬 |
| 질의 시각 해석 | `gemini-3.5-flash` 또는 Claude vision | 검색된 파생 이미지가 필요할 때만 해석 |

이미지를 별도 OCR 검색으로만 다루지 않는다. 텍스트 청크, 표 Markdown, 페이지/차트의
마스킹 파생 이미지를 `search_units`라는 공통 검색 단위로 만들고 Embed v4 공간에서 검색한다.

## 보안 경계

- 원본 ZIP과 원본 이미지는 NAS/로컬 워커 밖으로 보내거나 Supabase에 저장하지 않는다.
- 잠긴 문서는 기존과 동일하게 본문을 열지 않고 `pending_password`로 남긴다.
- 시각 자료는 로컬 OCR 좌표를 기준으로 전체 PII 정책을 적용하고 픽셀을 가린다.
- 파생 이미지를 다시 OCR해 잔존 PII가 없을 때만 외부 임베딩과 비공개 Storage 적재를 허용한다.
- 로컬 NER 또는 OCR이 없으면 시각 자산을 통과시키지 않는다. 시각 유래 텍스트도 NER이 없으면
  문서를 `quarantine`으로 격리한다.
- 이미지 외부 전송은 운영자가 `security_level='일반'`으로 검토한 문서만 허용한다.
- `document_assets`와 `search_units`는 기존 `documents`의 부서·보안등급 RLS를 그대로 따른다.
- 질의 시점 이미지는 사용자 JWT로 비공개 Storage RLS를 다시 통과한 파생본만 최대 4장 로드한다.

## 데이터 모델과 롤백

- `documents`는 신원·상태·권한의 단일 기준으로 유지한다.
- `document_assets`는 마스킹 텍스트, 표 Markdown, 비공개 파생 이미지 위치만 저장한다.
- `search_units`는 text/table/image/mixed 검색 단위와 1024차원 벡터를 저장한다.
- `replace_document_index_v2`는 한 문서의 자산·검색 단위·상태를 한 트랜잭션으로 교체한다.
- 초기 재구축은 `KMU_WRITE_LEGACY_INDEX=0`으로 실행해 기존 v1/v3 `doc_chunks`를 건드리지 않는다.
  따라서 구축 중에는 기존 검색을 유지할 수 있고, 전환 실패 시 RPC와 임베딩 모델을 함께 v1/v3로
  되돌릴 수 있다.

2026-07-15 현재 원격 Supabase에는 마이그레이션 `0012`와 질의 한도를 보강한 `0013`이
적용되어 있다. 현황은
`documents: v1=78, v2=0`, 기존 `doc_chunks=163`이며 모델은
`embed-multilingual-v3.0/v3`이다. 이 작업 PC에는 전체 원본 ZIP이 연결되어 있지 않아 실제
재인덱싱은 NAS 원본을 볼 수 있는 컴퓨터에서 이어서 실행한다.

## NAS 연결 컴퓨터에서 재구축

```sh
git pull --ff-only origin main
cd ingest

cp .env.visual-worker.example .env.visual-worker
# .env.visual-worker에 실제 NAS 01_raw 경로와 비밀값을 입력한다.

uv venv --python 3.12 .venv-visual
. .venv-visual/bin/activate
uv pip sync requirements-visual.txt

set -a
. ./.env.visual-worker
set +a

python -m kmu_ingest.cli v2-status
python -m kmu_ingest.cli reindex-v2 --path "$KMU_ZIP_DIR"
python -m kmu_ingest.cli v2-status
python -m kmu_ingest.cli cutover-check \
  --expected-source-archives 22 \
  --minimum-total-documents 78 \
  --minimum-v2-documents 71
```

첫 실행에는 PP-StructureV3, PP-OCRv5, 한국어 NER 모델 다운로드 시간이 든다. 원본 경로는
읽기 전용 마운트를 권장한다. `reindex-v2`는 DB에 등록된 원본 ZIP 22개를 지정한 루트에서
먼저 확인하며 하나라도 없거나 상대 경로가 루트를 벗어나면 처리 전에 종료한다. 재구축 종료 후
다음 조건을 확인한다.

- `documents.v2`가 재처리 가능한 문서 수와 일치한다.
- `search_units.total > 0`이며 text/table/mixed 분포가 출력된다.
- `assets.pending_review`, `pending_ocr`, `blocked`를 운영자가 확인한다.
- 기존 `legacy_models`가 `embed-multilingual-v3.0/v3`로 유지된다.
- `cutover-check`가 종료 코드 0과 `ready: true`를 반환한다. 시각 자산의 `pending_review`,
  `pending_ocr`, `blocked`는 원본 유출 대신 안전한 텍스트 대체 표현을 사용한다는 경고이며,
  모델 혼합·미마스킹 ready 자산·부분 재색인은 전환 실패로 판정한다. 보존된 v1
  `doc_chunks`의 문서 ID도 v2 문서 ID와 대조하므로 단순히 총 문서 수만 맞춘 교체는 통과하지 않는다.
- 검색 품질과 권한 테스트가 통과한 뒤에만 RAG 환경을 v2로 전환한다.

```sh
KMU_INDEX_VERSION=v2
KMU_EMBED_PROVIDER=cohere
KMU_EMBED_MODEL=embed-v4.0
KMU_EMBED_VERSION=v4.0-1024
KMU_EMBED_OUTPUT_DIMENSION=1024
KMU_SEARCH_RPC=hybrid_search_v2
KMU_RERANK_MODEL=rerank-v4.0-fast
```

롤백 값은 실제 보존된 v1 모델을 읽어 다음 명령으로 확인한다.

```sh
python -m kmu_ingest.cli rollback-check
```

현재 기준 롤백은 `KMU_SEARCH_RPC=hybrid_search`,
`KMU_EMBED_MODEL=embed-multilingual-v3.0`, `KMU_EMBED_VERSION=v3`를 함께 적용한다.

## 검증

```sh
PYTHONPATH=ingest python -m unittest discover -s ingest/tests
python scripts/verify_search_quality.py
cd web && npm test && npm run build
```

검색 품질 골든셋은 문서 Recall/MRR뿐 아니라 표·차트·스캔 이미지의 검색 단위 Recall/MRR도
측정한다.
