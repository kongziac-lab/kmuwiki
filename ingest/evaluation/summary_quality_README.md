# 요약 품질 평가 하네스 (스튜디오 §7)

스튜디오 요약(NotebookLM식)이 **근거에 충실하고(인용), 구조를 지키며, 핵심 출처를
빠뜨리지 않는지**를 수치로 검증하고 임계값 미달 시 게이트를 실패시킨다. 검색 품질
하네스(`search_quality.py`)와 같은 철학으로 순수 JSONL 에서 **결정론적으로** 채점한다.

## 실행
```bash
cd ingest
python -m evaluation.summary_quality                 # 리포트 + 게이트(종료코드)
python -m evaluation.summary_quality --json out.json # 기계 판독 지표
python ../scripts/verify_summary_quality.py          # CI 게이트용
```
종료코드: 게이트 통과 0 / 실패 1.

## 골든 데이터 (`golden/summary_quality_synth.jsonl`)
한 줄당 한 케이스. **전부 합성 — 실제 개인정보 저장 금지.**
```json
{"id":"...","query":"...","source_count":3,"relevant_ns":[1,2],
 "summary":"## 한눈에 보기\n... [1][2]\n## 핵심 내용\n- ... [1]\n## 주요 일정·수치\n- ...\n## 확인이 필요한 점\n- ...",
 "sources_text":"[1] ...\n[2] ..."}
```
- `source_count` : 요약에 제공된 출처 개수. `[n]` 인용이 이 범위를 벗어나면 환각 인용.
- `relevant_ns` : 요약이 반드시 반영해야 하는 핵심 출처 번호.
- `summary` : 평가 대상(고정 fixture). 운영에서 생성한 요약을 기록해 골든셋을 키운다.

## 지표 · 임계값 (summary_quality.py)
| 지표 | 의미 | 게이트 |
|---|---|---|
| citation_precision | `[n]` 중 유효 출처 비율(환각 인용 탐지) | ≥ 0.95 |
| coverage | 핵심 출처 중 인용된 비율 | ≥ 0.60 |
| structure_rate | 필수 섹션 헤더를 모두 포함한 케이스 비율 | = 1.0 |
| citation_rate | 최소 1개 인용을 단 케이스 비율 | = 1.0 |
| faithfulness (선택) | LLM-judge 주입 시만 계산 | ≥ 0.70 |

`REQUIRED_SECTIONS` 는 `rag.SUMMARY_SYSTEM_PROMPT` 의 섹션과 동기화해야 한다.

## LLM-judge(faithfulness) 확장
```python
from evaluation.summary_quality import evaluate_cases, load_cases
metrics = evaluate_cases(load_cases(path), judge=my_judge)  # my_judge(query, summary, sources_text) -> [0,1]
```
judge 를 주입하지 않으면 faithfulness 는 계산·게이트에서 제외되어 CI 결정론성이 유지된다.
운영 채점에는 답변 생성과 다른 프로바이더를 judge 로 쓰는 것을 권장한다.
```
