import unittest

from kmu_query.audit import log_access, sanitize_audit_query
from kmu_query.retriever import Source


class FakeRPC:
    def __init__(self, captured, name, params):
        captured.append((name, params))

    def execute(self):
        raise RuntimeError("audit db down")


class FakeClient:
    def __init__(self):
        self.calls = []

    def rpc(self, name, params):
        return FakeRPC(self.calls, name, params)


class TestAuditLogging(unittest.TestCase):
    def test_masks_sensitive_values_and_caps_query_length(self):
        query = "hong@example.com 010-1234-5678 900101-1234567 " + ("가" * 600)
        sanitized = sanitize_audit_query(query)

        self.assertIn("[이메일]", sanitized)
        self.assertIn("[전화번호]", sanitized)
        self.assertIn("[주민등록번호]", sanitized)
        self.assertNotIn("hong@example.com", sanitized)
        self.assertLessEqual(len(sanitized), 500)

    def test_logs_unique_document_ids_and_never_breaks_request(self):
        client = FakeClient()
        sources = [
            Source("d1", 0, "내용", 0.9),
            Source("d1", 1, "다른 청크", 0.8),
            Source("d2", 0, "내용", 0.7),
        ]

        log_access(client, action="search", query="면접", sources=sources)

        self.assertEqual(client.calls[0][0], "log_search_event")
        self.assertEqual(client.calls[0][1]["document_ids"], ["d1", "d2"])
        self.assertEqual(client.calls[0][1]["action_text"], "search")
        self.assertEqual(client.calls[0][1]["result_count"], 2)
        self.assertEqual(client.calls[1][0], "log_access")

    def test_caps_document_ids_sent_to_audit_rpc(self):
        client = FakeClient()
        sources = [Source(f"d{index}", 0, "내용", 0.5) for index in range(80)]

        log_access(client, action="search", query="질문", sources=sources)

        self.assertEqual(len(client.calls[0][1]["document_ids"]), 50)
        self.assertEqual(client.calls[0][1]["result_count"], 80)


if __name__ == "__main__":
    unittest.main()
