"""
Every transient state has a reconciler (JOBS_AND_INTEGRATIONS.md § 11): a row that can sit in a
"waiting for something" state needs a job that goes back and asks, or it stays there forever.

Transient = a status value matching `pending_*`, ending in `ing`, or listed in the model's
explicit TRANSIENT_STATES. Covered = a registered ReconcilerSpec names the model and the state, or
the allow-list below says, per (model, state), what else watches it. Each entry is a reviewed
decision, never a whole model.
"""

import re

from django.apps import apps

from core.registry import registry

TRANSIENT = re.compile(r"^pending_|ing$")

# (model label, state) → what moves or watches it instead of a reconciler.
ALLOWED = {
    ("core.JobRun", "retrying"): "Celery owns the retry; the 7.2 monitor and the queue doctor "
    "report a run that never finishes",
    ("core.WebhookDelivery", "pending"): "its outbox row is the obligation: the drainer sends it, "
    "the lease sweep recovers it, and the outbox doctor reports it stuck (webhooks.deliver)",
    ("core.NotificationDelivery", "pending"): "its outbox row is the obligation "
    "(notifications.deliver): the drainer sends it and the lease sweep recovers it; a stale lease "
    "makes the row `unknown`, never a resend",
    ("core.Notification", "warning"): "a severity level that happens to end in -ing, not a "
    "waiting state: nothing is pending on it",
    ("core.OpsDigestRun", "pending"): "settled from the delivery log at the start of every "
    "ops.alert_digest run (core.ops.digest.settle); one never delivered is given up on after an "
    "hour and its alerts roll into the next digest",
    ("core.Incident", "pending"): "ops.monitor re-syncs every open problem on each run: it is "
    "confirmed once it has persisted, and recovered the run it is gone; a stopped monitor shows "
    "in the schedule doctor",
    ("core.OutboxMessage", "pending"): "the drainer itself is what moves it; the outbox doctor "
    "reports a due message waiting too long (outbox.stuck)",
}


def transient_states() -> set[tuple[str, str]]:
    found = set()
    for model in apps.get_models():
        declared = set(getattr(model, "TRANSIENT_STATES", ()))
        for field in model._meta.concrete_fields:
            if not field.choices:
                continue
            for value, _label in field.flatchoices:
                if isinstance(value, str) and (TRANSIENT.search(value) or value in declared):
                    found.add((model._meta.label, value))
        for value in declared:
            found.add((model._meta.label, value))
    return found


def covered() -> set[tuple[str, str]]:
    return {(spec.model, state) for spec in registry.reconcilers.specs() for state in spec.states}


def test_every_pending_state_has_a_reconciler():
    universe = transient_states()
    assert universe, "found no transient state at all: the scan is looking in the wrong place"
    missing = sorted(universe - covered() - ALLOWED.keys())
    assert missing == [], (
        "a transient state with nothing that goes back and asks: register a ReconcilerSpec "
        f"next to it (JOBS_AND_INTEGRATIONS.md § 11): {missing}"
    )


def test_the_allow_list_has_no_dead_entries():
    assert sorted(ALLOWED.keys() - transient_states()) == []


def test_a_reconciler_names_a_real_model_and_real_states():
    for spec in registry.reconcilers.specs():
        model = apps.get_model(spec.model)
        values = {v for f in model._meta.concrete_fields if f.choices for v, _ in f.flatchoices}
        assert set(spec.states) <= values, f"{spec.name} covers states {model} does not have"


def test_the_outbox_lease_is_covered_by_its_recovery_sweep():
    assert ("core.OutboxMessage", "leased") in covered()
