"""Phase 6 verification report helpers."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class VerificationResult:
    name: str
    ok: bool
    detail: str


def write_report(path: Path, checks: list[VerificationResult]) -> None:
    payload = {
        "ok": all(check.ok for check in checks),
        "checks": [asdict(check) for check in checks],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def rag_proxy_auth_check(web: Path) -> VerificationResult:
    """RAG 프록시 라우트 전수 검사: resolveRagBase 를 쓰는 모든 route.ts 가
    업스트림 호출 전에 rejectMissingAuthorization 을 호출해야 한다.

    헬퍼 존재 여부만 보면 새 라우트가 인증 검사를 빠뜨려도 통과하므로,
    라우트 파일 단위로 강제한다(누락 시 해당 경로를 detail 에 나열).
    """
    proxies: list[str] = []
    missing: list[str] = []
    for p in sorted((web / "app" / "api").rglob("route.ts")):
        text = p.read_text(encoding="utf-8", errors="ignore")
        if "resolveRagBase" not in text:
            continue
        rel = p.relative_to(web).as_posix()
        proxies.append(rel)
        if "rejectMissingAuthorization" not in text:
            missing.append(rel)
    ok = bool(proxies) and not missing
    detail = (
        f"all {len(proxies)} RAG proxy routes call rejectMissingAuthorization"
        if ok
        else (f"RAG proxy routes missing auth guard: {', '.join(missing)}"
              if missing else "no RAG proxy routes found under web/app/api")
    )
    return VerificationResult("web-proxy-auth", ok, detail)


def run_static_checks(root: Path) -> list[VerificationResult]:
    web = root / "web"
    migrations = root / "supabase" / "migrations"
    checks = [
        rag_proxy_auth_check(web),
        VerificationResult(
            "no-service-role-in-web",
            "SUPABASE_SERVICE_ROLE_KEY" not in "\n".join(
                p.read_text(encoding="utf-8", errors="ignore")
                for p in web.rglob("*")
                if p.is_file() and p.suffix in {".ts", ".tsx", ".js", ".json", ".md"}
            ),
            "web bundle/config source does not reference service_role env",
        ),
        VerificationResult(
            "audit-rpc-defined",
            any("create or replace function log_access" in p.read_text(encoding="utf-8", errors="ignore")
                for p in migrations.glob("*.sql")),
            "database migration defines log_access RPC for access_log writes",
        ),
        VerificationResult(
            "password-backfill-deferred",
            "file-level encryption requires manual decryptor" in (
                root / "ingest" / "kmu_ingest" / "backfill.py"
            ).read_text(encoding="utf-8"),
            "file-internal password documents are explicitly deferred to manual/internal-server flow",
        ),
    ]
    return checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="kmu_phase6")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--out", default="phase6-report.json")
    args = parser.parse_args(argv)
    checks = run_static_checks(Path(args.root))
    out = Path(args.out)
    write_report(out, checks)
    for check in checks:
        print(f"{'OK' if check.ok else 'FAIL'} {check.name}: {check.detail}")
    return 0 if all(check.ok for check in checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
