"""
Every /api/ route refuses an anonymous caller (AUTH_BLUEPRINT.md § 9.3, BUILD_ORDER 2.2).

Each route is called unauthenticated with every method. Anything but 401/403 fails, and a 404
fails too, because it means the handler looked something up before checking who was asking.
The only exemptions are core.routes.PUBLIC_ROUTES, each with a written reason.
"""

import pytest
from django.test import override_settings

from core.routes import PUBLIC_ROUTES
from tests.architecture.url_walk import Route, iter_routes

METHODS = ("get", "post", "put", "patch", "delete")
REFUSED = {401, 403}


def api_routes(urlconf=None) -> list[Route]:
    return [r for r in iter_routes(urlconf) if r.path.startswith("/api/")]


def unenforced(client, routes: list[Route]) -> list[str]:
    problems = []
    for route in routes:
        for method in METHODS:
            status = getattr(client, method)(route.path).status_code
            if status in REFUSED:
                continue
            hint = ""
            if status == 404:
                hint = " (404: the handler looked something up before checking who was asking)"
            problems.append(f"{method.upper()} {route} -> {status}{hint}")
    return problems


def failure_message(problems: list[str]) -> str:
    return (
        "these routes answer an anonymous caller with something other than 401/403:\n  "
        + "\n  ".join(problems)
        + "\nGate the view, or argue for an entry in core/routes.py PUBLIC_ROUTES."
    )


@pytest.mark.django_db
def test_every_api_route_refuses_anonymous_callers(client):
    protected = [r for r in api_routes() if r.name not in PUBLIC_ROUTES]
    problems = unenforced(client, protected)
    assert not problems, failure_message(problems)


def test_the_walk_found_the_api():
    # Guards against a walker that silently finds nothing and so passes everything.
    names = {r.name for r in api_routes()}
    assert "core:health" in names, f"the URL walk did not find core:health; it found {names}"


# --- The checker itself, against routes whose answer is known ----------------------------------


@pytest.mark.django_db
@override_settings(ROOT_URLCONF="tests.architecture.fake_urls")
def test_checker_flags_open_and_lookup_first_views_and_passes_a_gated_one(client):
    problems = unenforced(client, api_routes("tests.architecture.fake_urls"))
    flagged = {p.split(" [")[0].split(" ", 1)[1] for p in problems}

    assert "/api/open/" in flagged
    assert any(p.startswith("GET /api/lookup-first/") and "404:" in p for p in problems)
    assert not any("/api/gated/" in p for p in problems), problems
