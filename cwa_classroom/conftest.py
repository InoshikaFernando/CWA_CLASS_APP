"""
Root conftest for pytest (Playwright UI tests).

Uses whichever database settings.py configures (MySQL or SQLite).
For SQLite (DB_ENGINE=sqlite): forces in-memory DB, skips migrations.
For MySQL: uses existing test DB with --keepdb behaviour.
"""
import os

import pytest


@pytest.fixture(scope="session")
def django_db_modify_db_settings():
    """Adjust DB settings for the test session."""
    from django.conf import settings

    # Remove legacy DB if present — avoids test DB creation issues
    settings.DATABASES.pop("legacy_cwa_school", None)
    settings.DATABASES.pop("cwa_school_legacy", None)

    engine = settings.DATABASES["default"]["ENGINE"]

    if "sqlite" in engine:
        # SQLite: use in-memory, skip migrations
        settings.DATABASES["default"] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": ":memory:",
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "HOST": "",
            "PORT": "",
            "USER": "",
            "PASSWORD": "",
            "OPTIONS": {},
            "TIME_ZONE": None,
            "TEST": {
                "CHARSET": None,
                "COLLATION": None,
                "MIGRATE": False,
                "MIRROR": None,
                "NAME": ":memory:",
                "DEPENDENCIES": [],
            },
        }


@pytest.fixture(scope="session")
def django_db_use_migrations():
    """Skip migrations on SQLite (tables created from models). Run on MySQL."""
    from django.conf import settings

    engine = settings.DATABASES["default"]["ENGINE"]
    if "sqlite" in engine:
        return False
    return True
