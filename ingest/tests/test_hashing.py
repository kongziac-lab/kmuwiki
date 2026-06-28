import unittest

from kmu_ingest.hashing import sha256_bytes


class TestHashing(unittest.TestCase):
    def test_deterministic(self):
        self.assertEqual(sha256_bytes(b"abc"), sha256_bytes(b"abc"))

    def test_distinct(self):
        self.assertNotEqual(sha256_bytes(b"abc"), sha256_bytes(b"abd"))


if __name__ == "__main__":
    unittest.main()
