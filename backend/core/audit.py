"""
log_activity() — the one call-site shape for the audit trail (AUTH_BLUEPRINT § 3.12).

Until the ActivityLog table lands (migration 5 of AUTH_BLUEPRINT § 13), events go to the `audit`
logger. Call sites do not change when the table arrives; only this function does.
"""

import logging

logger = logging.getLogger("audit")


def log_activity(verb: str, actor=None, target=None, **meta) -> None:
    logger.info(
        verb,
        extra={
            "audit_verb": verb,
            "audit_actor": getattr(actor, "public_id", None),
            "audit_target": getattr(target, "public_id", None),
            "audit_meta": meta,
        },
    )
