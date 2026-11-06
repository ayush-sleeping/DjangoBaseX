"""The job registry's register-time refusals (JOBS_AND_INTEGRATIONS.md § 1: dbx.jobs.E001–E004)."""

from datetime import date

import pytest
from django.core.checks import Error

from core import checks
from core.jobs.runner import signature_problem
from core.jobs.schedules import cron_fire_times, period_seconds
from core.registry import Cron, Interval, JobRegistry, JobSpec, RegistryError, registry
from tests.core.jobs import fakes


def spec(**overrides) -> JobSpec:
    values = {
        "name": "billing.close_usage",
        "func": "tests.core.jobs.fakes.count_three",
        "owner_module": "billing",
        "description": "Closes usage windows. If it stops, invoices are generated empty.",
    }
    return JobSpec(**(values | overrides))


def test_a_valid_spec_registers_and_seals():
    jobs = JobRegistry()
    jobs.register(spec())
    assert [s.name for s in jobs.specs()] == ["billing.close_usage"]
    with pytest.raises(RegistryError, match="sealed"):
        jobs.register(spec(name="billing.other"))


def test_e001_a_duplicate_name_is_refused():
    jobs = JobRegistry()
    jobs.register(spec())
    with pytest.raises(RegistryError, match="E001"):
        jobs.register(spec(description="Another job that happens to share the name."))


def test_e002_destructive_jobs_ship_disabled():
    with pytest.raises(RegistryError, match="E002"):
        JobRegistry().register(spec(destructive=True))
    JobRegistry().register(spec(destructive=True, enabled_by_default=False))


@pytest.mark.parametrize(("soft", "hard"), [(300, 300), (301, 300), (0, 300)])
def test_e003_the_soft_limit_is_below_the_hard_limit(soft, hard):
    with pytest.raises(RegistryError, match="E003"):
        JobRegistry().register(spec(soft_time_limit=soft, time_limit=hard))


def test_e003_an_interval_jobs_expiry_is_below_its_period():
    with pytest.raises(RegistryError, match="E003"):
        JobRegistry().register(spec(schedule=Interval(900), expires=900))
    JobRegistry().register(spec(schedule=Interval(900), expires=899))


@pytest.mark.parametrize(
    "bad",
    [
        {"name": "close_usage"},
        {"name": "Billing.close"},
        {"func": "not a path"},
        {"func": "single"},
        {"owner_module": " "},
        {"description": ""},
        {"queue": "Bulk Queue"},
        {"schedule": Cron("0 3 * *")},
        {"schedule": Cron("@daily * * * *")},
        {"schedule": Interval(0)},
        {"schedule": "0 3 * * *"},
    ],
)
def test_malformed_specs_are_refused(bad):
    with pytest.raises(RegistryError):
        JobRegistry().register(spec(**bad))


def test_only_jobspecs_register():
    with pytest.raises(RegistryError, match="JobSpec"):
        JobRegistry().register({"name": "billing.x"})


def test_e004_the_signature_is_one_context_argument():
    assert signature_problem(fakes.count_three) is None
    assert signature_problem(fakes.takes_nothing)
    assert signature_problem(fakes.takes_two)
    assert signature_problem("not callable")


def test_e004_the_check_reports_a_func_that_does_not_import(monkeypatch):
    broken = JobRegistry()
    broken.register(spec(func="tests.core.jobs.fakes.no_such_function"))
    broken.register(spec(name="billing.two", func="tests.core.jobs.fakes.takes_two"))
    monkeypatch.setattr(registry, "jobs", broken)
    errors = checks.check_job_callables(None)
    assert {e.id for e in errors} == {"dbx.jobs.E004"} and len(errors) == 2
    assert all(isinstance(e, Error) for e in errors)


def test_e003_the_check_reports_a_cron_expiry_at_or_past_its_period(monkeypatch):
    jobs = JobRegistry()
    jobs.register(spec(schedule=Cron("17 3 * * *"), expires=86_400))
    monkeypatch.setattr(registry, "jobs", jobs)
    assert [e.id for e in checks.check_job_callables(None)] == ["dbx.jobs.E003"]


def test_the_real_registry_passes_its_checks():
    assert checks.check_job_callables(None) == []


@pytest.mark.parametrize(
    ("expression", "seconds"),
    [
        ("17 3 * * *", 86_400),
        ("*/15 * * * *", 900),
        ("5 */6 * * *", 6 * 3600),
        ("0 9 * * 1-5", 3600 * 24),  # Mon–Fri: the shortest gap is a weekday to the next
        ("30 2 * * 0", 7 * 86_400),  # Sunday as 0
        ("30 2 * * 7", 7 * 86_400),  # and as 7
        ("0 0 1 * *", 28 * 86_400),  # monthly: February is the shortest gap
    ],
)
def test_period_seconds(expression, seconds):
    assert period_seconds(Cron(expression)) == seconds


def test_a_restricted_day_of_month_and_day_of_week_fire_on_either():
    fires = list(cron_fire_times(Cron("0 0 13 * 5"), date(2001, 1, 1), 31))
    # January 2001: Fridays 5, 12, 19, 26 and the 13th (a Saturday).
    assert [f.day for f in fires] == [5, 12, 13, 19, 26]


def test_every_minute_stops_at_the_cron_floor(monkeypatch):
    import core.jobs.schedules as schedules

    seen = []
    real = schedules.cron_fire_times

    def counting(*args):
        for fire in real(*args):
            seen.append(fire)
            yield fire

    monkeypatch.setattr(schedules, "cron_fire_times", counting)
    assert period_seconds(Cron("* * * * *")) == 60
    assert len(seen) == 2  # the early exit, not ~2.1 million firings
