"""
The second product end to end (BUILD_ORDER 10.1): numbering, state machine with history, money,
scoping, soft delete and the per-action permission codes, all reached through core.sdk only.
Runs with the platform's suite (`cd backend && uv run pytest`) once the plugin is installed.
"""

import pytest
from django.test import Client

from rbac import services as rbac
from tests.factories import DEFAULT_PASSWORD, UserFactory
from users.cookies import cookie_names

pytestmark = pytest.mark.django_db

ENQUIRIES = "/api/enquiries/"
ALL = (
    "enquiries.enquiries.view",
    "enquiries.enquiries.create",
    "enquiries.enquiries.update",
    "enquiries.enquiries.transition",
    "enquiries.enquiries.delete",
)
# An obviously fake contact; the currency is test data, not a default (invariant 21).
NEW = {
    "contact_name": "Test Contact",
    "contact_email": "contact@example.test",
    "subject": "Ten widgets",
    "value_amount": "1200.5",
    "value_currency": "EUR",
}


def session(*codes):
    user = UserFactory()
    if codes:
        role = rbac.create_role(
            actor=None, name=f"r-{user.pk}", slug=f"r-{user.pk}", permission_codes=codes
        )
        rbac.assign_role(actor=None, user=user, role=role)
    client = Client()
    client.post(
        "/api/auth/login/",
        {"email": user.email, "password": DEFAULT_PASSWORD},
        content_type="application/json",
    )
    return client


def send(client, method, path, data=None):
    csrf = client.cookies.get(cookie_names().csrf)
    headers = {"HTTP_X_CSRF_TOKEN": csrf.value} if csrf is not None and csrf.value else {}
    return getattr(client, method)(path, data or {}, content_type="application/json", **headers)


def create(client, **overrides):
    response = send(client, "post", ENQUIRIES, NEW | overrides)
    assert response.status_code == 201, response.content
    return response.json()


def move(client, enquiry, to, reason=""):
    return send(
        client,
        "post",
        f"{ENQUIRIES}{enquiry['public_id']}/transition/",
        {"to": to, "reason": reason},
    )


def test_an_enquiry_gets_the_next_number_and_a_quantised_value():
    client = session(*ALL)
    first, second = create(client), create(client)

    assert first["number"].startswith("ENQ-") and first["number"].endswith("-00001")
    assert second["number"].endswith("-00002")
    assert first["value"] == {"amount": "1200.50", "currency": "EUR"}
    assert first["status"] == "new" and first["allowed_transitions"] == ["contacted", "lost"]
    assert "id" not in first  # public_id only


def test_an_unknown_currency_is_refused_with_the_error_envelope():
    response = send(session(*ALL), "post", ENQUIRIES, NEW | {"value_currency": "XXZ"})
    assert response.status_code == 400
    assert "value_currency" in response.json()["error"]["details"]


def test_the_pipeline_moves_only_along_legal_transitions():
    client = session(*ALL)
    enquiry = create(client)

    assert move(client, enquiry, "won").status_code == 409  # new -> won skips the pipeline
    for step in ("contacted", "quoted", "won"):
        response = move(client, enquiry, step)
        assert response.status_code == 200, response.content
    assert response.json()["allowed_transitions"] == []  # won is final
    assert move(client, enquiry, "lost", reason="late").status_code == 409


def test_losing_or_reopening_needs_a_reason():
    client = session(*ALL)
    enquiry = create(client)

    refused = move(client, enquiry, "lost")
    assert refused.status_code == 400 and refused.json()["error"]["code"] == "reason_required"
    assert move(client, enquiry, "lost", reason="Chose another supplier").status_code == 200
    assert move(client, enquiry, "new").status_code == 400
    assert move(client, enquiry, "new", reason="They came back").json()["status"] == "new"


def test_every_status_change_is_recorded_in_state_history():
    from core.lifecycle.models import StateTransition

    client = session(*ALL)
    enquiry = create(client)
    move(client, enquiry, "contacted")
    move(client, enquiry, "lost", reason="No budget")

    rows = list(
        StateTransition.objects.filter(object_type="enquiries.enquiry", field="status")
        .order_by("pk")
        .values_list("from_state", "to_state", "reason")
    )
    assert rows == [("new", "contacted", ""), ("contacted", "lost", "No budget")]


def test_a_person_never_sees_moves_or_deletes_someone_elses_enquiry():
    mine, theirs = session(*ALL), session(*ALL)
    enquiry = create(theirs)
    detail = f"{ENQUIRIES}{enquiry['public_id']}/"

    assert mine.get(ENQUIRIES).json()["results"] == []
    assert mine.get(detail).status_code == 404
    assert move(mine, enquiry, "contacted").status_code == 404
    assert send(mine, "delete", detail).status_code == 404


def test_each_action_needs_its_own_code():
    owner = session(*ALL)
    enquiry = create(owner)
    reader = session("enquiries.enquiries.view")

    assert reader.get(ENQUIRIES).status_code == 200
    assert send(reader, "post", ENQUIRIES, NEW).status_code == 403
    assert move(reader, enquiry, "contacted").status_code in (403, 404)
    assert session().get(ENQUIRIES).status_code == 403


def test_editing_requotes_the_value_and_deleting_bins_without_reusing_the_number():
    client = session(*ALL)
    enquiry = create(client)
    detail = f"{ENQUIRIES}{enquiry['public_id']}/"

    edited = send(client, "patch", detail, {"value_amount": "99.999"})
    assert edited.json()["value"] == {"amount": "100.00", "currency": "EUR"}

    assert send(client, "delete", detail).status_code == 204
    assert client.get(detail).status_code == 404
    assert create(client)["number"].endswith("-00002")
