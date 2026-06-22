"""
Root conftest for pytest (Playwright UI tests).

Forces SQLite for UI tests by default. Set DB_ENGINE=mysql before running
to use MySQL instead.
"""
import os
import tempfile

import pytest


# Set DB_ENGINE before Django settings load (conftest.py is loaded first)
if "DB_ENGINE" not in os.environ:
    os.environ["DB_ENGINE"] = "sqlite"
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")


def _enable_sqlite_wal(sender, connection, **kwargs):
    """Put SQLite test connections in WAL mode + a generous busy timeout.

    WAL lets the live-server request thread read while the test body writes,
    and the busy timeout makes any remaining writer contention wait rather
    than raising ``database is locked`` (Django 4.2's sqlite backend doesn't
    accept ``init_command``, so this runs on the connection_created signal).
    """
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("PRAGMA journal_mode=WAL;")
            cursor.execute("PRAGMA busy_timeout=20000;")


# Registered lazily inside the DB-settings fixture so it only affects test runs.
_WAL_SIGNAL_CONNECTED = False


@pytest.fixture(scope="session")
def django_db_modify_db_settings():
    """Adjust DB settings for the test session.

    UI tests use ``live_server``, which serves requests from a separate thread
    than the test body. With an in-memory *shared-cache* SQLite DB those two
    connections contend on table-level locks (``SQLITE_LOCKED`` →
    ``database table is locked: django_session``), which SQLite's busy-timeout
    does NOT retry — the dominant source of UI-suite flakiness under parallel
    Playwright workers.

    Fix: give each xdist worker its own *file-based* SQLite DB in WAL mode with
    a busy timeout. File locking (unlike shared-cache) honours the busy timeout,
    so concurrent writers wait instead of erroring.
    """
    global _WAL_SIGNAL_CONNECTED
    from django.conf import settings
    from django.db.backends.signals import connection_created

    # Remove legacy DB if present — avoids test DB creation issues
    settings.DATABASES.pop("legacy_cwa_school", None)
    settings.DATABASES.pop("cwa_school_legacy", None)

    engine = os.environ.get("DB_ENGINE", "sqlite")

    if engine == "sqlite":
        if not _WAL_SIGNAL_CONNECTED:
            connection_created.connect(_enable_sqlite_wal)
            _WAL_SIGNAL_CONNECTED = True
        # Per-worker file so parallel xdist workers don't share one DB file.
        worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
        db_file = os.path.join(tempfile.gettempdir(), f"cwa_ui_test_{worker}.sqlite3")
        # Start from a clean slate each session (drop stale schema + WAL sidecars).
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(db_file + suffix)
            except OSError:
                pass

        settings.DATABASES["default"] = {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": db_file,
            "ATOMIC_REQUESTS": False,
            "AUTOCOMMIT": True,
            "CONN_MAX_AGE": 0,
            "CONN_HEALTH_CHECKS": False,
            "HOST": "",
            "PORT": "",
            "USER": "",
            "PASSWORD": "",
            # timeout → busy timeout (seconds). WAL mode is set on connect via
            # the connection_created signal (see _enable_sqlite_wal).
            "OPTIONS": {"timeout": 20},
            "TIME_ZONE": None,
            "TEST": {
                "CHARSET": None,
                "COLLATION": None,
                "MIGRATE": False,
                "MIRROR": None,
                "NAME": db_file,
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
