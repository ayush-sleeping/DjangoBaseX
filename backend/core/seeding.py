"""
The demo-seeder contract (BUILD_ORDER 9.6; ENGINEERING_PRACTICES § 9).

An app that wants demo data adds `<app>/demo.py` exposing `seed(stdout) -> SeedResult`.
`manage.py seed_demo` discovers it, runs the apps in INSTALLED_APPS order, and tallies the results.
A seeder recognises its own rows by a natural key, creates through the app's services, and so can
reach only states the product can reach. Synthetic data only: reserved `.test` addresses.
"""

from dataclasses import dataclass

DEMO_DOMAIN = "example.test"  # reserved by RFC 2606: it can never be a real person's mailbox


@dataclass
class SeedResult:
    created: int = 0
    skipped: int = 0  # the row already existed: a second run lands here
