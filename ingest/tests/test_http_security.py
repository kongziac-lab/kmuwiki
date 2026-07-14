import unittest
from types import SimpleNamespace

from fastapi import HTTPException

from kmu_query.http_security import (
    bearer_token,
    enforce_rate_limit,
    validate_query_body,
    validate_runtime_security,
)


class FakeRateResponse:
    def __init__(self, data):
        self.data = data


class FakeRateRPC:
    def __init__(self, data):
        self.data = data

    def execute(self):
        if isinstance(self.data, Exception):
            raise self.data
        return FakeRateResponse(self.data)


class FakeRateClient:
    def __init__(self, data):
        self.data = data
        self.params = None

    def rpc(self, name, params):
        self.params = (name, params)
        return FakeRateRPC(self.data)


class TestHttpSecurity(unittest.TestCase):
    def test_production_configuration_fails_closed(self):
        base = dict(
            is_production=True,
            api_shared_secret="secret",
            allowed_origins="https://wiki.example.edu",
            api_rate_limit_per_minute=30,
        )
        validate_runtime_security(SimpleNamespace(**base))

        for update in (
            {"api_shared_secret": ""},
            {"allowed_origins": "*"},
            {"allowed_origins": ""},
            {"api_rate_limit_per_minute": 0},
        ):
            with self.assertRaises(RuntimeError):
                validate_runtime_security(SimpleNamespace(**(base | update)))

    def test_bearer_token_and_query_limits(self):
        self.assertEqual(bearer_token("Bearer token-value"), "token-value")
        with self.assertRaises(HTTPException) as missing:
            bearer_token(None)
        self.assertEqual(missing.exception.status_code, 401)

        settings = SimpleNamespace(api_max_query_chars=5)
        self.assertEqual(validate_query_body({"query": " 질문 "}, settings), "질문")
        with self.assertRaises(HTTPException) as too_long:
            validate_query_body({"query": "123456"}, settings)
        self.assertEqual(too_long.exception.status_code, 413)

    def test_distributed_rate_limit_fails_closed_in_production(self):
        settings = SimpleNamespace(api_rate_limit_per_minute=2, is_production=True)
        client = FakeRateClient(True)
        enforce_rate_limit(client, "search", settings)
        self.assertEqual(client.params[0], "consume_api_rate_limit")

        with self.assertRaises(HTTPException) as limited:
            enforce_rate_limit(FakeRateClient(False), "search", settings)
        self.assertEqual(limited.exception.status_code, 429)

        with self.assertRaises(HTTPException) as unavailable:
            enforce_rate_limit(FakeRateClient(RuntimeError("db down")), "search", settings)
        self.assertEqual(unavailable.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
