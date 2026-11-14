"""
The shared list pipeline (API_PLATFORM.md § 1): one place that turns query parameters into an
ordered, filtered queryset for every BaseViewSet list.

- An unknown query parameter is a 400, never silently ignored: a typo'd filter must not return
  everything while looking like success.
- `ordering` accepts only the view's declared `ordering_fields`; anything else is a 400.
- The primary key is ALWAYS the last ordering term. Without it a sort on a non-unique column lets
  the database return ties in any order, so a row repeats on page 2 and another appears on no page.
"""

from django.core.exceptions import ValidationError as DjangoValidationError

from core.api.error_codes import ApiError

BASE_PARAMS = frozenset({"page", "search", "ordering"})
_TRUE, _FALSE = {"true", "1"}, {"false", "0"}


def _term_name(term) -> str:
    return term.lstrip("-") if isinstance(term, str) else ""


def with_pk_tiebreak(queryset, terms: list):
    """Append pk (same direction as the first term) unless the ordering already ends unique."""
    if any(_term_name(t) in {"pk", "id"} for t in terms):
        return queryset.order_by(*terms)
    first = terms[0] if terms and isinstance(terms[0], str) else ""
    return queryset.order_by(*terms, "-pk" if first.startswith("-") else "pk")


def parse_ordering(raw: str, allowed: tuple[str, ...]) -> list[str]:
    terms = [t.strip() for t in raw.split(",") if t.strip()]
    bad = [t for t in terms if t.lstrip("-") not in allowed]
    if not terms or bad:
        raise ApiError(
            "unknown_parameter",
            "Unknown ordering field.",
            {"ordering": bad or [raw], "allowed": sorted(allowed)},
        )
    return terms


def _coerce(model, field_name: str, raw: str):
    field = model._meta.get_field(field_name)
    if field.get_internal_type() == "BooleanField":
        value = raw.lower()
        if value in _TRUE:
            return True
        if value in _FALSE:
            return False
        raise ApiError("validation_error", details={field_name: ["Use true or false."]})
    try:
        return field.to_python(raw)
    except DjangoValidationError as exc:
        raise ApiError("validation_error", details={field_name: exc.messages}) from exc


def run_list(queryset, view, params):
    allowed = BASE_PARAMS | set(view.filterset_fields) | set(view.accepted_params)
    unknown = sorted(set(params) - allowed)
    if unknown:
        raise ApiError(
            "unknown_parameter",
            "Unknown query parameter.",
            {"parameters": unknown, "allowed": sorted(allowed)},
        )
    for name in view.filterset_fields:
        if name in params:
            queryset = queryset.filter(**{name: _coerce(queryset.model, name, params[name])})
    if params.get("ordering"):
        terms = parse_ordering(params["ordering"], tuple(view.ordering_fields))
    else:
        terms = list(queryset.query.order_by or queryset.model._meta.ordering)
    return with_pk_tiebreak(queryset, terms) if terms else queryset.order_by("pk")
