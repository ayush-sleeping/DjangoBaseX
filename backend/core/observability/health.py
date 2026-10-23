"""
Health in three rungs (OBSERVABILITY.md § 6; BUILD_ORDER 6.2; closes TECH_DEBT DB-11).

  live        Is this process worth keeping?    no I/O at all       200
  ready       Can this instance serve traffic?  database + cache    200 / 503
  components  Which part is unwell, how badly?  every probe         ok 200 · degraded 200 · down 503

The two public rungs are answered by HealthShortCircuitMiddleware, placed right after
RequestIdMiddleware: before sessions, CSRF, authentication, throttling and ALLOWED_HOSTS (a
container healthcheck calls localhost, which an operator's host list rightly omits). The
orchestrator's probe must never share a rate-limit bucket with an attacker. The views in
core/views.py answer the same way, so reverse() works and the public-route ledger stays honest.

Readiness names a failed dependency from a closed set (`database`, `cache`) and never carries
exception text: a connection error's message includes hosts, ports and sometimes user names. It
probes nothing third-party and never looks at migrations: a provider's outage is not our outage.
The I/O budget is the clients' own timeouts (connect_timeout on the database, socket timeouts on
the cache), configured in settings, never unbounded.

Components runs every registry.health check under HEALTH_PROBE_TIMEOUT_SECONDS. A probe never
propagates: one that raises or times out is `down` if critical, `degraded` otherwise, with the
exception type and a scrubbed message. Only a critical component (the core dependencies) can make
the install `down`; everything else failing is `degraded` and still 200. A stopped worker is a
dashboard item, not a reason for a load balancer to eject the web tier.
"""

import secrets
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse

from core.registry import HealthCheck, PermissionGroupSpec, PermissionSpec, registry

from .scrub import scrub

LIVE_PATHS = frozenset({"", "live/"})  # relative to /<API_PREFIX>/health/
READY_PATH = "ready/"
OK, DEGRADED, DOWN, UNKNOWN = "ok", "degraded", "down", "unknown"
DEFAULT_PROBE_TIMEOUT = 2.0

HEALTH_GROUP = PermissionGroupSpec(
    code="health",
    label="Health",
    module="core",
    order=90,
    permissions=(
        PermissionSpec(
            "core.health.view",
            "Read the components health report (grantable to a monitoring principal alone)",
        ),
    ),
)


# --- The two core dependencies ------------------------------------------------------------------


def probe_database() -> bool:
    """SELECT 1 under a statement timeout where the backend has one. The connect timeout is the
    database OPTIONS' (settings); a backend without statement_timeout relies on that alone."""
    with connection.cursor() as cursor:
        if connection.vendor == "postgresql":
            cursor.execute("SET LOCAL statement_timeout = %s", [int(probe_timeout() * 1000)])
        cursor.execute("SELECT 1")
        return cursor.fetchone()[0] == 1


def probe_cache() -> bool:
    """A set/get round-trip on a random key, not a PING: PING succeeds against a read-only replica
    and a full instance. The cache is in readiness because throttles and session revocation live
    in it (AUTH_BLUEPRINT § 17.4): an instance that cannot reach it enforces per process."""
    key, value = f"health:{secrets.token_hex(8)}", secrets.token_hex(8)
    cache.set(key, value, timeout=5)
    seen = cache.get(key)
    cache.delete(key)
    return seen == value


def core_probes() -> tuple[HealthCheck, ...]:
    """Built per call, so a test can patch probe_database / probe_cache on this module."""
    return (
        HealthCheck("database", "Database", probe_database, critical=True),
        HealthCheck("cache", "Cache", probe_cache, critical=True),
    )


def probe_timeout() -> float:
    return float(getattr(settings, "HEALTH_PROBE_TIMEOUT_SECONDS", DEFAULT_PROBE_TIMEOUT))


# --- Live and ready -----------------------------------------------------------------------------


def live() -> JsonResponse:
    return _never_cached(JsonResponse({"status": OK}))


def ready() -> JsonResponse:
    """503 naming the failed dependencies from a closed set; never exception text."""
    failed = []
    for probe in core_probes():
        try:
            if not probe.check():
                failed.append(probe.key)
        except Exception:  # noqa: BLE001 — any failure is the fixed token, never its text
            failed.append(probe.key)
    if failed:
        return _never_cached(JsonResponse({"status": "unavailable", "failed": failed}, status=503))
    return _never_cached(JsonResponse({"status": OK}))


class HealthShortCircuitMiddleware:
    """Answers the public rungs before sessions, auth, CSRF, throttling and ALLOWED_HOSTS."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.base = f"/{settings.API_PREFIX}/health/"

    def __call__(self, request):
        if request.method in ("GET", "HEAD") and request.path.startswith(self.base):
            rest = request.path[len(self.base) :]
            if rest in LIVE_PATHS:
                return live()
            if rest == READY_PATH:
                return ready()
        return self.get_response(request)


def _never_cached(response: JsonResponse) -> JsonResponse:
    response["Cache-Control"] = "no-store"
    return response


# --- Components ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProbeResult:
    status: str
    detail: str
    ms: int
    critical: bool

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "detail": self.detail,
            "ms": self.ms,
            "critical": self.critical,
        }


def call_with_timeout(fn: Callable[[], object], timeout: float):
    """Runs fn in a worker thread and gives up after `timeout`. The worker is not killed (Python
    cannot), so a hung probe leaks one thread until it returns; the report does not wait for it."""
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        return executor.submit(_in_own_connection, fn).result(timeout=timeout)
    finally:
        executor.shutdown(wait=False)


def _in_own_connection(fn):
    try:
        return fn()
    finally:
        connection.close()  # a worker thread's connection is its own: never leave it open


def run_probe(probe: HealthCheck) -> ProbeResult:
    """Never propagates. A probe that raises or hangs is down (critical) or degraded."""
    started = time.perf_counter()
    try:
        passed = call_with_timeout(probe.check, probe_timeout())
        status, detail = (OK, "") if passed else (_failure_status(probe), "check returned False")
    except FutureTimeout:
        status, detail = _failure_status(probe), f"timed out after {probe_timeout():g}s"
    except Exception as exc:  # noqa: BLE001 — § 6: the endpoint itself never 500s
        status, detail = _failure_status(probe), f"{type(exc).__name__}: {scrub(str(exc))}"
    ms = round((time.perf_counter() - started) * 1000)
    return ProbeResult(status, detail, ms, probe.critical)


def _failure_status(probe: HealthCheck) -> str:
    return DOWN if probe.critical else DEGRADED


def unapplied_migrations() -> bool:
    """Informative, never gating: how many migrations the database has not applied."""
    from django.db.migrations.executor import MigrationExecutor

    executor = MigrationExecutor(connection)
    plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
    if plan:
        raise RuntimeError(f"{len(plan)} unapplied migration(s)")
    return True


MIGRATIONS_PROBE = HealthCheck("migrations", "Migrations", unapplied_migrations, critical=False)


def components() -> tuple[dict, int]:
    """(body, status code). Only a critical component can make the install down."""
    report = {}
    for probe in (*core_probes(), MIGRATIONS_PROBE, *registry.health.checks()):
        if probe.key in report:  # a core key re-registered by an app: the core probe wins
            continue
        report[probe.key] = run_probe(probe).as_dict()
    statuses = {entry["status"] for entry in report.values()}
    if DOWN in statuses:
        overall, code = DOWN, 503
    elif DEGRADED in statuses or UNKNOWN in statuses:
        overall, code = DEGRADED, 200
    else:
        overall, code = OK, 200
    body = {"status": overall, "release": read_release(), "components": report}
    return body, code


def read_release() -> str:
    path = settings.BASE_DIR.parent / "VERSION"
    try:
        return path.read_text(encoding="utf-8").strip() or UNKNOWN
    except OSError:
        return UNKNOWN
