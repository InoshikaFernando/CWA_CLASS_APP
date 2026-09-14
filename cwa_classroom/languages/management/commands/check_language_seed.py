"""
Management command: check_language_seed

Asserts that every language declared in ``languages/seed_data.py`` actually
exists in the database, with content attached. Exits non-zero and names what is
missing if not.

WHY THIS EXISTS
---------------
Seed data only reaches a server if a migration creates it. ``scripts/deploy.sh``
runs ``migrate``, ``collectstatic`` and a restart — it never runs a management
command. French, Mandarin, Japanese and Korean were added to
``seed_language_exercises`` alone, so they shipped to dev as code nothing ever
executed: migrations ran on every deploy and applied cleanly, there was simply
no migration that created the rows.

The unit suites cannot catch that. ``conftest.py`` builds the SQLite test
database straight from the models (``django_db_use_migrations`` returns False on
SQLite), so no RunPython in this repository has ever executed under pytest. CI's
Migration Health job therefore builds a database the way a deploy does — from
zero, through every migration — and then runs this command against it.

Also usable on a server to answer "did the seed data actually land?":

    sudo -u cwa /home/cwa/CWA_CLASS_APP_DEV/venv/bin/python \
        /home/cwa/CWA_CLASS_APP_DEV/cwa_classroom/manage.py check_language_seed
"""
from django.core.management.base import BaseCommand, CommandError

from languages.models import Language, LanguageExercise
from languages.seed_data import SEED, expected_exercise_count


class Command(BaseCommand):
    help = 'Verify every language in languages/seed_data.py exists in the database'

    def handle(self, *args, **options):
        expected = dict(SEED)
        present = {
            lang.code: lang
            for lang in Language.objects.filter(code__in=expected)
        }

        missing_languages = sorted(set(expected) - set(present))

        # A Language row with too few exercises is the same failure wearing a
        # disguise: the hub lists the language and its topics are short or
        # empty. Compare against what SEED declares rather than just "> 0" —
        # the MySQL collation bug migration 0011 fixes silently dropped French
        # accented letters and Sinhala lowercase vowels while leaving plenty of
        # other rows behind, so a non-zero count proved nothing.
        short_languages = {}
        for code, lang in present.items():
            actual = LanguageExercise.objects.filter(
                topic_level__topic__language=lang
            ).count()
            expected_count = expected_exercise_count(code)
            if actual < expected_count:
                short_languages[code] = (actual, expected_count)

        if missing_languages or short_languages:
            problems = []
            if missing_languages:
                problems.append(
                    'no Language row: '
                    + ', '.join(f'{code} ({expected[code]["name"]})' for code in missing_languages)
                )
            if short_languages:
                problems.append(
                    'fewer exercises than seed_data.py declares: '
                    + ', '.join(
                        f'{code} ({expected[code]["name"]}) has {actual}, expected {wanted}'
                        for code, (actual, wanted) in sorted(short_languages.items())
                    )
                )
            raise CommandError(
                'Language seed data is missing from the database — '
                + '; '.join(problems)
                + '. Seed data reaches a server only through a migration: deploy.sh '
                  'runs `migrate`, never a management command. Add a RunPython data '
                  'migration under languages/migrations/ that seeds these codes from '
                  'languages/seed_data.py (see 0014_seed_fr_zh_ja_ko.py for the shape).'
            )

        total_exercises = LanguageExercise.objects.filter(
            topic_level__topic__language__code__in=expected
        ).count()
        self.stdout.write(self.style.SUCCESS(
            f'All {len(expected)} seeded languages present '
            f'({", ".join(sorted(expected))}) with {total_exercises} exercises.'
        ))
