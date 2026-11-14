"""Provider errors and their mapping to our responses (JOBS_AND_INTEGRATIONS.md § 20)."""

from .errors import (
    OutboundBlocked,
    ProviderAuthError,
    ProviderClientError,
    ProviderError,
    ProviderNotConfigured,
    ProviderRateLimited,
    ProviderResponseError,
    ProviderUnavailable,
    UnsafeDestination,
    from_exception,
    raise_for_upstream,
)

__all__ = [
    "OutboundBlocked",
    "ProviderAuthError",
    "ProviderClientError",
    "ProviderError",
    "ProviderNotConfigured",
    "ProviderRateLimited",
    "ProviderResponseError",
    "ProviderUnavailable",
    "UnsafeDestination",
    "from_exception",
    "raise_for_upstream",
]
