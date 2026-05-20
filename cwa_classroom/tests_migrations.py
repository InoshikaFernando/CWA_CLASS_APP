from io import StringIO

from django.core.management import call_command
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase


class MigrationHealthTests(TestCase):

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
