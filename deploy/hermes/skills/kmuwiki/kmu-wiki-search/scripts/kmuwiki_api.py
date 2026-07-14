#!/usr/bin/env python3
"""Small Hermes skill helper for authenticated kmuwiki API calls.

The script intentionally uses only the Python standard library so it can run in
the published Hermes container without installing extra packages.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any


def main() -> int:
    parser = argparse.ArgumentParser(description="Call kmuwiki search/RAG APIs.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("search", "hermes", "reports", "workflow"):
        add_common_args(subparsers.add_parser(name))

    args = parser.parse_args()
    client = KmuWikiClient.from_env()

    if args.command == "search":
        result = client.post("search", build_payload(args))
    elif args.command == "hermes":
        result = client.post("hermes", build_payload(args, include_target=True))
    elif args.command == "reports":
        result = client.post("reports", build_payload(args, include_target=True, include_report=True))
    elif args.command == "workflow":
        search = client.post("search", build_payload(args))
        hermes = client.post("hermes", build_payload(args, include_target=True))
        result = {"search": search, "hermes": hermes}
        if args.include_report:
            result["report"] = client.post(
                "reports",
                build_payload(args, include_target=True, include_report=True),
            )
    else:
        parser.error(f"unknown command: {args.command}")
        return 2

    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--query", required=True, help="Natural-language search query.")
    parser.add_argument("--source-year", type=int, default=env_int("KMUWIKI_DEFAULT_SOURCE_YEAR"))
    parser.add_argument("--target-year", type=int)
    parser.add_argument("--dept", default=os.environ.get("KMUWIKI_DEFAULT_DEPT") or None)
    parser.add_argument("--k", type=int, default=env_int("KMUWIKI_DEFAULT_K") or 12)
    parser.add_argument("--known-document-id", action="append", default=[])
    parser.add_argument("--report-type", default="result")
    parser.add_argument("--recipient", default="")
    parser.add_argument("--sender", default="")
    parser.add_argument("--include-report", action="store_true")


def build_payload(
    args: argparse.Namespace,
    *,
    include_target: bool = False,
    include_report: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "query": args.query,
        "k": args.k,
    }
    if args.dept:
        payload["dept"] = args.dept
    if args.source_year:
        payload["source_year"] = args.source_year
        payload["year"] = args.source_year
    if include_target and args.target_year:
        payload["target_year"] = args.target_year
    if include_target and args.known_document_id:
        payload["known_document_ids"] = args.known_document_id
    if include_report:
        payload["report_type"] = args.report_type
        if args.recipient:
            payload["recipient"] = args.recipient
        if args.sender:
            payload["sender"] = args.sender
    return payload


class KmuWikiClient:
    def __init__(
        self,
        base_url: str,
        auth_token: str = "",
        api_secret: str = "",
        *,
        supabase_url: str = "",
        supabase_anon_key: str = "",
        auth_email: str = "",
        auth_password: str = "",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token.strip()
        self.api_secret = api_secret
        self.supabase_url = supabase_url.rstrip("/")
        self.supabase_anon_key = supabase_anon_key.strip()
        self.auth_email = auth_email.strip()
        self.auth_password = auth_password

    @classmethod
    def from_env(cls) -> "KmuWikiClient":
        base_url = os.environ.get("KMUWIKI_API_BASE_URL", "").strip()
        auth_token = os.environ.get("KMUWIKI_AUTH_TOKEN", "").strip()
        api_secret = os.environ.get("KMUWIKI_API_SECRET", "").strip()
        supabase_url = (
            os.environ.get("NEXT_PUBLIC_SUPABASE_URL", "")
            or os.environ.get("SUPABASE_URL", "")
        ).strip()
        supabase_anon_key = (
            os.environ.get("NEXT_PUBLIC_SUPABASE_ANON_KEY", "")
            or os.environ.get("SUPABASE_ANON_KEY", "")
        ).strip()
        auth_email = os.environ.get("KMUWIKI_AUTH_EMAIL", "").strip()
        auth_password = os.environ.get("KMUWIKI_AUTH_PASSWORD", "")
        if not base_url:
            raise SystemExit("KMUWIKI_API_BASE_URL is required")
        if not auth_token and not (supabase_url and supabase_anon_key and auth_email and auth_password):
            raise SystemExit(
                "Either KMUWIKI_AUTH_TOKEN or "
                "NEXT_PUBLIC_SUPABASE_URL/NEXT_PUBLIC_SUPABASE_ANON_KEY/"
                "KMUWIKI_AUTH_EMAIL/KMUWIKI_AUTH_PASSWORD is required"
            )
        return cls(
            base_url,
            auth_token,
            api_secret,
            supabase_url=supabase_url,
            supabase_anon_key=supabase_anon_key,
            auth_email=auth_email,
            auth_password=auth_password,
        )

    def post(self, endpoint: str, payload: dict[str, Any]) -> Any:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "content-type": "application/json",
            "authorization": f"Bearer {self.get_auth_token()}",
        }
        if self.api_secret:
            headers["x-kmuwiki-api-secret"] = self.api_secret
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"{endpoint} failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"{endpoint} failed: {exc.reason}") from exc
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return {"raw": body}

    def get_auth_token(self) -> str:
        if self.auth_token:
            return self.auth_token
        self.auth_token = self.sign_in_with_password()
        return self.auth_token

    def sign_in_with_password(self) -> str:
        url = f"{self.supabase_url}/auth/v1/token?grant_type=password"
        payload = {
            "email": self.auth_email,
            "password": self.auth_password,
        }
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {
            "apikey": self.supabase_anon_key,
            "content-type": "application/json",
        }
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise SystemExit(f"Supabase login failed: HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise SystemExit(f"Supabase login failed: {exc.reason}") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise SystemExit("Supabase login failed: non-JSON response") from exc
        token = parsed.get("access_token")
        if not isinstance(token, str) or not token.strip():
            raise SystemExit("Supabase login failed: missing access_token")
        return token.strip()


def env_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


if __name__ == "__main__":
    sys.exit(main())
