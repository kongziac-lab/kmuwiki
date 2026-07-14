# 스튜디오 — NotebookLM급 품질 보장 설계

KMU Wiki 스튜디오(Phase 7)는 검색된 근거 문서만으로 **요약 · 마인드맵 · 슬라이드 · 인포그래픽**을
생성한다. NotebookLM과 같은 소비 경험을 목표로 하되, 공문서 특유의 제약(개인정보 마스킹,
부서·보안등급 권한, 출처 추적)을 지키면서 **품질을 재현 가능하게** 만드는 것이 이 문서의 목적이다.

관련 코드:
- 결정론적 산출물: [`ingest/kmu_query/studio.py`](../ingest/kmu_query/studio.py)
- 요약(LLM): [`ingest/kmu_query/rag.py`](../ingest/kmu_query/rag.py) `stream_summary`
- 엔드포인트: [`ingest/kmu_query/service.py`](../ingest/kmu_query/service.py) `/studio`, `/studio/summary`
- 웹: [`web/app/studio/page.tsx`](../web/app/studio/page.tsx)
- 테스트: [`ingest/tests/test_studio.py`](../ingest/tests/test_studio.py)

## 1. 무엇을 "품질"로 정의하는가

NotebookLM의 체감 품질은 네 가지에서 나온다. 각 항목을 KMU Wiki에서 어떻게 보장하는지 매핑한다.

| NotebookLM 품질 축 | KMU Wiki 보장 방법 |
|---|---|
| **근거 충실성**(자료에 있는 것만) | 요약도 RAG와 동일한 트러스트 바운더리 — `stream_summary`는 `build_context`로 만든 번호형 출처만 입력, `SUMMARY_SYSTEM_PROMPT`가 "자료에 없는 내용 추측 금지" 강제 |
| **인용의 정확성**(문장↔출처) | 요약 응답도 `[번호]`를 달고, SSE `citations` 이벤트로 번호↔문서 매핑을 함께 전송 |
| **구조적 명료함**(개요·핵심·쟁점) | 시스템 프롬프트에 고정 섹션(`## 한눈에 보기 / 핵심 내용 / 주요 일정·수치 / 확인이 필요한 점`) |
| **환각 없음** | 마인드맵·슬라이드·인포그래픽은 100% 결정론적(규칙기반) — LLM 미경유라 환각 자체가 불가능. 근거 없으면 "근거 문서 없음" 노드로 명시 |

## 2. 아키텍처 원칙 — "규칙기반 뼈대 + LLM 문구"

```
검색(hybrid + rerank) → Source[] (마스킹된 본문만)
   ├─ studio.py (결정론적)  → 마인드맵 / 슬라이드 / 인포그래픽 / 지표
   └─ rag.stream_summary (LLM) → 한눈에 보기 요약(+인용)
```

- **뼈대는 결정론적**: 문서 수·분류·기간·업무 그룹은 `insights` 집계를 재사용해 검색·인사이트와 **같은 수치**를 보장한다(화면 간 불일치 방지).
- **문구만 LLM**: 자연어 요약만 운영 LLM(멀티모달 v2 기본 `KMU_LLM_PROVIDER=gemini` → `gemini-3.5-flash`)을 경유한다.
- **마스킹 경계선 유지**: 요약도 이미 마스킹·임베딩된 Supabase 데이터만 조회하는 `rag` 서비스에서 실행되므로, 원본 개인정보는 절대 LLM으로 나가지 않는다.

## 3. 품질 보장 장치 (구현됨)

1. **출처 없으면 생성하지 않음** — `stream_summary`는 sources가 비면 LLM을 호출하지 않고 `REFUSAL` 1회만 반환. 마인드맵/인포그래픽/슬라이드는 "근거 문서 없음"을 명시.
2. **파싱 안전성** — 마인드맵 노드는 Mermaid 셰이프 문자(`() [] {}` 등)를 제거해 렌더 실패를 원천 차단(`test_sanitizes_unsafe_characters`).
3. **인젝션·XSS 안전성** — 인포그래픽 SVG는 모든 텍스트를 이스케이프(`test_escapes_text`). 문서 제목에 `<script>`가 있어도 무해화.
4. **수치 일관성** — 문서 수는 `document_id` 기준 중복 제거(`test_duplicate_document_ids_counted_once`).
5. **결정론성** — 같은 입력 → 같은 산출물. 스냅샷/골든 테스트가 가능(단위 테스트 14종 통과).

## 4. NotebookLM 격차를 좁히는 로드맵 (제안)

품질을 "보장"하려면 자동 평가가 필요하다. 마스킹 평가 하네스(`ingest/evaluation/`)와
검색 품질 게이트(`search_quality.py`) 패턴을 그대로 확장한다.

### 4.1 요약 품질 평가 하네스 ✅ 구현됨
[`ingest/evaluation/summary_quality.py`](../ingest/evaluation/summary_quality.py) — 검색 품질 하네스와
같은 철학으로 순수 JSONL 에서 **결정론적**으로 채점해 CI 게이트가 가능하다.

- 골든셋: [`ingest/evaluation/golden/summary_quality_synth.jsonl`](../ingest/evaluation/golden/summary_quality_synth.jsonl)
- 결정론적 지표(LLM 불필요):
  - **citation_precision**: 요약의 `[n]` 중 유효 출처(1..source_count)를 가리키는 비율(환각 인용 탐지). 게이트 ≥ 0.95
  - **coverage**: 핵심 출처(relevant_ns) 중 실제 인용한 비율. 게이트 ≥ 0.60
  - **structure_rate**: 지정 섹션 헤더를 모두 포함하는 케이스 비율. 게이트 = 1.0
  - **citation_rate**: 최소 1개 인용을 단 케이스 비율. 게이트 = 1.0
- 선택 지표: **faithfulness** — `evaluate_cases(cases, judge=...)` 로 LLM-judge 를 주입할 때만 계산·게이트(≥ 0.70). judge 미주입 시 CI 결정론성 유지.
- 실행:
  ```bash
  cd ingest && python -m evaluation.summary_quality            # 리포트 + 종료코드
  python scripts/verify_summary_quality.py                     # CI 게이트용
  ```
- 운영 연동: 생성된 요약을 케이스로 기록해 골든셋을 키우면 회귀를 잡는다(검색 품질 하네스와 동일 패턴).

### 4.2 오디오 개요 (NotebookLM 시그니처, 미구현)
- 대본 생성(`stream_summary` 확장) → **TTS**(외부 API) → mp3.
- 주의: 대본을 TTS로 보내기 전 **마스킹 재검증** 필수(마스킹 경계선). 1인 브리핑 오디오를 현실적 목표로.

### 4.3 마인드맵 의미 그룹핑 ✅ 구현됨
[`studio.cluster_work_items`](../ingest/kmu_query/studio.py) + `build_mindmap_mermaid(..., groups=...)`.
- **노드(업무·문서)는 항상 결정론적**, LLM은 **그룹 라벨만** 생성 → 환각 표면적을 라벨로만 국한.
- 안전장치: 존재하지 않는 `work_id`는 무시(`parse_cluster_response`), 매핑 누락 업무는 규칙기반 `task_category`로 폴백, JSON 파싱 실패·LLM 오류 시 전체 규칙기반으로 폴백, 업무 2개 미만이면 LLM 호출 생략.
- 엔드포인트: `POST /studio` 응답에 `mindmap_grouping: "semantic" | "rule"` 을 함께 반환(웹에서 배지 표시). `semantic_mindmap: false` 로 비활성 가능.

## 5. 운영 체크리스트

- [ ] `KMU_LLM_PROVIDER`와 키가 `rag` 서비스에 주입되어 요약이 동작하는지 확인.
- [ ] 요약 응답의 `[n]`이 `citations`와 일치하는지 샘플 검수.
- [ ] 슬라이드(.md)를 Marp로, 인포그래픽(.svg)을 뷰어로 실제 렌더 확인.
- [ ] (로드맵) 요약 품질 하네스를 CI 게이트로 추가.
