# NAS(DS920+) 배포 — 저장소 배치 & 3·4단계 실행 가이드

경로 기준(확인됨): 공유폴더 `jdh` = `Y:`(Windows) = `/volume1/jdh`(NAS 내부).
- 원본 ZIP: `Y:\Kmuwiki` = `/volume1/jdh/Kmuwiki`
- 저장소 배치 위치: `Y:\repo\ingest` = `/volume1/jdh/repo/ingest`
- 로그: `/volume1/jdh/logs`

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
- [ ] 볼륨 마운트 `/volume1/jdh/Kmuwiki:/data/zips:ro` 가 실제 원본과 매칭
- [ ] 첫 `run` 성공 → Supabase 반영 확인
- [ ] 스케줄 등록 후 다음 날 로그 정상
- [ ] DSM 인바운드 차단(QuickConnect/UPnP off), 아웃바운드 Supabase·Cohere 만 허용
