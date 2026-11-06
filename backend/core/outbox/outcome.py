"""What a topic handler is handed and what it answers (JOBS_AND_INTEGRATIONS.md § 12)."""

from dataclasses import dataclass, field
from types import MappingProxyType

EVIDENCE_VALUES = (str, int, float, bool, type(None))
SENT, RETRY, FAILED, SKIPPED, UNKNOWN = "sent", "retry", "failed", "skipped", "unknown"


class ProviderNotConfigured(Exception):
    """Raised by a handler whose integration the product has not switched on. The message is
    recorded as `skipped`, not dead-lettered: a dormant integration must not fill the dead letters.
    """


@dataclass(frozen=True)
class Delivery:
    """One message, as the handler sees it. Ids, never the row: the handler re-reads current
    state and re-validates (still unpaid? recipient suppressed?) before it sends."""

    id: int
    topic: str
    dedupe_key: str  # stable across attempts: pass it on as the provider's idempotency key
    payload: MappingProxyType
    attempt: int  # 1 for the first attempt


@dataclass(frozen=True)
class Outcome:
    """
    A handler returns one of these and never raises. An exception it lets escape is converted:
    a transient one to RETRY on an at_least_once topic, anything on an at_most_once topic to
    UNKNOWN (the provider may have accepted it).
    """

    status: str
    ref: str = ""  # SENT: the provider's message id
    after: float | None = None  # RETRY: the upstream's Retry-After, in seconds
    code: str = ""  # FAILED/RETRY/UNKNOWN: a stable error code; SKIPPED: the reason
    message: str = ""  # scrubbed and truncated before it is stored
    evidence: dict = field(default_factory=dict)  # UNKNOWN: what a human needs to decide

    def __post_init__(self) -> None:
        # Checked here, in the handler, so a bad shape fails while the handler still owns the
        # result, never later when the row is settled and the outcome would be lost.
        if not isinstance(self.evidence, dict) or any(
            not isinstance(k, str) or not isinstance(v, EVIDENCE_VALUES)
            for k, v in self.evidence.items()
        ):
            raise TypeError(
                "Outcome evidence is a flat dict of str keys and str/int/float/bool/None values"
            )

    @classmethod
    def SENT(cls, ref: str = ""):
        return cls(SENT, ref=ref)

    @classmethod
    def RETRY(cls, after: float | None = None, code: str = "", message: str = ""):
        return cls(RETRY, after=after, code=code, message=message)

    @classmethod
    def FAILED(cls, code: str, message: str = ""):
        return cls(FAILED, code=code, message=message)

    @classmethod
    def SKIPPED(cls, reason: str):
        return cls(SKIPPED, code=reason)

    @classmethod
    def UNKNOWN(cls, evidence: dict | None = None, code: str = "", message: str = ""):
        return cls(UNKNOWN, evidence=evidence or {}, code=code, message=message)
