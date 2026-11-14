"""The ops jobs' bodies (BUILD_ORDER 7.8). Each returns normally: a monitor that finds a problem
has worked (§ 19). They import neither notify() nor a channel: the dispatcher is the only door."""

from core.jobs import JobContext

from . import digest, monitors


def run_monitor(ctx: JobContext) -> int:
    return monitors.run()


def run_alert_digest(ctx: JobContext) -> int:
    return digest.run_digest()


def run_release_held(ctx: JobContext) -> int:
    return digest.release_quiet()
