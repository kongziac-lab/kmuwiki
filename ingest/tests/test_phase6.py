import json
import tempfile
import unittest
from pathlib import Path

from kmu_verify.phase6 import VerificationResult, write_report


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
