"""
Locks (JOBS_AND_INTEGRATIONS.md § 9): one primitive per shape of "only one at a time".

- single_flight(key, ttl_ms): Redis SET NX PX with a random token. Release and extend are Lua
  compare-on-token scripts, so a holder whose lock already expired can never delete or prolong
  its successor's lock. The TTL is short (the work's time limit + a margin, capped at
  MAX_LOCK_TTL_SECONDS): a holder killed mid-run blocks the next run for minutes, not a day.
- advisory_xact_lock(key): the transaction-scoped PostgreSQL advisory lock. Released at commit or
  rollback. The session-scoped variants are banned (tests/architecture/test_no_session_advisory_
  locks.py): behind a transaction-pooling PgBouncer a "session" is shared by strangers.
- Row claims are not here: select_for_update(skip_locked=True), stamp, commit, then act
  (core.outbox.drain is the worked example).

The store is Redis at settings.LOCKS_REDIS_URL (by default the cache's Redis). With no URL (a
development or test box on the per-process cache) an in-process store is used: it guards one
process, which is all such a box has; dbx.E005 already refuses a per-process cache in production.
"""

import logging
import os
import secrets
import socket
import threading
import time
from contextlib import contextmanager

from django.conf import settings
from django.db import DEFAULT_DB_ALIAS, connections

logger = logging.getLogger("core.locks")

# A cap, not a default (§ 9): a lock that outlives its holder is an outage with a timer on it.
MAX_LOCK_TTL_SECONDS = 3600
# A job's lock lives for its hard time limit plus this, so it expires soon after a killed holder.
JOB_LOCK_MARGIN_SECONDS = 30
STORE_TIMEOUT_SECONDS = 2.0
SKIP, PROCEED = "skip", "proceed"

_RELEASE = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end
return 0
"""
_EXTEND = """
if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('pexpire', KEYS[1], ARGV[2]) end
return 0
"""


class LockStoreUnavailable(Exception):
    """The lock store could not be reached. What happens next is the caller's declared choice."""


def job_lock_ttl_ms(time_limit: int) -> int:
    return (time_limit + JOB_LOCK_MARGIN_SECONDS) * 1000


def _check_ttl(ttl_ms: int) -> None:
    if not isinstance(ttl_ms, int) or isinstance(ttl_ms, bool) or ttl_ms < 1:
        raise ValueError(f"ttl_ms must be a positive int, got {ttl_ms!r}")
    if ttl_ms > MAX_LOCK_TTL_SECONDS * 1000:
        raise ValueError(
            f"a {ttl_ms} ms lock is above the {MAX_LOCK_TTL_SECONDS}s cap (dbx.jobs.E020): "
            "long work renews with extend() between batches instead"
        )


class RedisStore:
    def __init__(self, client) -> None:
        self._client = client
        self._release = client.register_script(_RELEASE)
        self._extend = client.register_script(_EXTEND)

    def _call(self, fn, *args, **kwargs):
        from redis.exceptions import ConnectionError, TimeoutError

        try:
            return fn(*args, **kwargs)
        except (ConnectionError, TimeoutError, OSError) as exc:
            raise LockStoreUnavailable(f"{type(exc).__name__}: {exc}") from exc

    def acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        return bool(self._call(self._client.set, key, token, nx=True, px=ttl_ms))

    def release(self, key: str, token: str) -> bool:
        return bool(self._call(self._release, keys=[key], args=[token]))

    def extend(self, key: str, token: str, ttl_ms: int) -> bool:
        return bool(self._call(self._extend, keys=[key], args=[token, ttl_ms]))


class MemoryStore:
    """The same contract in one process: token-checked release and extend, expiry by clock."""

    def __init__(self, clock=time.monotonic) -> None:
        self._clock = clock
        self._held: dict[str, tuple[str, float]] = {}
        self._mutex = threading.Lock()

    def _live(self, key: str) -> tuple[str, float] | None:
        entry = self._held.get(key)
        if entry and entry[1] <= self._clock():
            del self._held[key]
            return None
        return entry

    def acquire(self, key: str, token: str, ttl_ms: int) -> bool:
        with self._mutex:
            if self._live(key):
                return False
            self._held[key] = (token, self._clock() + ttl_ms / 1000)
            return True

    def release(self, key: str, token: str) -> bool:
        with self._mutex:
            entry = self._live(key)
            if not entry or entry[0] != token:
                return False
            del self._held[key]
            return True

    def extend(self, key: str, token: str, ttl_ms: int) -> bool:
        with self._mutex:
            entry = self._live(key)
            if not entry or entry[0] != token:
                return False
            self._held[key] = (token, self._clock() + ttl_ms / 1000)
            return True


_store = None
_store_mutex = threading.Lock()


def get_store():
    """Built lazily from LOCKS_REDIS_URL; never reaches into the cache backend's private client."""
    global _store
    with _store_mutex:
        if _store is None:
            url = getattr(settings, "LOCKS_REDIS_URL", "") or ""
            if url:
                import redis

                _store = RedisStore(
                    redis.Redis.from_url(
                        url,
                        socket_timeout=STORE_TIMEOUT_SECONDS,
                        socket_connect_timeout=STORE_TIMEOUT_SECONDS,
                    )
                )
            else:
                _store = MemoryStore()
        return _store


def set_store(store) -> None:
    """Swap the store (tests; None rebuilds from settings on next use)."""
    global _store
    with _store_mutex:
        _store = store


def _namespaced(key: str) -> str:
    # Two products sharing one Redis must not hold each other's locks.
    return f"{settings.PRODUCT_SLUG}:lock:{key}"


class Lease:
    """What single_flight yields. Truthy when the caller may proceed. `held` is False when it
    proceeds without the lock (on_unavailable="proceed" and the store was down)."""

    def __init__(self, key: str, token: str, ttl_ms: int, *, held: bool, store) -> None:
        self.key, self.token, self.ttl_ms, self.held = key, token, ttl_ms, held
        self._store = store

    def __bool__(self) -> bool:
        return True

    def extend(self, ttl_ms: int | None = None) -> bool:
        """Renew between batches. False means the lock was lost: stop, someone else may run."""
        if not self.held:
            return True
        ttl_ms = self.ttl_ms if ttl_ms is None else ttl_ms
        _check_ttl(ttl_ms)
        return self._store.extend(self.key, self.token, ttl_ms)


def _token() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{secrets.token_hex(8)}"


@contextmanager
def single_flight(key: str, ttl_ms: int, *, on_unavailable: str = SKIP):
    """
    `with single_flight(key, ttl_ms) as lease: if not lease: <skip>`. Yields a Lease, or None when
    another holder has it. When the store is unreachable: on_unavailable="skip" (the default)
    yields None; "proceed" yields an unheld Lease, and only work that is itself idempotent may
    declare it. The lock is released by token on the way out, whatever happened inside.
    """
    if on_unavailable not in (SKIP, PROCEED):
        raise ValueError(f'on_unavailable must be "{SKIP}" or "{PROCEED}"')
    _check_ttl(ttl_ms)
    store, name, token = get_store(), _namespaced(key), _token()
    try:
        got = store.acquire(name, token, ttl_ms)
    except LockStoreUnavailable as exc:
        logger.warning(
            "core.lock.store_unavailable",
            extra={"lock": key, "on_unavailable": on_unavailable, "error": str(exc)[:200]},
        )
        yield (
            Lease(name, token, ttl_ms, held=False, store=store)
            if on_unavailable == PROCEED
            else None
        )
        return
    if not got:
        yield None
        return
    try:
        yield Lease(name, token, ttl_ms, held=True, store=store)
    finally:
        try:
            store.release(name, token)
        except LockStoreUnavailable:
            # It expires by TTL: that is what the short TTL is for.
            logger.warning("core.lock.release_failed", extra={"lock": key})


_warned_no_advisory = False


def advisory_xact_lock(key: str, using: str = DEFAULT_DB_ALIAS) -> bool:
    """
    Try the transaction-scoped advisory lock on `key`; True when this transaction holds it. Must be
    called inside transaction.atomic(): it is released at commit or rollback, never by hand.
    On SQLite (development, ADR-0005) it is a no-op that answers True, with a one-time warning.
    """
    global _warned_no_advisory
    conn = connections[using]
    if not conn.in_atomic_block:
        raise RuntimeError(
            "advisory_xact_lock() outside transaction.atomic() would release at once"
        )
    if conn.vendor != "postgresql":
        if not _warned_no_advisory:
            _warned_no_advisory = True
            logger.warning("core.lock.advisory_unsupported", extra={"vendor": conn.vendor})
        return True
    with conn.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", [key])
        return bool(cursor.fetchone()[0])
