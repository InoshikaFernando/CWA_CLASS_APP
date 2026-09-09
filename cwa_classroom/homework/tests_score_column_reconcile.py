"""Migration 0028 — reconciling the drifted ``score`` column (CPP-408).

Production holds ``homework_homeworksubmission.score`` as ``decimal(6,2)``
while the model says ``PositiveSmallIntegerField``. The migration issues an
explicit ALTER, because migration state already agrees with the model and so
Django emits no SQL of its own.

The suites run on SQLite, where the migration is a deliberate no-op, so the
MySQL behaviour is driven against a stub connection. That is the point: the
branch that matters — refusing to round somebody's mark away — only ever runs
on a database the tests never see, and would otherwise be shipped unexercised.
"""
from django.apps import apps as global_apps
from django.db import connection
from django.test import TestCase

import importlib

MIGRATION = importlib.import_module(
    'homework.migrations.0028_reconcile_submission_score_column'
)


class _FakeCursor:
    """Consumes from a queue SHARED with its connection.

    Each helper opens its own cursor, so a per-cursor copy would replay the
    first result every time and the "no fractional rows" case would read back
    the information_schema row instead of an empty list.
    """

    def __init__(self, results):
        self._results = results          # shared, deliberately not copied
        self.executed = []

    def execute(self, sql, params=None):
        self.executed.append((' '.join(sql.split()), params))

    def fetchone(self):
        return self._results.pop(0) if self._results else None

    def fetchall(self):
        return self._results.pop(0) if self._results else []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class _FakeConnection:
    """A MySQL-shaped connection: fake cursor, real backend behind it.

    Only ``vendor`` and ``cursor`` are stubbed — the two things the migration
    branches on. Everything else falls through to the live connection, because
    the migration asks ``field.db_type()`` for its target type and stubbing
    that out would replace the very derivation under test with a fixture.
    """

    def __init__(self, vendor='mysql', results=()):
        self.vendor = vendor
        self.cursors = []
        self.results = list(results)

    def cursor(self):
        cursor = _FakeCursor(self.results)
        self.cursors.append(cursor)
        return cursor

    def __getattr__(self, name):
        return getattr(connection, name)


class _FakeSchemaEditor:
    def __init__(self, connection):
        self.connection = connection
        self.statements = []

    def execute(self, sql):
        self.statements.append(' '.join(sql.split()))


class SqliteIsUntouchedTests(TestCase):
    """The suites run on SQLite; this migration must not touch it."""

    def test_forward_is_a_no_op_on_sqlite(self):
        editor = _FakeSchemaEditor(_FakeConnection(vendor='sqlite'))
        MIGRATION.align_to_model(global_apps, editor)
        self.assertEqual(editor.statements, [])

    def test_reverse_is_a_no_op_on_sqlite(self):
        editor = _FakeSchemaEditor(_FakeConnection(vendor='sqlite'))
        MIGRATION.restore_legacy_column(global_apps, editor)
        self.assertEqual(editor.statements, [])

    def test_the_real_migration_applies_cleanly_here(self):
        # The suite already ran every migration to build this database; if 0028
        # raised on SQLite nothing in this file would run at all. Asserting the
        # table is still readable states that plainly.
        from homework.models import HomeworkSubmission
        self.assertEqual(HomeworkSubmission.objects.count(), 0)


class MysqlAlterTests(TestCase):

    def test_a_drifted_column_is_altered_to_the_model_type(self):
        # information_schema says 'decimal'; no fractional rows.
        conn = _FakeConnection(results=[('decimal',), []])
        editor = _FakeSchemaEditor(conn)

        MIGRATION.align_to_model(global_apps, editor)

        self.assertEqual(len(editor.statements), 1)
        statement = editor.statements[0]
        self.assertIn('ALTER TABLE homework_homeworksubmission', statement)
        self.assertIn('MODIFY score', statement)
        self.assertIn('NOT NULL', statement)
        # Derived from the model field, not hard-coded.
        self.assertIn('smallint', statement.lower())

    def test_an_already_correct_column_is_left_alone(self):
        conn = _FakeConnection(results=[('smallint',)])
        editor = _FakeSchemaEditor(conn)

        MIGRATION.align_to_model(global_apps, editor)

        self.assertEqual(editor.statements, [],
                         're-running must cost nothing')

    def test_the_target_type_comes_from_the_model(self):
        """Hard-coding the type is how a migration drifts from its model."""
        expected = MIGRATION._target_definition(global_apps, connection)
        field = global_apps.get_model(
            'homework', 'HomeworkSubmission')._meta.get_field('score')
        self.assertIn(field.db_type(connection), expected)
        self.assertIn('NOT NULL', expected)


class RefusesToLoseDataTests(TestCase):
    """The branch that matters."""

    def test_a_fractional_score_stops_the_migration(self):
        conn = _FakeConnection(results=[('decimal',), [(41, '24.50'), (77, '9.25')]])
        editor = _FakeSchemaEditor(conn)

        with self.assertRaises(RuntimeError) as ctx:
            MIGRATION.align_to_model(global_apps, editor)

        message = str(ctx.exception)
        self.assertIn('#41 = 24.50', message)      # names the rows
        self.assertIn('#77 = 9.25', message)
        self.assertIn('Refusing', message)
        self.assertEqual(editor.statements, [],
                         'nothing may be altered once data would be lost')

    def test_no_fractional_rows_means_no_refusal(self):
        conn = _FakeConnection(results=[('decimal',), []])
        editor = _FakeSchemaEditor(conn)
        MIGRATION.align_to_model(global_apps, editor)     # does not raise
        self.assertEqual(len(editor.statements), 1)


class ReversibleTests(TestCase):

    def test_the_reverse_restores_what_production_holds_today(self):
        conn = _FakeConnection(results=[('smallint',)])
        editor = _FakeSchemaEditor(conn)

        MIGRATION.restore_legacy_column(global_apps, editor)

        self.assertEqual(len(editor.statements), 1)
        self.assertIn('decimal(6,2)', editor.statements[0])

    def test_reverse_is_idempotent(self):
        conn = _FakeConnection(results=[('decimal',)])
        editor = _FakeSchemaEditor(conn)
        MIGRATION.restore_legacy_column(global_apps, editor)
        self.assertEqual(editor.statements, [])

    def test_the_operation_declares_both_directions(self):
        """An irreversible migration cannot be rolled back on a bad deploy."""
        operation = MIGRATION.Migration.operations[0]
        self.assertTrue(operation.reversible)
