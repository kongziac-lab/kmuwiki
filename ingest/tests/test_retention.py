import unittest
from datetime import datetime, timezone

from kmu_ingest.retention import cleanup_security_retention, retention_cutoffs


class _Response:
    def __init__(self, count):
        self.count = count
        self.data = []


class _Query:
    def __init__(self, calls, table):
        self.calls = calls
        self.table = table
        self.column = None
        self.cutoff = None

    def delete(self, **kwargs):
        self.calls.append((self.table, "delete", kwargs))
        return self

    def lt(self, column, cutoff):
        self.column = column
        self.cutoff = cutoff
        self.calls.append((self.table, "lt", column, cutoff))
        return self

    def execute(self):
        return _Response(3 if self.table == "access_log" else 5)


class _Client:
    def __init__(self):
        self.calls = []

    def table(self, name):
        return _Query(self.calls, name)


class TestSecurityRetention(unittest.TestCase):
    def test_cutoffs_enforce_minimum_windows(self):
        now = datetime(2026, 7, 15, 3, 17, tzinfo=timezone.utc)

        audit, rate_limit = retention_cutoffs(now, audit_days=1, rate_limit_days=0)

        self.assertEqual(audit, "2026-06-15T03:17:00+00:00")
        self.assertEqual(rate_limit, "2026-07-14T03:17:00+00:00")

    def test_cleanup_deletes_only_expired_security_rows(self):
        client = _Client()
        now = datetime(2026, 7, 15, 3, 17, tzinfo=timezone.utc)

        result = cleanup_security_retention(client, now=now)

        self.assertEqual(result, {"access_log": 3, "api_rate_limits": 5})
        self.assertIn(("access_log", "lt", "at", "2026-01-16T03:17:00+00:00"), client.calls)
        self.assertIn(("api_rate_limits", "lt", "window_started", "2026-07-14T03:17:00+00:00"), client.calls)


if __name__ == "__main__":
    unittest.main()
