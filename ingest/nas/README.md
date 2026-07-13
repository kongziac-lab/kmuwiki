# NAS(DS920+) 배포 — 저장소 배치 & 3·4단계 실행 가이드

경로 기준(확인됨): 공유폴더 `jdh` = `Y:`(Windows) = `/volume1/jdh`(NAS 내부).
- 문서 루트: `Y:\Kmuwiki` = `/volume1/jdh/kmuwiki` (아래 단계형 구조)
- 저장소 배치 위치: `Y:\repo\ingest` = `/volume1/jdh/repo/ingest`
- 로그: `/volume1/jdh/logs`

## 단계형 적재 폴더 (00_inbox → 01_raw)

```
Y:\Kmuwiki\
├─ 00_inbox\      ← ★새 ZIP 은 여기에만 넣는다 (연도 하위폴더 유지 가능)
├─ 01_raw\        ← 불변 원본 — 스테이저만 반입, 워커가 :ro 로 읽음. 직접 수정 금지
└─ 99_rejected\   ← 검증 실패 격리 + reasons.log (사유: not-zip/empty/invalid-zip/
                     too-large/too-many-entries/uncompressed-too-large/name-collision)
```

- 야간 배치가 **스테이징(검증 반입) → 인제스트** 순으로 돈다. 수동 실행:
  `docker-compose run --rm stager`
- 5분 이내에 만들어진 파일은 "복사 중"으로 보고 건너뛴다(다음 실행 때 반입).
- 같은 이름·같은 내용이 이미 01_raw 에 있으면 투입본을 지운다(중복). 같은 이름·다른
  내용이면 `이름-<sha8>.zip` 으로 나란히 보관한다 — 01_raw 는 절대 덮어쓰지 않는다.
- **스냅샷 권장**: DSM 패키지 **Snapshot Replication** 설치 → 공유폴더 `jdh` 에
  일일 스냅샷 + 30일 보관. 랜섬웨어/실수 삭제 시 01_raw 복원용.

## 저장소 배치 (권장: SMB 복사)

`Y:` 가 이미 매핑돼 있으므로 개발 PC에서 `ingest/` 폴더만 복사하면 된다.
워커 이미지는 `ingest/` 만 있으면 되고, 이 방식은 `.env.worker`(gitignore 대상)도 자동으로 함께 올라간다.

PowerShell에서:
```powershell
robocopy "C:\Users\Owner\Documents\github\kmuwiki\ingest" "Y:\repo\ingest" /E /XD .venv __pycache__ /XF *.pyc
```
- `/XD .venv __pycache__` : 가상환경·캐시 제외(리눅스에서 불필요)
- 결과: `Y:\repo\ingest\...` == `/volume1/jdh/repo/ingest\...`
- 코드 수정 후 재배포도 같은 명령으로 덮어쓰기(변경분만 복사).

> 대안(git): NAS에 git이 설치돼 있다면 `git clone https://github.com/kongziac-lab/kmuwiki.git /volume1/jdh/repo`
> 로 받아도 된다. 단 `.env.worker` 는 gitignore 라 **별도 복사 필요**하고, 기본 DSM엔 git CLI가 없어
> Git Server 패키지/entware 설치가 선행돼야 한다. 단순함은 위의 SMB 복사가 낫다.

## 3단계 — 빌드 & 1회 실행 (SSH 또는 Container Manager)
```sh
cd /volume1/jdh/repo
docker compose -f ingest/docker-compose.yml build
docker compose -f ingest/docker-compose.yml run --rm worker run
```
- 성공 판정: 콘솔에 상태 분포 출력, Supabase `documents`/청크 증가.
- 소량 검증을 원하면 원본 폴더에 일부 ZIP만 두고 시작.

## 4단계 — 야간 스케줄 등록
DSM > 제어판 > **작업 스케줄러** > 생성 > 예약된 작업 > **사용자 정의 스크립트**
- 사용자: `root`
- 스케줄: 매일 03:00 (권장)
- 실행 명령:
  ```sh
  sh /volume1/jdh/repo/ingest/nas/run-ingest.sh
  ```
- 백필까지 자동화하려면 별도 작업으로:
  ```sh
  sh /volume1/jdh/repo/ingest/nas/run-ingest.sh backfill
  ```
로그: `/volume1/jdh/logs/ingest-<cmd>-<타임스탬프>.log` (30일 자동 정리)

## 점검 체크리스트
- [ ] 경로 확인: `ls -d /volume*/jdh` 가 `/volume1/jdh` 출력
- [ ] `ingest/` 복사됨 + `ingest/.env.worker` 존재(3키 채워짐), 권한 600 권장
- [ ] 폴더 구조: `/volume1/jdh/kmuwiki/{00_inbox,01_raw,99_rejected}` 존재
- [ ] 볼륨 마운트 `/volume1/jdh/kmuwiki/01_raw:/data/zips:ro` 가 실제 원본과 매칭
- [ ] 코드 변경 반영 시 이미지 재빌드(`docker-compose build`) — stage 커맨드 포함
- [ ] 첫 `run` 성공 → Supabase 반영 확인
- [ ] 스케줄 등록 후 다음 날 로그 정상(스테이징 → 인제스트 순)
- [ ] Snapshot Replication 스냅샷 스케줄 활성(권장)
- [ ] DSM 인바운드 차단(QuickConnect/UPnP off), 아웃바운드 Supabase·Cohere 만 허용
