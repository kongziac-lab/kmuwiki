import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestUnifiedVercelServicesConfig(unittest.TestCase):
    def test_root_vercel_json_defines_web_and_rag_services(self):
        config = json.loads((ROOT / "vercel.json").read_text(encoding="utf-8"))

        services = config["experimentalServices"]
        self.assertEqual(services["web"]["entrypoint"], "web")
        self.assertEqual(services["web"]["routePrefix"], "/")
        self.assertEqual(services["rag"]["entrypoint"], "ingest/main.py")
        self.assertEqual(services["rag"]["routePrefix"], "/rag")

    def test_web_proxy_uses_services_url_not_separate_api_project(self):
        proxy = (ROOT / "web/lib/ragProxy.ts").read_text(encoding="utf-8")
        chat_route = (ROOT / "web/app/api/chat/route.ts").read_text(encoding="utf-8")
        search_route = (ROOT / "web/app/api/search/route.ts").read_text(encoding="utf-8")
        insights_route = (ROOT / "web/app/api/insights/route.ts").read_text(encoding="utf-8")
        hermes_route = (ROOT / "web/app/api/hermes/route.ts").read_text(encoding="utf-8")

        self.assertIn("process.env.NEXT_PUBLIC_RAG_URL", proxy)
        self.assertIn("new URL(requestUrl).origin", proxy)
        self.assertIn("resolveRagBase(req.url)", chat_route)
        self.assertIn("resolveRagBase(req.url)", search_route)
        self.assertIn("resolveRagBase(req.url)", insights_route)
        self.assertIn("resolveRagBase(req.url)", hermes_route)
        self.assertNotIn("kmuwiki-api.vercel.app",
                         proxy + chat_route + search_route + insights_route + hermes_route)


if __name__ == "__main__":
    unittest.main()
