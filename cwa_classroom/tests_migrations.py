"""Migration health.

These run against the migration files on disk, which needs saying out loud:
pytest-django is configured to build the SQLite test database straight from the
models (``django_db_use_migrations`` in conftest.py), and it does that by
replacing ``MIGRATION_MODULES`` with a mapping that reports every app as having
no migrations at all. Under that mapping ``MigrationLoader`` loads nothing, so
``detect_conflicts()`` returns ``{}`` and ``makemigrations --check`` sees no
apps — both checks pass no matter what is on disk.

That is not hypothetical. It is how classroom acquired two leaf nodes
(0108_merge_20260626_1129 and 0117_school_free_ai_grading) with CI green the
whole way, until the test-site deploy ran a real `migrate` and stopped dead.

``override_settings(MIGRATION_MODULES={})`` puts the real discovery back for the
duration of each check, which is the only reason they test anything.
"""

from io import StringIO

from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, override_settings


@override_settings(MIGRATION_MODULES={})
class MigrationHealthTests(TestCase):

    def test_migration_files_are_actually_loaded(self):
        """The guard on the guard: prove the override defeated the disabling.

        Without this, both checks below silently degrade to no-ops again the
        next time the test-database setup changes — which is exactly the
        failure this module exists to prevent.
        """
        loader = MigrationLoader(None, ignore_no_migrations=True)
        assert loader.disk_migrations, (
            "MigrationLoader found no migration files at all. MIGRATION_MODULES "
            "is still disabling them, so every check in this file is vacuous."
        )

    def test_no_conflicting_leaf_nodes(self):
        loader = MigrationLoader(None, ignore_no_migrations=True)
        conflicts = loader.detect_conflicts()
        assert not conflicts, (
            f"Conflicting migrations detected: {conflicts}. "
            f"Run 'python manage.py makemigrations --merge' or delete the redundant file."
        )

    def test_no_missing_migrations(self):
        out = StringIO()
        call_command("makemigrations", "--check", "--dry-run", stdout=out, stderr=StringIO())
