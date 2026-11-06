"""Loads the Celery app whenever Django loads `config`, so every task binds to it (ADR-0012)."""

from .celery import app as celery_app

__all__ = ["celery_app"]
