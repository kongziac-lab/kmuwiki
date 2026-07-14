import importlib.util
import os
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[2]
HERMES = ROOT / "deploy" / "hermes"
SKILL = HERMES / "skills" / "kmuwiki" / "kmu-wiki-search"
HELPER = SKILL / "scripts" / "kmuwiki_api.py"


def load_helper():
    spec = importlib.util.spec_from_file_location("kmuwiki_api", HELPER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class TestHermesDeploy(unittest.TestCase):
    def test_compose_runs_official_hermes_container_with_read_only_skill_mount(self):
        compose = (HERMES / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertRegex(
            compose,
            r"nousresearch/hermes-agent:v[0-9.]+@sha256:[0-9a-f]{64}",
        )
        self.assertNotIn("nousresearch/hermes-agent:latest", compose)
        self.assertIn("command: gateway run", compose)
        self.assertIn("API_SERVER_ENABLED", compose)
        self.assertIn('HOME: "/opt/data/home"', compose)
        self.assertIn("GEMINI_API_KEY", compose)
        self.assertIn("GOOGLE_API_KEY", compose)
        self.assertIn("./skills/kmuwiki:/opt/data/skills/kmuwiki:ro", compose)
        self.assertNotIn("no-new-privileges:true", compose)
        self.assertNotIn("/volume1/jdh/kmuwiki/01_raw", compose)

    def test_env_example_has_only_user_scoped_kmuwiki_credentials(self):
        env = (HERMES / ".env.example").read_text(encoding="utf-8")

        self.assertIn("API_SERVER_KEY=", env)
        self.assertIn("KMUWIKI_API_BASE_URL=", env)
        self.assertIn("KMUWIKI_AUTH_TOKEN=", env)
        self.assertIn("NEXT_PUBLIC_SUPABASE_URL=", env)
        self.assertIn("NEXT_PUBLIC_SUPABASE_ANON_KEY=", env)
        self.assertIn("KMUWIKI_AUTH_EMAIL=", env)
        self.assertIn("KMUWIKI_AUTH_PASSWORD=", env)
        self.assertIn("KMUWIKI_API_SECRET=", env)
        self.assertIn("OPENROUTER_API_KEY=", env)
        self.assertIn("OPENAI_API_KEY=", env)
        self.assertNotIn("SUPABASE_SERVICE_ROLE_KEY", env)

    def test_skill_declares_api_only_trust_boundary_and_helper_path(self):
        skill = (SKILL / "SKILL.md").read_text(encoding="utf-8")

        self.assertIn("name: kmu-wiki-search", skill)
        self.assertIn("Never read original ZIP", skill)
        self.assertIn("Never query Supabase tables directly", skill)
        self.assertIn("Supabase Auth login", skill)
        self.assertIn("kmuwiki_api.py workflow", skill)

    def test_ops_scripts_keep_logs_inside_deploy_directory(self):
        check = (HERMES / "check-hermes.sh").read_text(encoding="utf-8")
        skills = (HERMES / "test-hermes-skills.sh").read_text(encoding="utf-8")
        chat = (HERMES / "test-hermes-chat.sh").read_text(encoding="utf-8")
        sync = (HERMES / "sync-hermes-env.sh").read_text(encoding="utf-8")
        smoke = (HERMES / "test-kmuwiki.sh").read_text(encoding="utf-8")
        workflow = (HERMES / "test-kmuwiki-workflow.sh").read_text(encoding="utf-8")
        verify = (HERMES / "verify-hermes.sh").read_text(encoding="utf-8")
        final_check = (HERMES / "final-check-hermes.sh").read_text(encoding="utf-8")
        windows_final_check = (HERMES / "run-final-check-from-windows.ps1").read_text(encoding="utf-8")
        windows_final_check_cmd = (HERMES / "run-final-check-from-windows.cmd").read_text(encoding="utf-8")
        runbook = (HERMES / "RUN_FINAL_CHECK.txt").read_text(encoding="utf-8")
        dsm_task_runbook = (HERMES / "RUN_FINAL_CHECK_DSM_TASK.txt").read_text(encoding="utf-8")
        status = (HERMES / "status-hermes.sh").read_text(encoding="utf-8")
        wait = (HERMES / "wait-hermes-api.sh").read_text(encoding="utf-8")
        cleanup = (HERMES / "cleanup-hermes-root.sh").read_text(encoding="utf-8")
        access_sql = (HERMES / "access-log-check.sql").read_text(encoding="utf-8")
        start = (HERMES / "start-hermes.sh").read_text(encoding="utf-8")
        ignore = (HERMES / ".gitignore").read_text(encoding="utf-8")
        version = (HERMES / "VERSION").read_text(encoding="utf-8").strip()

        for script in (check, skills, chat, sync, smoke, workflow, verify, final_check, status, wait):
            self.assertIn('LOG_DIR="${HERMES_LOG_DIR:-$SCRIPT_DIR/logs}"', script)
            self.assertNotIn("/volume1/jdh/hermes-", script)
            self.assertIn("DEPLOY_VERSION", script)

        for script in (check, skills, chat, sync, smoke, workflow, verify, final_check, wait, start):
            self.assertIn("/usr/local/bin:/usr/local/sbin:/usr/syno/bin", script)

        self.assertRegex(version, r"^\d{4}-\d{2}-\d{2}\.\d+$")
        self.assertIn("logs/", ignore)
        self.assertIn(".env", ignore)
        self.assertIn("check-hermes", verify)
        self.assertIn("test-hermes-skills", verify)
        self.assertIn("wait-hermes-api", verify)
        self.assertIn("test-kmuwiki", verify)
        self.assertIn("test-kmuwiki-workflow", verify)
        self.assertIn("test-hermes-chat", verify)
        self.assertIn("HERMES_RUN_CHAT_TEST", verify)
        self.assertIn("HERMES_SKIP_START", verify)
        self.assertIn("HERMES_RUN_CHAT_TEST=1", final_check)
        self.assertIn("sync-hermes-env.sh", final_check)
        self.assertIn("HERMES_SYNC_RESTART=1", final_check)
        self.assertIn("HERMES_SKIP_START", final_check)
        self.assertIn("HERMES_STEP_TIMEOUT", final_check)
        self.assertIn("FINAL_CHECK=PASSED", final_check)
        self.assertIn("access-log-check.sql", final_check)
        self.assertIn("sudo -E env HOME=/root", final_check)
        self.assertIn("final-check-hermes.sh", windows_final_check)
        self.assertIn("sudo password", windows_final_check)
        self.assertIn("run-final-check-from-windows.ps1", windows_final_check_cmd)
        self.assertIn("FINAL_CHECK=PASSED", runbook)
        self.assertIn("CHAT_CHECK=FOUND_EVIDENCE_RESPONSE", runbook)
        self.assertIn("DSM Task Scheduler", dsm_task_runbook)
        self.assertIn("sh final-check-hermes.sh", dsm_task_runbook)
        self.assertIn("HERMES_STEP_TIMEOUT", verify)
        self.assertIn("HERMES_FORCE_RECREATE", start)
        self.assertIn("HERMES_SKIP_PULL", start)
        self.assertIn("HERMES_PREP_TIMEOUT", start)
        self.assertIn("chown -R 10000:10000 /opt/data/skills/kmu-wiki-search", start)
        self.assertNotIn("chown -R 10000:10000 /opt/data ", start)
        self.assertIn("--force-recreate", start)
        self.assertIn('${COMPOSE_PROJECT_NAME}_hermes_run', start)
        self.assertIn("cp -R /opt/data/skills/kmuwiki/kmu-wiki-search /opt/data/skills/", start)
        self.assertIn("cp -R /opt/data/skills/kmuwiki/kmu-wiki-search /opt/data/home/.hermes/skills/", start)
        self.assertIn("cp -R /opt/data/skills/kmuwiki/kmu-wiki-search", start)
        self.assertIn("/v1/skills", skills)
        self.assertIn("/v1/chat/completions", chat)
        self.assertIn("CHAT_CHECK=FOUND_EVIDENCE_RESPONSE", chat)
        self.assertIn("FAILED_NO_INFERENCE_PROVIDER", chat)
        self.assertIn("PROVIDER ENV PRESENCE", chat)
        self.assertIn("DOTENV_{key}", chat)
        self.assertIn("/opt/data/home/.hermes/.env", chat)
        self.assertIn("ENV_SYNC=OK", sync)
        self.assertIn("/opt/data/home/.hermes/.env", sync)
        self.assertIn("OPENROUTER_API_KEY", start)
        self.assertIn("OPENAI_API_KEY", start)
        self.assertIn("HERMES_API_READY", wait)
        self.assertIn("http://127.0.0.1:8642/health", wait)
        self.assertIn("kmu-wiki-search", skills)
        self.assertIn("/opt/data/skills/kmu-wiki-search/SKILL.md", skills)
        self.assertIn("workflow", workflow)
        self.assertIn("WORKFLOW_CHECK=FOUND_KEYS", workflow)
        self.assertIn("hermes-status.log", status)
        self.assertIn("hermes-chat-test.log", status)
        self.assertIn("Hermes status summary", status)
        self.assertIn("access_log", access_sql)
        self.assertIn("hermes-agent@kmu.local", access_sql)

        self.assertIn("--dry-run", cleanup)
        self.assertIn("--apply", cleanup)
        self.assertIn("Refusing to operate outside /volume1", cleanup)
        self.assertIn("hermes-*.log", cleanup)
        self.assertIn("printf 'hermes\\r'", cleanup)

    def test_helper_sends_source_year_separately_from_target_year(self):
        helper = load_helper()
        args = type("Args", (), {
            "query": "교환학생 홍보",
            "k": 12,
            "dept": "국제교류팀",
            "source_year": 2026,
            "target_year": 2027,
            "known_document_id": ["doc-1"],
            "report_type": "result",
            "recipient": "총장",
            "sender": "국제처",
        })()

        payload = helper.build_payload(args, include_target=True, include_report=True)

        self.assertEqual(payload["source_year"], 2026)
        self.assertEqual(payload["year"], 2026)
        self.assertEqual(payload["target_year"], 2027)
        self.assertEqual(payload["known_document_ids"], ["doc-1"])
        self.assertEqual(payload["report_type"], "result")

    def test_helper_can_use_dedicated_account_login_instead_of_static_jwt(self):
        helper = load_helper()
        captured = {}

        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"access_token":"jwt-from-login"}'

        def fake_urlopen(request, timeout):
            captured["url"] = request.full_url
            captured["timeout"] = timeout
            captured["apikey"] = request.get_header("Apikey")
            captured["body"] = request.data.decode("utf-8")
            return FakeResponse()

        client = helper.KmuWikiClient(
            "https://kmuwiki.example.com/api",
            supabase_url="https://supabase.example.com",
            supabase_anon_key="anon-key",
            auth_email="hermes-agent@kmu.local",
            auth_password="secret",
        )

        with patch.object(helper.urllib.request, "urlopen", fake_urlopen):
            token = client.get_auth_token()

        self.assertEqual(token, "jwt-from-login")
        self.assertEqual(
            captured["url"],
            "https://supabase.example.com/auth/v1/token?grant_type=password",
        )
        self.assertEqual(captured["apikey"], "anon-key")
        self.assertIn('"email": "hermes-agent@kmu.local"', captured["body"])

    def test_helper_env_accepts_either_static_token_or_login_credentials(self):
        helper = load_helper()
        base_env = {
            "KMUWIKI_API_BASE_URL": "https://kmuwiki.example.com/api",
            "KMUWIKI_API_SECRET": "",
        }

        with patch.dict(os.environ, {**base_env, "KMUWIKI_AUTH_TOKEN": "jwt"}, clear=True):
            client = helper.KmuWikiClient.from_env()
            self.assertEqual(client.get_auth_token(), "jwt")

        login_env = {
            **base_env,
            "NEXT_PUBLIC_SUPABASE_URL": "https://supabase.example.com",
            "NEXT_PUBLIC_SUPABASE_ANON_KEY": "anon-key",
            "KMUWIKI_AUTH_EMAIL": "hermes-agent@kmu.local",
            "KMUWIKI_AUTH_PASSWORD": "secret",
        }
        with patch.dict(os.environ, login_env, clear=True):
            client = helper.KmuWikiClient.from_env()
            self.assertEqual(client.supabase_url, "https://supabase.example.com")
            self.assertEqual(client.auth_email, "hermes-agent@kmu.local")


if __name__ == "__main__":
    unittest.main()
