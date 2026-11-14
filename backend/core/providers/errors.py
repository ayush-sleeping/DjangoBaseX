"""
One exception hierarchy every adapter raises, and the one place an upstream status becomes it
(JOBS_AND_INTEGRATIONS.md § 20). core.api.exceptions maps each to our own response.

The expensive mistake this prevents: an upstream 401 passed straight through tells our frontend
that OUR session is invalid, and it signs the user out over a partner's expired key. So an upstream
401/403 is `ProviderAuthError` → our 502, never our 401.

No status mapping is hand-rolled anywhere else (tests/architecture/test_no_hand_rolled_status_
mapping.py). Messages that leave here are scrubbed and truncated: an upstream body can carry
recipients, URLs and tokens.
"""

from __future__ import annotations

from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

MAX_DETAIL_LENGTH = 200
# Upstream 4xx we pass through as the same status; any other 4xx becomes our 400.
PASSED_THROUGH_4XX = frozenset({400, 404, 409, 422})


def _safe(text: object) -> str:
    from core.observability.scrub import default_rules

    return default_rules().scrub_text(str(text or ""))[:MAX_DETAIL_LENGTH]


class ProviderError(Exception):
    """Base: something about a call to another system. `status`/`code` are OUR response."""

    status = 502
    code = "upstream_error"
    message = "The partner service returned an error."
    transient = False  # read by core.jobs.retry.RetryPolicy.is_transient

    def __init__(
        self,
        provider: str = "",
        *,
        upstream_status: int | None = None,
        code: str | None = None,
        safe_detail: str = "",
        retry_after: float | None = None,
    ) -> None:
        self.provider = provider
        self.upstream_status = upstream_status
        if code:
            self.code = code
        self.safe_detail = _safe(safe_detail)
        self.retry_after = retry_after
        super().__init__(
            f"{self.code}: {provider or 'provider'}"
            + (f" ({upstream_status})" if upstream_status else "")
        )


class ProviderAuthError(ProviderError):
    """Upstream 401/403: OUR credential for them is bad. Never our 401."""

    code = "upstream_auth_failed"
    message = "Our credentials for the partner service were refused."


class ProviderRateLimited(ProviderError):
    """Upstream 429 that persisted after one bounded retry."""

    status = 503
    code = "upstream_rate_limited"
    message = "The partner service is rate limiting us. Try again shortly."
    transient = True


class ProviderUnavailable(ProviderError):
    """Upstream 5xx, a timeout or a connection error."""

    code = "upstream_unavailable"
    message = "The partner service is unavailable."
    transient = True

    def __init__(self, *args, timeout: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if timeout:
            self.status = 504
            self.code = "upstream_timeout"
            self.message = "The partner service did not answer in time."


class ProviderClientError(ProviderError):
    """Another upstream 4xx: the request was wrong. The same status, with a sanitised detail."""

    status = 400
    code = "upstream_rejected"
    message = "The partner service rejected the request."

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        if self.upstream_status in PASSED_THROUGH_4XX:
            self.status = self.upstream_status


class ProviderResponseError(ProviderError):
    """A 2xx that is malformed or breaks the contract, or a response over the size cap."""

    code = "upstream_bad_response"
    message = "The partner service sent a response we could not use."


class ProviderNotConfigured(ProviderError):
    """The integration is not set up. The outbox records it as `skipped`, not dead-lettered."""

    status = 503
    code = "integration_not_configured"
    message = "This integration is not configured."


class OutboundBlocked(ProviderError):
    """The non-production guard refused it (§ 27). 423, never 401/403: callers would treat those
    as a credential fault and mark the credential bad or retry."""

    status = 423
    code = "blocked_locally"
    message = "Outbound calls to this host are blocked outside production."


class UnsafeDestination(ProviderClientError):
    """The address is not safe to connect to (§ 18): private, loopback, metadata, unresolvable,
    or a URL shape we refuse. Raised BEFORE any connection is made."""

    status = 400
    code = "unsafe_destination"
    message = "That address cannot be reached from this service."

    def __init__(self, reason: str, *, host: str = "") -> None:
        self.reason, self.host = reason, host
        super().__init__(host, safe_detail=reason)
        self.args = (f"unsafe_destination ({reason}): {host or 'no host'}",)


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Seconds from a Retry-After header: delta-seconds or an HTTP-date. None when absent/bad."""
    if not value:
        return None
    value = value.strip()
    if value.isdigit():
        return float(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return max(0.0, (moment - (now or datetime.now(UTC))).total_seconds())


def raise_for_upstream(response, provider: str, *, detail: str = "") -> None:
    """
    Raise the ProviderError an upstream response means, or return for a 2xx/3xx. `detail` is
    the ONE field the adapter chose to surface (never the body wholesale); it is scrubbed.
    """
    status = response.status_code
    if status < 400:
        return
    kwargs = {"upstream_status": status, "safe_detail": detail}
    retry_after = parse_retry_after(response.headers.get("Retry-After"))
    if status in (401, 403):
        raise ProviderAuthError(provider, **kwargs)
    if status == 429:
        raise ProviderRateLimited(provider, retry_after=retry_after, **kwargs)
    if status in (408, 504):
        raise ProviderUnavailable(provider, timeout=True, retry_after=retry_after, **kwargs)
    if status >= 500:
        raise ProviderUnavailable(provider, retry_after=retry_after, **kwargs)
    raise ProviderClientError(provider, **kwargs)


def from_exception(exc: BaseException, provider: str) -> ProviderError:
    """Translate a transport-level exception at the adapter boundary (§ 20)."""
    import httpx

    if isinstance(exc, ProviderError):
        return exc
    if isinstance(exc, httpx.TimeoutException):
        return ProviderUnavailable(provider, timeout=True, code=None)
    if isinstance(exc, (httpx.TransportError, ConnectionError, TimeoutError)):
        return ProviderUnavailable(provider)
    return ProviderResponseError(provider)
