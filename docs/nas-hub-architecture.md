# NAS(DS920+) AI 데이터 허브 구조

기존 [운영 구조](operational-architecture.md)에서 **인제스트 계층의 실행 위치**만 개발자 PC → Synology DS920+로 옮기는 변경입니다. 클라우드 계층(Supabase·Vercel·Cohere·Claude)은 바뀌지 않습니다.

## 역할 분담

```
교내(온프레미스)                          클라우드
┌─────────────────────────────┐         ┌──────────────────────┐
│ DS920+ (데이터 허브·마스킹 경계선) │  마스킹된  │ Supabase(pgvector·RLS) │
│  ├ jdh/kmuwiki/00_inbox (투입)    │  데이터만  │ Vercel(웹·/rag)        │
│  │    ↓ stager: 구조 검증 반입     │ ────────▶ │ Cohere(임베딩 1024d)   │
│  ├ jdh/kmuwiki/01_raw (불변 원본)  │         │ Claude(답변 생성)      │
│  │    (실패분 → 99_rejected 격리)  │         └──────────────────────┘
│  ├ Container Manager: ingest 워커 │
│  │   파싱·★마스킹★·이그레스게이트   │
│  └ 작업 스케줄러: 야간 스테이징→배치 │
└─────────────────────────────┘
```

### 단계형 적재 (00_inbox → 검증 → 01_raw)

새 ZIP 은 `00_inbox` 에만 투입한다. 야간 배치의 스테이저(`kmu_ingest.cli stage`)가
구조 검증(zip 폭탄·비정상 파일·부분 업로드) 후 `01_raw` 로 반입하고, 실패분은
`99_rejected/reasons.log` 와 함께 격리한다. 워커는 `01_raw` 만 `:ro` 로 읽으며,
`01_raw` 는 덮어쓰지 않는다(동명이본은 `이름-<sha8>.zip` 으로 병존). 암호화 ZIP 은
정상 입력으로 통과시킨다(`pending_password` 유예 흐름). Snapshot Replication
일일 스냅샷으로 불변성을 보강한다.

- **NAS = 데이터 중력의 중심.** 원본 ZIP(마스킹 前 원문)과 파싱·마스킹이 NAS 안에서 끝난다.
- **클라우드 = 연산.** 임베딩·답변 생성은 API 호출. NAS엔 GPU가 없어 로컬 추론을 두지 않는다.
- **마스킹 경계선이 물리적으로 NAS 안에 위치.** 고신뢰 PII(주민번호·계좌·카드·이메일)는 이그레스 게이트(`pii/egress_gate.py`)를 통과하지 못하면 전송 차단·격리된다.

## 컨테이너 구성

`ingest/` 아래 파일로 빌드/실행한다.

| 파일 | 내용 |
|---|---|
| `ingest/Dockerfile` | torch/easyocr/transformers 제외 경량 이미지(순수 파이썬 파서만, 비-root) |
| `ingest/docker-compose.yml` | read-only 원본 마운트 + 하드닝(cap_drop·read_only·no-new-privileges) |
| `ingest/.env.worker.example` | 워커 전용 최소 시크릿 템플릿(키 2개) |
| `ingest/.dockerignore` | `.env`·`.venv`·`tests`·`kmu_query` 등 제외 |

### 워커 환경변수(NAS 기본값)

| 변수 | 값 | 이유 |
|---|---|---|
| `KMU_ZIP_DIR` | `/data/zips` | 원본 공유폴더의 컨테이너 마운트 경로 |
| `KMU_OCR_BACKEND` | `none` | OCR(torch)은 4GB RAM에 부담 → GPU 박스로 유예(`pending_ocr`) |
| `KMU_ENABLE_NER` | `0` | 성명 NER(torch) 비활성 → 이미지 경량화 |
| `KMU_EMBED_PROVIDER` | `cohere` | 기본값 `fake` 방지: 실제 임베딩 강제 |
| `KMU_MAX_ZIP_ENTRY_MB` | `128` | 단일 ZIP/HWPX 항목 메모리 사용 상한 |
| `KMU_MAX_ZIP_COMPRESSION_RATIO` | `200` | 비정상 고압축 ZIP/HWPX 차단 |
| `KMU_RUN_UID/GID` | `10001` | 컨테이너 비-root 실행 계정 |

## 배포 절차

```bash
# 1) 시크릿 준비 (NAS에서, 키 2개만)
cp ingest/.env.worker.example ingest/.env.worker
#    SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY / COHERE_API_KEY 채움

# 2) 원본 공유폴더 경로를 docker-compose.yml volumes 에 지정 (:ro 유지)
#    이 환경: /volume1/jdh/kmuwiki/01_raw:/data/zips:ro  (Windows Y:\Kmuwiki\01_raw 와 동일)
#    stager 는 00_inbox(rw)·01_raw(rw)·99_rejected(rw) 를 마운트한다.
#    KMU_RUN_UID/GID 계정에 위 세 폴더 ACL을 부여한다.

# 3) 1회성 배치 실행
docker compose --env-file ingest/.env.worker -f ingest/docker-compose.yml run --rm worker run
#    백필:
docker compose --env-file ingest/.env.worker -f ingest/docker-compose.yml run --rm worker backfill

# 4) Synology 작업 스케줄러에 (3)을 야간 cron 으로 등록
```

## 보안 원칙 (NAS 특화)

기존 운영 원칙에 더해, "상시 가동 장비에 최상위 비밀·원본 PII가 상주"하는 리스크를 다음으로 상쇄한다.

- **키 최소화.** 워커는 `SUPABASE_SERVICE_ROLE_KEY` + `COHERE_API_KEY` **2개만** 둔다. 답변 생성용 키(ANTHROPIC/NOUS/GEMINI/anon)는 NAS에 두지 않는다(그건 Vercel `/rag` 전용).
- **원본 read-only.** 워커는 원본 ZIP을 읽기만 하므로 `:ro` 마운트. 컨테이너 루트 FS도 `read_only`.
- **비-root·capability 제거.** 전용 NAS UID/GID로 실행하고 Linux capability를 모두 제거한다.
- **공유폴더 암호화.** 원본 폴더는 Synology 암호화 공유폴더(AES-256) + 스냅샷 + 오프사이트 백업.
- **인바운드 차단.** QuickConnect/UPnP/포트포워딩 비활성, DSM 최신 패치, 기본 admin 비활성 + 2FA. 관리·SMB는 VPN/Tailscale 내부망에서만.
- **아웃바운드 화이트리스트.** Supabase·Cohere 도메인만 허용.
- **성명 마스킹을 켤 경우** NER 미가용 시 fail-closed(파이프라인 중단)로 운영한다. 이그레스 게이트는 성명·주소를 잡지 않으므로 NER 의존을 드러내야 한다.

## 호환성 메모

- HWP 파싱은 `olefile`(순수 파이썬)로 미리보기 스트림만 읽어 리눅스 컨테이너에서 그대로 동작한다.
- pdfplumber·python-docx·openpyxl·xlrd 모두 순수 파이썬 → GPU/네이티브 의존 없음.
- torch 계열(OCR·NER)은 이미지에서 제외되어 4GB RAM에서도 안정적이다. 8GB 증설 시 여유가 커진다.
