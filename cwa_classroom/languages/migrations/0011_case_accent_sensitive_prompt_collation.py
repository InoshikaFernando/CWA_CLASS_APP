"""
Fix: MySQL's default collation (utf8mb4_unicode_ci) is both case- AND
accent-insensitive, so LanguageExercise.prompt / LanguageAnswer.answer_text
lookups (used throughout seed_language_exercises.py's get_or_create calls)
silently treat 'A' == 'a' and 'e' == 'é' == 'è' == 'ê' == 'ë' as duplicates.
This has already caused two real data gaps: Sinhala vowels missing their
lowercase forms (case), and French accented letters missing 3 of 4 'e'
variants, 1 of 2 'a'/'i' variants, and 2 of 3 'u' variants (accent).

Switches both columns to utf8mb4_bin (a plain byte-for-byte comparison —
case- and accent-sensitive) on MySQL. SQLite's default TEXT/VARCHAR
comparison is already binary (case/accent-sensitive) unless a column
explicitly opts into COLLATE NOCASE, which these never did, so there's
nothing to fix there — this migration is a no-op on any non-MySQL backend.

Schema-only: deliberately doesn't touch the model fields' Python
definitions (no db_collation on the TextField/CharField) since Django's
db_collation values aren't portable between MySQL and SQLite, and the
project's tests run against SQLite where the fix isn't needed anyway.
"""
from django.db import migrations


def _set_binary_collation(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE languages_languageexercise "
            "MODIFY prompt LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE languages_languageanswer "
            "MODIFY answer_text VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_bin NOT NULL"
        )


def _restore_unicode_ci_collation(apps, schema_editor):
    if schema_editor.connection.vendor != 'mysql':
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(
            "ALTER TABLE languages_languageexercise "
            "MODIFY prompt LONGTEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL"
        )
        cursor.execute(
            "ALTER TABLE languages_languageanswer "
            "MODIFY answer_text VARCHAR(500) CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci NOT NULL"
        )


class Migration(migrations.Migration):

    dependencies = [
        ('languages', '0010_seed_language_exercises'),
    ]

    operations = [
        migrations.RunPython(_set_binary_collation, _restore_unicode_ci_collation),
    ]
