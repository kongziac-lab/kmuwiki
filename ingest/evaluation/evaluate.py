"""마스킹 재현율/정밀도 평가 (§7.A).

두 가지를 측정한다:
  - recall(안전): must_mask(가려야 할 PII) 가 마스킹 출력에서 사라졌는가.
                  남아 있으면 LEAK(유출) — 가장 위험.
  - keep(활용성): must_keep(가리면 안 되는 값: 문서번호·날짜·기관명·금액) 가 보존됐는가.
                  사라졌으면 OVER-MASK(과다 마스킹) — 검색·메타데이터 훼손.

임계값 미달 시 비정상 종료(exit 1) → CI 게이트로 쓸 수 있다.

⚠️ golden 데이터는 전부 '합성(가짜)'이어야 한다. 실제 개인정보 저장 금지.
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from collections import defaultdict
from dataclasses import dataclass, field

# 유형별 재현율 임계값. 정형 식별자는 1.0(완전), 비정형은 다소 완화.
DEFAULT_RECALL_THRESHOLDS = {
    "주민등록번호": 1.0,
    "전화번호": 1.0,
    "이메일": 1.0,
    "카드번호": 1.0,
    "계좌번호": 0.90,
    "성명": 0.95,
    "주소": 0.90,
}
DEFAULT_KEEP_THRESHOLD = 0.98


@dataclass
class TypeStat:
    total: int = 0
    masked: int = 0
    leaks: list[dict] = field(default_factory=list)

    @property
    def recall(self) -> float:
        return self.masked / self.total if self.total else 1.0


@dataclass
class Report:
    by_type: dict[str, TypeStat]
    keep_total: int
    keep_ok: int
    overmasked: list[dict]
    ner_enabled: bool
    recall_thresholds: dict[str, float]
    keep_threshold: float
    policy_labels: frozenset[str] | None = None

    @property
    def keep_ratio(self) -> float:
        return self.keep_ok / self.keep_total if self.keep_total else 1.0

    @property
    def passed(self) -> bool:
        for t, st in self.by_type.items():
            if st.recall < self.recall_thresholds.get(t, 0.95):
                return False
        return self.keep_ratio >= self.keep_threshold


def load_golden(paths: list[str]) -> list[dict]:
    items: list[dict] = []
    for path in paths:
        for fp in sorted(glob.glob(path)):
            with open(fp, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        items.append(json.loads(line))
    return items


def run_eval(
    items: list[dict],
    masker,
    recall_thresholds: dict[str, float] | None = None,
    keep_threshold: float = DEFAULT_KEEP_THRESHOLD,
) -> Report:
    rt = recall_thresholds or DEFAULT_RECALL_THRESHOLDS
    by_type: dict[str, TypeStat] = defaultdict(TypeStat)
    keep_total = keep_ok = 0
    overmasked: list[dict] = []

    for it in items:
        masked = masker.mask(it["text"]).text
        for pii in it.get("must_mask", []):
            st = by_type[pii["type"]]
            st.total += 1
            if pii["value"] in masked:
                st.leaks.append({"id": it["id"], "value": pii["value"]})
            else:
                st.masked += 1
        for keep in it.get("must_keep", []):
            keep_total += 1
            if keep in masked:
                keep_ok += 1
            else:
                overmasked.append({"id": it["id"], "value": keep})

    ner_enabled = getattr(masker, "_ner", None) is not None
    policy = getattr(masker, "policy", None)
    return Report(dict(by_type), keep_total, keep_ok, overmasked,
                  ner_enabled, rt, keep_threshold,
                  policy_labels=getattr(policy, "labels", None))


def format_report(rep: Report) -> str:
    lines = []
    if rep.policy_labels is not None:
        lines.append("마스킹 정책: " + ", ".join(sorted(rep.policy_labels)))
    lines.append(f"NER: {'활성' if rep.ner_enabled else '비활성(정책상 성명·주소 보존)'}")
    lines.append("")
    lines.append(f"{'유형':<12}{'총':>5}{'마스킹':>8}{'recall':>9}{'임계':>7}  판정")
    lines.append("-" * 52)
    for t in sorted(rep.by_type):
        st = rep.by_type[t]
        thr = rep.recall_thresholds.get(t, 0.95)
        ok = "PASS" if st.recall >= thr else "FAIL ✗"
        lines.append(f"{t:<12}{st.total:>5}{st.masked:>8}{st.recall:>9.2f}{thr:>7.2f}  {ok}")
    lines.append("-" * 52)
    keep_ok = rep.keep_ratio >= rep.keep_threshold
    lines.append(f"{'보존(keep)':<12}{rep.keep_total:>5}{rep.keep_ok:>8}{rep.keep_ratio:>9.2f}"
                 f"{rep.keep_threshold:>7.2f}  {'PASS' if keep_ok else 'FAIL ✗'}")

    leaks = [lk for st in rep.by_type.values() for lk in st.leaks]
    if leaks:
        lines.append("\n[LEAK] 마스킹 안 된 PII (유출 위험):")
        for lk in leaks:
            lines.append(f"  - {lk['id']}: {lk['value']!r}")
    if rep.overmasked:
        lines.append("\n[OVER-MASK] 잘못 가려진 비-PII (활용성 훼손):")
        for om in rep.overmasked:
            lines.append(f"  - {om['id']}: {om['value']!r}")

    lines.append("\n=== " + ("GATE PASS ✅" if rep.passed else "GATE FAIL ❌") + " ===")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="evaluate", description="마스킹 품질 평가 (§7.A)")
    p.add_argument("--golden", nargs="*",
                   default=["evaluation/golden/*.jsonl"], help="golden glob(들)")
    p.add_argument("--json", help="결과 JSON 출력 경로")
    p.add_argument("--no-ner", action="store_true", help="NER 끄고 정규식만 평가")
    args = p.parse_args(argv)

    from kmu_ingest.config import load_settings
    from kmu_ingest.pii.masker import Masker

    s = load_settings()
    masker = Masker(enable_ner=(s.enable_ner and not args.no_ner),
                    ner_model=s.ner_model)

    items = load_golden(args.golden)
    if not items:
        print("golden 항목이 없습니다.", file=sys.stderr)
        return 2

    rep = run_eval(items, masker)
    print(format_report(rep))

    if args.json:
        out = {
            "ner_enabled": rep.ner_enabled,
            "keep_ratio": rep.keep_ratio,
            "passed": rep.passed,
            "by_type": {t: {"total": st.total, "masked": st.masked,
                            "recall": st.recall, "leaks": st.leaks}
                        for t, st in rep.by_type.items()},
            "overmasked": rep.overmasked,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, indent=2)

    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
