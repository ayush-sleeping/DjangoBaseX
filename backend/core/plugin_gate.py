"""
Route-level soft-disable (EXTENSIBILITY § 15). config/urls.py mounts every registered urlconf
through gated_include(): each view in it first asks registry.plugin_state whether its owner is
enabled, and a disabled plugin's route answers 403 `plugin_disabled`. 403, not 404: a disabled
feature is "not permitted now", not "does not exist", and the route-enforcement test accepts only
401/403 from a route it calls signed out. The gate wraps the callback at mount time, so it covers
any prefix and every view style and needs no middleware entry in settings.
"""

import functools
import importlib

from django.http import JsonResponse
from django.urls import URLPattern, URLResolver

from .registry import plugin_state


def _wrap(view, owner: str):
    @functools.wraps(view)  # keeps .cls, .view_class, csrf_exempt: schema and checks read them
    def gated(request, *args, **kwargs):
        if not plugin_state.owner_enabled(owner):
            return JsonResponse(
                {
                    "error": {
                        "code": "plugin_disabled",
                        "message": "This feature is switched off.",
                    }
                },
                status=403,
            )
        return view(request, *args, **kwargs)

    return gated


def _gate(patterns, owner: str) -> list:
    gated = []
    for entry in patterns:
        if isinstance(entry, URLResolver):
            gated.append(
                URLResolver(
                    entry.pattern,
                    _gate(entry.url_patterns, owner),
                    entry.default_kwargs,
                    entry.app_name,
                    entry.namespace,
                )
            )
        else:
            assert isinstance(entry, URLPattern)
            gated.append(
                URLPattern(
                    entry.pattern, _wrap(entry.callback, owner), entry.default_args, entry.name
                )
            )
    return gated


def gated_include(urlconf: str, owner: str):
    """include(urlconf), with every view answering 403 while `owner` (the registering module) is a
    soft-disabled plugin. A platform owner is never gated."""
    module = importlib.import_module(urlconf)
    return include_args(module, owner)


def include_args(module, owner: str):
    patterns = _gate(module.urlpatterns, owner)
    return (patterns, getattr(module, "app_name", None))
