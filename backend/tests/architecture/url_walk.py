"""
Walk Django's URL resolver and turn every route into a concrete path a test client can call.

A route this cannot render raises instead of being skipped. A walker that silently drops what it
does not understand is how an enforcement test ends up enforcing nothing.
"""

import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass

from django.urls import URLResolver, get_resolver
from django.urls.resolvers import RegexPattern, RoutePattern

# One sample value per path converter. A new converter needs an entry here.
SAMPLES = {
    "int": "1",
    "str": "sample",
    "slug": "sample",
    "path": "sample",
    "uuid": str(uuid.UUID(int=1)),
}

ROUTE_PARAM = re.compile(r"<(?:(?P<converter>\w+):)?(?P<name>\w+)>")
REGEX_GROUP = re.compile(r"\(\?P<(?P<name>\w+)>[^)]*\)")
REGEX_LEFTOVER = re.compile(r"[()\[\]*+?|{}\\]")


@dataclass(frozen=True)
class Route:
    path: str
    name: str | None  # namespaced, e.g. "core:health"

    def __str__(self) -> str:
        return f"{self.path} [{self.name or 'unnamed'}]"


def iter_routes(urlconf=None) -> Iterator[Route]:
    yield from _walk(get_resolver(urlconf).url_patterns, prefix="", namespace=None)


def _walk(patterns, prefix: str, namespace: str | None) -> Iterator[Route]:
    for entry in patterns:
        part = _render(entry.pattern)
        if isinstance(entry, URLResolver):
            ns = namespace
            if entry.namespace:
                ns = f"{namespace}:{entry.namespace}" if namespace else entry.namespace
            yield from _walk(entry.url_patterns, prefix + part, ns)
        else:
            name = entry.name and (f"{namespace}:{entry.name}" if namespace else entry.name)
            yield Route("/" + prefix + part, name)


def _render(pattern) -> str:
    if isinstance(pattern, RoutePattern):
        return ROUTE_PARAM.sub(_route_sample, str(pattern))
    if isinstance(pattern, RegexPattern):
        text = pattern.regex.pattern.lstrip("^").rstrip("$")
        text = REGEX_GROUP.sub(lambda m: "json" if m["name"] == "format" else "1", text)
        text = text.replace(r"\.", ".").replace("/?", "/")
        if REGEX_LEFTOVER.search(text):
            raise ValueError(f"cannot render regex route {pattern.regex.pattern!r}; teach url_walk")
        return text
    raise ValueError(f"unknown URL pattern type {type(pattern).__name__}; teach url_walk")


def _route_sample(match: re.Match) -> str:
    converter = match["converter"] or "str"
    if converter not in SAMPLES:
        raise ValueError(f"no sample value for path converter {converter!r}; add one to SAMPLES")
    return SAMPLES[converter]
