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


def run_static_checks(root: Path) -> list[VerificationResult]:
    web = root / "web"
    migrations = root / "supabase" / "migrations"
    checks = [
        VerificationResult(
            "web-proxy-auth",
            "rejectMissingAuthorization" in (web / "lib" / "ragProxy.ts").read_text(encoding="utf-8"),
            "web API proxies require a user Authorization header before RAG calls",
        ),
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
