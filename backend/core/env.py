"""
APP_ENV: the one environment classification (CONFIGURATION.md § 4).

Fail closed. Only an allow-list of non-production values is non-production; anything else (a typo,
a capital letter, a new label, an empty string, unset) is production-like and gets production's
refusals. `is_production_like()` is the ONLY environment test in the codebase: never DEBUG, never
`APP_ENV == "..."`, never a hostname.

Imports nothing that needs the app registry: settings import calls into this module.
"""

from typing import TypedDict

# A new NON-production label is a reviewed code change, never an env value: an env value could
# weaken every check at once.
NON_PRODUCTION = frozenset({"development", "local", "test", "ci"})

# Ribbon tones, quietest to loudest. The frontend maps each to a colour.
TONE_STAGING = "staging"
TONE_DEV = "dev"
TONE_LOUD = "loud"


class EnvironmentLabel(TypedDict):
    label: str | None
    tone: str | None


def normalise(app_env: object) -> str:
    """'  Production ' → 'production'. None, and anything that is not a string, → ''."""
    return app_env.strip().lower() if isinstance(app_env, str) else ""


def is_production_like(app_env: str | None = None) -> bool:
    """
    True unless APP_ENV is exactly one of NON_PRODUCTION after normalising.

    With no argument it reads settings.APP_ENV. Code running DURING settings import must pass the
    value explicitly (`is_production_like(ns.get("APP_ENV") or "")`): settings are not ready yet.
    """
    if app_env is None:
        from django.conf import settings

        app_env = getattr(settings, "APP_ENV", None)
    return normalise(app_env) not in NON_PRODUCTION


def environment_label(app_env: str | None) -> EnvironmentLabel:
    """
    What the environment ribbon shows (§ 4). Labelling is not classification: an unknown value is
    secured like production AND labelled louder than anything, because not knowing which
    environment you are on is exactly when a warning is worth most.
    """
    value = normalise(app_env)
    if value == "production":
        return {"label": None, "tone": None}
    if value == "staging":
        return {"label": "Staging", "tone": TONE_STAGING}
    if value in {"development", "local"}:
        return {"label": "Development", "tone": TONE_DEV}
    if value in {"test", "ci"}:
        return {"label": "Test", "tone": TONE_DEV}
    return {"label": "Unknown environment: set APP_ENV", "tone": TONE_LOUD}
