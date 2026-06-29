import unittest

from kmu_query.audit import log_access
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
    def test_logs_unique_document_ids_and_never_breaks_request(self):
        client = FakeClient()
        sources = [
            Source("d1", 0, "내용", 0.9),
            Source("d1", 1, "다른 청크", 0.8),
            Source("d2", 0, "내용", 0.7),
        ]

        log_access(client, action="search", query="면접", sources=sources)

        self.assertEqual(client.calls[0][0], "log_access")
        self.assertEqual(client.calls[0][1]["document_ids"], ["d1", "d2"])
        self.assertEqual(client.calls[0][1]["action_text"], "search")


if __name__ == "__main__":
    unittest.main()
