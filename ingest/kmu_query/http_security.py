"""HTTP authentication, request validation, and distributed rate limiting.

The expensive embedding/RAG path must never run for an unverified bearer token.
Production also fails closed when the internal shared secret or an explicit CORS
allow-list is missing.
"""

from __future__ import annotations

import hmac
import json
from typing import Any

from fastapi import HTTPException, Request


def validate_runtime_security(settings) -> None:
    """Reject unsafe production configuration during application startup."""
    if not getattr(settings, "is_production", False):
        return
    if not settings.api_shared_secret:
        raise RuntimeError("KMU_API_SHARED_SECRET is required in production")
    origins = [item.strip() for item in settings.allowed_origins.split(",") if item.strip()]
    if not origins or "*" in origins:
        raise RuntimeError("KMU_ALLOWED_ORIGINS must be an explicit allow-list in production")
    if settings.api_rate_limit_per_minute < 1:
        raise RuntimeError("KMU_API_RATE_LIMIT_PER_MINUTE must be at least 1")


def require_api_secret(header_secret: str | None, settings) -> None:
    expected = settings.api_shared_secret
    if not expected:
        if getattr(settings, "is_production", False):
            raise HTTPException(status_code=503, detail="API shared secret is not configured")
        return
    if not header_secret or not hmac.compare_digest(header_secret, expected):
        raise HTTPException(status_code=401, detail="invalid api secret")


def bearer_token(authorization: str | None) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="missing authorization")
    token = authorization.split(" ", 1)[1].strip()
    if not token or len(token) > 8192:
        raise HTTPException(status_code=401, detail="invalid authorization")
    return token


def verified_user_client(authorization: str | None, settings):
    """Verify the JWT with Supabase before any embedding or LLM work begins."""
    from supabase import create_client

    token = bearer_token(authorization)
    client = create_client(settings.supabase_url, settings.supabase_anon_key)
    try:
        response = client.auth.get_user(token)
        user = getattr(response, "user", None)
        if user is None or not getattr(user, "id", None):
            raise ValueError("missing user")
    except Exception as exc:
        raise HTTPException(status_code=401, detail="invalid authorization") from exc
    client.postgrest.auth(token)
    return client


def enforce_rate_limit(client, action: str, settings) -> None:
    """Use a Supabase-backed fixed-window limiter shared by all instances."""
    try:
        response = client.rpc("consume_api_rate_limit", {
            "action_text": action,
            "max_requests": settings.api_rate_limit_per_minute,
            "window_seconds": 60,
        }).execute()
        allowed = response.data
        if isinstance(allowed, list):
            allowed = allowed[0] if allowed else False
        if allowed is not True:
            raise HTTPException(status_code=429, detail="rate limit exceeded")
    except HTTPException:
        raise
    except Exception as exc:
        # A missing/broken limiter must not silently expose production capacity.
        if getattr(settings, "is_production", False):
            raise HTTPException(status_code=503, detail="rate limiter unavailable") from exc


def authorize_request(
    authorization: str | None,
    api_secret: str | None,
    action: str,
    settings,
):
    require_api_secret(api_secret, settings)
    client = verified_user_client(authorization, settings)
    enforce_rate_limit(client, action, settings)
    return client


async def read_json_object(request: Request, *, max_bytes: int) -> dict[str, Any]:
    """Read JSON incrementally and stop before an oversized body is buffered."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_bytes:
                raise HTTPException(status_code=413, detail="request body too large")
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid content-length") from exc

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > max_bytes:
            raise HTTPException(status_code=413, detail="request body too large")
        chunks.append(chunk)
    try:
        body = json.loads(b"".join(chunks) or b"{}")
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="invalid JSON body") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return body


def validate_query_body(body: dict[str, Any], settings) -> str:
    query = body.get("query")
    if not isinstance(query, str) or not query.strip():
        raise HTTPException(status_code=400, detail="query is required")
    query = query.strip()
    if len(query) > settings.api_max_query_chars:
        raise HTTPException(status_code=413, detail="query is too long")
    body["query"] = query

    dept = body.get("dept")
    if dept is not None and (not isinstance(dept, str) or len(dept) > 200):
        raise HTTPException(status_code=400, detail="invalid dept")
    known_ids = body.get("known_document_ids")
    if known_ids is not None:
        if not isinstance(known_ids, list) or len(known_ids) > 200:
            raise HTTPException(status_code=400, detail="invalid known_document_ids")
        if any(not isinstance(value, str) or len(value) > 64 for value in known_ids):
            raise HTTPException(status_code=400, detail="invalid known_document_ids")
    return query


def bounded_text(value: Any, *, field: str, max_chars: int) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise HTTPException(status_code=400, detail=f"{field} must be a string")
    if len(value) > max_chars:
        raise HTTPException(status_code=413, detail=f"{field} is too long")
    return value
