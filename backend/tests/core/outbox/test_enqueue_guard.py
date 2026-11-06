"""No database marker on purpose: outside a test transaction there is no atomic block, which is
exactly the state outbox.enqueue() must refuse (JOBS_AND_INTEGRATIONS.md § 12)."""

import pytest

from core.outbox import enqueue


def test_enqueue_outside_a_transaction_raises(topics):
    with pytest.raises(RuntimeError, match="inside the business change"):
        enqueue("tests.email", dedupe_key="k", topics=topics)
