from __future__ import annotations

from datetime import datetime, timedelta, timezone


def retention_cutoffs(
    now: datetime | None = None,
    *,
    audit_days: int = 180,
    rate_limit_days: int = 1,
) -> tuple[str, str]:
    current = now or datetime.now(timezone.utc)
    audit_cutoff = current - timedelta(days=max(30, audit_days))
    rate_limit_cutoff = current - timedelta(days=max(1, rate_limit_days))
    return audit_cutoff.isoformat(), rate_limit_cutoff.isoformat()


def cleanup_security_retention(
    client,
    *,
    now: datetime | None = None,
    audit_days: int = 180,
    rate_limit_days: int = 1,
) -> dict[str, int]:
    audit_cutoff, rate_limit_cutoff = retention_cutoffs(
        now,
        audit_days=audit_days,
        rate_limit_days=rate_limit_days,
    )
    audit = (
        client.table("access_log")
        .delete(count="exact")
        .lt("at", audit_cutoff)
        .execute()
    )
    rate_limits = (
        client.table("api_rate_limits")
        .delete(count="exact")
        .lt("window_started", rate_limit_cutoff)
        .execute()
    )
    return {
        "access_log": _deleted_count(audit),
        "api_rate_limits": _deleted_count(rate_limits),
    }


def _deleted_count(response) -> int:
    count = getattr(response, "count", None)
    if isinstance(count, int):
        return count
    data = getattr(response, "data", None)
    return len(data) if isinstance(data, list) else 0
