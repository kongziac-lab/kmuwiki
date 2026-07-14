# KMU Wiki — 인제스트 워커 (Phase 1)

전자결재 ZIP → 잠금탐지 → 텍스트/레이아웃/OCR → 마스킹 → **이그레스 게이트** →
Embed v4 멀티모달 인덱스 → Supabase.
마스터 플랜의 불변식을 코드로 강제한다: [../plans/kmu-wiki-master-plan.md](../plans/kmu-wiki-master-plan.md)

## 핵심 불변식 (코드 위치)
| 불변식 | 강제 위치 |
|---|---|
| 1·7 마스킹 후에만 외부 전송, 게이트로 검증 | `pii/egress_gate.py`, `pipeline.py` 6단계 |
| 2 잠긴 파일 본문 미오픈 | `lockdetect.py`, `watcher.py`, `pipeline.py` 2단계 |
| 3·6 차원 1024 고정·모델 핀 | `config.EMBED_DIM`, `embedding.py`, `search_units.embed_model` |
| 4 해시 멱등성 | `hashing.py`, `pipeline.py` 1단계 |
| 5·8 RLS·deny-by-default | `supabase/migrations/0001_init.sql`, `metadata.py` |

## 빠른 시작 (DB 없이 검증)
```bash
cd ingest
python -m kmu_ingest.cli run --path ./zips --dry-run
```
`--dry-run` 은 의존성 없이(기본 fake 임베딩) 파이프라인을 끝까지 돌려 상태 분포를 출력한다.

## 운영 실행
```bash
pip install -r requirements-worker.txt
cp .env.example .env   # 값 채우기 (SUPABASE_*, KMU_EMBED_PROVIDER=bge-m3 등)
python -m kmu_ingest.cli run
```

`requirements.txt`는 Vercel RAG 서비스, `requirements-api.txt`는 로컬 ASGI 서버,
`requirements-worker.txt`는 경량 NAS 워커, `requirements-visual.txt`는
PP-StructureV3·PP-OCRv5·NER를 포함한 Mac/GPU 시각 워커용 잠금 파일이다. 파일들은
`requirements*.in`에서 해시와 함께 재현 가능하게 생성한다.

멀티모달 v2 전체 재구축은 [운영 문서](../docs/multimodal-v2.md)의 섀도 인덱스 절차를 따른다.
재구축 명령은 DB에 등록된 원본 ZIP 전부를 먼저 확인하며, 운영 전환은 `cutover-check`가
데이터 수·모델 핀·검색 단위·시각 마스킹·롤백 인덱스를 모두 통과한 뒤에만 수행한다.

원본 ZIP은 `./zips` 한 폴더에 계속 넣어도 된다. 워커는 하위 폴더까지 재귀적으로
스캔하고, ZIP의 상대 경로를 `zip_archives.source_path`에 저장한다. 지식베이스 정리는
파일 폴더가 아니라 `documents.task_category`, `classification_confidence`,
`review_required`, 임베딩 검색 결과로 수행한다.

로컬 관리자 웹에서 실행할 때도 기본값은 같은 `KMU_ZIP_DIR`을 사용한다. 관리자 화면의
`로컬 ZIP 폴더` 입력칸에서 실행할 폴더를 매번 절대경로로 바꿀 수도 있다. 다른 컴퓨터에서
Windows 공유 드라이브나 NAS를 쓰는 경우 해당 컴퓨터의 환경변수를 기본값으로 두거나,
웹 입력칸에 해당 경로를 넣어 실행한다.

다른 내부망 컴퓨터에서 관리자 화면을 열 수는 있지만, 로컬 인제스트 실행 API는 요청의
`Host`만으로 내부 사용자를 신뢰하지 않는다. 운영 모드에서 신뢰 가능한 역방향 프록시가
클라이언트 IP를 설정하는 경우에만 아래 값을 사용한다.

```powershell
$env:KMU_ENABLE_LOCAL_INGEST="1"
$env:KMU_TRUST_PROXY_HEADERS="1"
$env:KMU_LOCAL_INGEST_ALLOWED_DIRS="\\NAS\KMU-Wiki-Zips"
```

프록시는 외부에서 전달된 `x-forwarded-for`를 제거한 뒤 실제 클라이언트 주소를 새로 넣어야
한다. 개발 서버의 로컬 인제스트는 loopback 접속만 허용한다.

```bash
# macOS
KMU_ZIP_DIR=/Users/kdh/Documents/KMU-Wiki-Zips

# Windows PowerShell 예시
$env:KMU_ZIP_DIR="Z:\KMU-Wiki-Zips"
$env:KMU_ZIP_DIR="\\NAS\KMU-Wiki-Zips"
```

## 백필
```bash
python -m kmu_ingest.cli backfill --dry-run
python -m kmu_ingest.cli backfill --zip-dir ./zips --passwords ./passwords.txt --ocr-backend paddle
```
`pending_ocr`는 보안된 로컬 OCR 서버에서 처리한다. 암호가 있는 PDF/HWP 등 파일 내부 암호 문서는
완전한 내부 로컬 서버와 수동 운영 절차가 구축되기 전까지 의도적으로 유예하며, 수동 큐에 남긴다.

## 테스트
```bash
cd ingest
python -m unittest discover -s tests -v
python -m kmu_verify.phase6 --out ../phase6-report.json
```

## RAG 답변 모델
임베딩은 계속 Cohere multilingual 1024차원 계열을 사용하고, 아래 설정은 답변 생성 LLM에만 적용한다.
마스킹된 검색 출처만 provider로 전송된다.

```bash
# 기본: ANTHROPIC_API_KEY가 있으면 Claude, 없으면 Cohere chat
KMU_LLM_PROVIDER=

# Cohere 명시
KMU_LLM_PROVIDER=cohere
KMU_COHERE_CHAT_MODEL=command-r-plus-08-2024

# Nous Portal(OpenAI 호환 aggregator) — 모델 탐색/A-B 테스트용
KMU_LLM_PROVIDER=nous
NOUS_API_KEY=...
KMU_NOUS_MODEL=Hermes-4-70B

# Google Gemini 직접 연결 — Gemini 운영 확정 시 권장
KMU_LLM_PROVIDER=gemini
GOOGLE_API_KEY=...
KMU_GEMINI_MODEL=gemini-3.5-flash

# Vertex AI를 쓰면 프로젝트와 리전을 지정한다. 기본 리전은 서울.
GOOGLE_GENAI_USE_VERTEXAI=1
GOOGLE_CLOUD_PROJECT=your-project
GOOGLE_CLOUD_LOCATION=asia-northeast3
```

`nous`와 `gemini`는 silent switch 방지를 위해 `KMU_LLM_PROVIDER`로 명시했을 때만 켜진다.

## 단계별 상태(state machine)
`pending_password`(잠김) · `pending_ocr`(스캔본, OCR 대기) · `quarantine`(PII 잔존 차단) ·
`processed` · `failed`. 2차(로컬 GPU 서버) 백필은 `pending_password`/`pending_ocr` 만 골라 처리.

업무 분류 확신도가 낮은 문서는 `task_category='미분류'`, `review_required=true`로 남긴다.
운영자는 나중에 해당 메타데이터만 수정하면 원본 ZIP을 다시 옮기지 않아도 된다.

## 마스킹 정책 (§7.A)
**무엇을 PII로 보고 가릴지**는 단일 정책(`pii/policy.py`)이 정한다. 마스커와 이그레스
게이트가 같은 정책을 공유한다(어긋나면 전 문서 격리되므로).

- **내부결재문 기본 정책**(`KMU_MASK_LABELS` 빈 값):
  - 🔒 마스킹: **주민등록번호·카드·계좌·여권/면허·이메일** (유출 위험 식별자)
  - 👤 보존: **성명·전화번호·주소** — 직원이 업무상 등장하는 식별 메타데이터(업무흐름도·담당자 조회에 필요)
- **재정의**: `KMU_MASK_LABELS=주민등록번호,계좌번호,이메일,성명,주소` (민원·학생 등 제3자 정보 문서) 또는 `=all`.

레이어:
- **L1 정규식**(`pii/regex_rules.py`): 정책에 포함된 라벨만 치환. 계좌는 은행/계좌 키워드 인접 시에만(날짜·문서번호 오탐 방지).
- **L2 NER**(`pii/ner.py`): 정책이 성명/주소를 켤 때만 동작(HuggingFace 한국어 NER, lazy). 기본 정책은 비활성 → 모델 불필요.
- **L3 이그레스 게이트**(`pii/egress_gate.py`): 전송 직전, **정책과 동일한 라벨만** 재스캔→차단.

## 샘플 ZIP 확정 후 채울 곳
- `metadata.py` — 전자결재 index/헤더 파서, 부서·열람권·보안등급 매핑(§7.B)
- `hwp_support.py`(미생성) — HWP/HWPX 텍스트 추출
