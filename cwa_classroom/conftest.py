"""
Root conftest for pytest (Playwright UI tests).

Forces SQLite for UI tests by default. Set DB_ENGINE=mysql before running
to use MySQL instead.
"""
import os

import pytest


# Set DB_ENGINE before Django settings load (conftest.py is loaded first)
if "DB_ENGINE" not in os.environ:
    os.environ["DB_ENGINE"] = "sqlite"
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


@pytest.fixture(scope="session")
def django_db_modify_db_settings():
    """Adjust DB settings for the test session."""
    from django.conf import settings

    # Remove legacy DB if present — avoids test DB creation issues
    settings.DATABASES.pop("legacy_cwa_school", None)
    settings.DATABASES.pop("cwa_school_legacy", None)

    engine = os.environ.get("DB_ENGINE", "sqlite")

    if engine == "sqlite":
        # SQLite: use in-memory
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
