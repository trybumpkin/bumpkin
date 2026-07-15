from __future__ import annotations


def categorize_failure_reason(reason: str | None) -> str | None:
    if not reason:
        return None
    normalized = reason.strip().lower()
    for markers, category in (
        (("no token available",), "missing_token"),
        (("429", "too many requests"), "rate_limited"),
        (("401", "403", "bad credentials"), "invalid_token"),
        (("certificate_verify_failed", "ssl:"), "ssl_failure"),
        (("nodename nor servname provided", "name or service not known"), "dns_failure"),
        (("http 5", "timed out", "connection refused"), "endpoint_failure"),
        (("schema", "non-json output"), "response_schema_error"),
    ):
        if any(marker in normalized for marker in markers):
            return category
    return "unknown_failure"
