"""Migration 0028 must run outside a transaction.

Its RunPython issues an ALTER TABLE on MySQL. Django refuses DDL from
RunPython inside a transaction on a database that cannot roll DDL back —
"Executing DDL statements while in a transaction on databases that can't
perform a rollback is prohibited" — and that is how the first deploy of this
migration failed on the test site while every SQLite suite stayed green. The
flag is the fix (as in 0020); this pins it so it cannot quietly come back.
"""
from importlib import import_module


def test_migration_0028_is_non_atomic():
    module = import_module(
        'homework.migrations.0028_reconcile_submission_score_column')
    assert module.Migration.atomic is False


def test_migration_0020_precedent_is_still_non_atomic():
    module = import_module(
        'homework.migrations.0020_repair_missing_studentanswer_review_columns')
    assert module.Migration.atomic is False
