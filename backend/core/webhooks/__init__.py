"""Outbound and inbound webhooks (BUILD_ORDER 7.6; JOBS_AND_INTEGRATIONS.md § 16, § 17)."""

from .emission import emit

__all__ = ["emit"]
