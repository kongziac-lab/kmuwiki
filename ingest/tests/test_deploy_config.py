import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class TestUnifiedVercelServicesConfig(unittest.TestCase):
    def test_root_vercel_json_defines_web_and_rag_services(self):
        config = json.loads((ROOT / "vercel.json").read_text())

        services = config["experimentalServices"]
        self.assertEqual(services["web"]["entrypoint"], "web")
        self.assertEqual(services["web"]["routePrefix"], "/")
        self.assertEqual(services["rag"]["entrypoint"], "ingest/main.py")
        self.assertEqual(services["rag"]["routePrefix"], "/rag")

    def test_web_proxy_uses_services_url_not_separate_api_project(self):
        route = (ROOT / "web/app/api/chat/route.ts").read_text()

        self.assertIn("process.env.NEXT_PUBLIC_RAG_URL", route)
        self.assertIn("new URL(req.url).origin", route)
        self.assertNotIn("kmuwiki-api.vercel.app", route)


if __name__ == "__main__":
    unittest.main()
