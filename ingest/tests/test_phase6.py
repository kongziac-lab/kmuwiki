import json
import tempfile
import unittest
from pathlib import Path

from kmu_verify.phase6 import VerificationResult, rag_proxy_auth_check, write_report


def _write_route(web: Path, rel: str, text: str) -> None:
    p = web / "app" / "api" / rel / "route.ts"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


class TestRagProxyAuthCheck(unittest.TestCase):
    def test_passes_when_every_rag_proxy_calls_auth_guard(self):
        with tempfile.TemporaryDirectory() as td:
            web = Path(td)
            _write_route(web, "chat", "resolveRagBase rejectMissingAuthorization")
            _write_route(web, "studio/summary", "resolveRagBase rejectMissingAuthorization")
            _write_route(web, "workflows", "supabase only — not a rag proxy")

            result = rag_proxy_auth_check(web)

        self.assertTrue(result.ok)
        self.assertIn("all 2 RAG proxy routes", result.detail)

    def test_fails_and_names_route_missing_auth_guard(self):
        with tempfile.TemporaryDirectory() as td:
            web = Path(td)
            _write_route(web, "chat", "resolveRagBase rejectMissingAuthorization")
            _write_route(web, "studio", "resolveRagBase // 인증 검사 누락")

            result = rag_proxy_auth_check(web)

        self.assertFalse(result.ok)
        self.assertIn("app/api/studio/route.ts", result.detail)
        self.assertNotIn("app/api/chat/route.ts", result.detail)

    def test_fails_when_no_rag_proxy_routes_exist(self):
        with tempfile.TemporaryDirectory() as td:
            web = Path(td)
            (web / "app" / "api").mkdir(parents=True)

            result = rag_proxy_auth_check(web)

        self.assertFalse(result.ok)
        self.assertIn("no RAG proxy routes", result.detail)


class TestPhase6Report(unittest.TestCase):
    def test_writes_machine_readable_report(self):
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "phase6.json"
            write_report(out, [
                VerificationResult("security", True, "pii clear"),
                VerificationResult("calendar", False, "not configured"),
            ])

            data = json.loads(out.read_text())

        self.assertFalse(data["ok"])
        self.assertEqual(data["checks"][0]["name"], "security")
        self.assertEqual(data["checks"][1]["detail"], "not configured")


if __name__ == "__main__":
    unittest.main()
