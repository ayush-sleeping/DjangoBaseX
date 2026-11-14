"""
HTTP in both directions. Inbound: client_ip(), the one place the caller's address is decided.
Outbound: client(purpose), the only way application code calls another system
(JOBS_AND_INTEGRATIONS.md § 18), with the non-production guard (§ 27) built in.
"""

from .client import SafeClient, client, close_all, fan_out, validate_display_url
from .inbound import client_ip

__all__ = ["SafeClient", "client", "client_ip", "close_all", "fan_out", "validate_display_url"]
