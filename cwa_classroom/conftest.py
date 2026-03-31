"""
Root conftest — forces SQLite for all pytest runs.

The project's settings.py uses ``load_dotenv(override=True)`` which
overrides env vars with the .env file.  We patch Django's DATABASES
directly after it has been initialised.
"""
import pytest


@pytest.fixture(scope="session")
def django_db_modify_db_settings():
    """Override the database to use SQLite in-memory for tests."""
    from django.conf import settings

    # Replace entirely — MySQL OPTIONS (charset, init_command) break SQLite
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
    # Remove legacy DB if present (also MySQL)
    settings.DATABASES.pop("legacy_cwa_school", None)
    settings.DATABASES.pop("cwa_school_legacy", None)


@pytest.fixture(scope="session")
def django_db_use_migrations():
    """Skip migrations — create tables from model definitions."""
    return False
