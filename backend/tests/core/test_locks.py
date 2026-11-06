"""Locks (JOBS_AND_INTEGRATIONS.md § 9): token-checked release, short TTLs, a declared direction
when the store is down. Each store contract runs on the in-process store, and on Redis's Lua path
through fakeredis when it is installed."""

import threading
import time

import pytest
from django.db import connection, transaction

from core import locks
from core.locks import (
    MAX_LOCK_TTL_SECONDS,
    LockStoreUnavailable,
    MemoryStore,
    RedisStore,
    advisory_xact_lock,
    set_store,
    single_flight,
)


def _redis_store():
    fakeredis = pytest.importorskip("fakeredis", reason="fakeredis[lua] is a dev dependency")
    pytest.importorskip("lupa", reason="fakeredis needs lupa to run the Lua scripts")
    return RedisStore(fakeredis.FakeRedis())


@pytest.fixture(params=["memory", "redis"])
def store(request):
    built = MemoryStore() if request.param == "memory" else _redis_store()
    set_store(built)
    yield built
    set_store(None)


def test_release_does_not_delete_a_successors_lock(store):
    assert store.acquire("k", "first", 50)
    time.sleep(0.08)  # the first holder overran its TTL
    assert store.acquire("k", "second", 5_000)
    assert store.release("k", "first") is False  # a plain DEL here would free "second"'s lock
    assert store.acquire("k", "third", 5_000) is False
    assert store.release("k", "second") is True


def test_ttl_expires_after_a_killed_holder(store):
    assert store.acquire("k", "killed", 50)  # never released: the holder died
    assert store.acquire("k", "next", 5_000) is False
    time.sleep(0.08)
    assert store.acquire("k", "next", 5_000)


def test_extend_checks_the_token(store):
    assert store.acquire("k", "mine", 60)
    assert store.extend("k", "someone-else", 5_000) is False
    assert store.extend("k", "mine", 5_000) is True
    time.sleep(0.1)
    assert store.acquire("k", "other", 5_000) is False  # renewed past the original TTL


def test_single_flight_lets_one_holder_in_and_releases_on_the_way_out(store):
    with single_flight("job:x", 5_000) as outer:
        assert outer and outer.held
        with single_flight("job:x", 5_000) as inner:
            assert inner is None
    with single_flight("job:x", 5_000) as again:
        assert again


def test_single_flight_releases_when_the_work_raises(store):
    with pytest.raises(RuntimeError), single_flight("job:x", 5_000):
        raise RuntimeError("boom")
    with single_flight("job:x", 5_000) as lease:
        assert lease


class DownStore:
    def acquire(self, *args):
        raise LockStoreUnavailable("ConnectionError: refused")


def test_unavailable_store_skips_by_default(caplog):
    set_store(DownStore())
    try:
        with single_flight("job:x", 5_000) as lease:
            assert lease is None
        with single_flight("job:x", 5_000, on_unavailable="proceed") as lease:
            assert lease and not lease.held
            assert lease.extend() is True  # nothing to renew
    finally:
        set_store(None)
    assert "core.lock.store_unavailable" in caplog.text


def test_a_redis_outage_is_reported_as_unavailable():
    redis = pytest.importorskip("redis")
    client = redis.Redis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2)
    with pytest.raises(LockStoreUnavailable):
        RedisStore.__new__(RedisStore)._call(client.set, "k", "v", nx=True, px=10)


def test_the_direction_must_be_declared():
    with (
        pytest.raises(ValueError, match="on_unavailable"),
        single_flight("k", 10, on_unavailable=""),
    ):
        pass


@pytest.mark.parametrize("ttl_ms", [0, -5, MAX_LOCK_TTL_SECONDS * 1000 + 1])
def test_ttls_are_short_and_positive(ttl_ms):
    with pytest.raises(ValueError), single_flight("k", ttl_ms):
        pass


def test_keys_are_namespaced_by_product(settings):
    settings.PRODUCT_SLUG = "acme"
    assert locks._namespaced("job:x") == "acme:lock:job:x"


def test_the_store_comes_from_settings(settings):
    set_store(None)
    settings.LOCKS_REDIS_URL = ""
    assert isinstance(locks.get_store(), MemoryStore)
    set_store(None)
    settings.LOCKS_REDIS_URL = "redis://127.0.0.1:1/0"
    try:
        assert isinstance(locks.get_store(), RedisStore)  # lazily: nothing connects yet
    finally:
        set_store(None)


# --- advisory_xact_lock -------------------------------------------------------------------------


def test_advisory_lock_refuses_to_run_outside_a_transaction():
    with pytest.raises(RuntimeError, match="atomic"):
        advisory_xact_lock("k")


@pytest.mark.django_db
def test_advisory_lock_inside_a_transaction():
    with transaction.atomic():
        assert advisory_xact_lock("billing:account:7") is True


@pytest.mark.django_db
@pytest.mark.skipif(connection.vendor != "postgresql", reason="advisory locks are PostgreSQL's")
def test_advisory_lock_excludes_another_transaction_until_it_ends():
    seen = []

    def other():
        try:
            with transaction.atomic():
                seen.append(advisory_xact_lock("billing:account:7"))
        finally:
            connection.close()

    with transaction.atomic():
        assert advisory_xact_lock("billing:account:7") is True
        thread = threading.Thread(target=other)
        thread.start()
        thread.join(timeout=30)
    assert seen == [False]
