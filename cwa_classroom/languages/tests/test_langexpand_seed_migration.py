# -*- coding: utf-8 -*-
"""
Tests for the seed-data → migration contract (CPP-392/393 follow-up).

THE BUG THESE EXIST FOR
-----------------------
French, Mandarin, Japanese and Korean were added to the
``seed_language_exercises`` management command and to nothing else. Servers
never run management commands — ``scripts/deploy.sh`` runs ``migrate``,
``collectstatic`` and a restart — so the four languages shipped to dev as code
that nothing executed. Migrations ran fine on every deploy and applied cleanly;
migrations 0012/0013 even widened ``script_type`` to accept cjk/kana/hangul. The
``Language`` rows were simply never created, and the hub kept showing
English/Sinhala/Tamil. It read like "the deploy didn't migrate", which sent the
investigation in the wrong direction entirely.

WHY THE MIGRATION BODY IS CALLED DIRECTLY HERE
----------------------------------------------
``conftest.py`` builds the SQLite test database straight from the models
(``django_db_use_migrations`` returns False on SQLite), so no RunPython in this
repository has ever executed under pytest. Calling 0014's function against the
real models is the closest a SQLite suite can get to running the migration. It
covers the seeding LOGIC. It cannot prove the migration graph applies from zero
on the real backend, which is what CI's "Fresh-database migrate" job does
against MySQL — the two halves are complementary, and neither replaces the
other.
"""
import importlib
import inspect

import pytest
from django.apps import apps as django_apps
from django.core.management import call_command
from django.core.management.base import CommandError

from languages import seed_data
from languages.management.commands import seed_language_exercises
from languages.models import (
    Language, LanguageExercise, LanguageTopic, LanguageTopicLevel,
)
from languages.seed_data import SEED, expected_exercise_count

pytestmark = pytest.mark.langexpand

_MIGRATION_0010 = importlib.import_module('languages.migrations.0010_seed_language_exercises')
_MIGRATION_0014 = importlib.import_module('languages.migrations.0014_seed_all_languages')


# ---------------------------------------------------------------------------
# The contract: one seed source, reachable from a migration
# ---------------------------------------------------------------------------

def test_command_and_migration_read_the_same_seed_source():
    """Separate copies are what let the two drift apart in the first place."""
    assert seed_language_exercises.SEED is seed_data.SEED, (
        'seed_language_exercises no longer reads languages/seed_data.py. Once '
        'the command owns its own copy, a language can be added to it without '
        'any migration ever creating that language on a server.')
    assert _MIGRATION_0014.SEED is seed_data.SEED, (
        '0014 no longer reads languages/seed_data.py, so the migration and the '
        'command can disagree about what a language contains.')


def test_the_migration_seeds_every_language_not_a_hardcoded_subset():
    """0014 iterates SEED itself, so a language added to seed_data.py is
    carried to every server by the next deploy without anyone remembering to
    extend a list. A subset here is how fr/zh/ja/ko went missing."""
    source = inspect.getsource(_MIGRATION_0014.seed_all_languages)
    assert 'SEED.items()' in source, (
        'Migration 0014 no longer iterates all of seed_data.SEED. If it seeds a '
        'hardcoded subset, a language added to seed_data.py exists only for '
        'whoever runs `manage.py seed_language_exercises` by hand — deploy.sh '
        'never does.')


# ---------------------------------------------------------------------------
# 0014's RunPython body, against the real models
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestMigration0014SeedsEveryLanguage:

    def test_it_creates_every_language_with_the_right_script(self):
        _MIGRATION_0014.seed_all_languages(django_apps, None)

        created = {lang.code: lang for lang in Language.objects.all()}
        assert set(created) == set(SEED)
        for code in SEED:
            assert created[code].name == SEED[code]['name']
            assert created[code].script_type == SEED[code]['script_type']
            assert created[code].is_active is True

    def test_it_creates_the_exercises_not_just_the_language_row(self):
        _MIGRATION_0014.seed_all_languages(django_apps, None)

        for code in SEED:
            count = LanguageExercise.objects.filter(
                topic_level__topic__language__code=code).count()
            assert count == expected_exercise_count(code), (
                f'{code}: seeded {count} exercises, SEED declares '
                f'{expected_exercise_count(code)}')

    def test_a_multi_level_topic_is_one_topic_with_several_levels(self):
        """French 'Alphabet' / Japanese 'ひらがな' appear at two levels each.

        Topics key on (language, name), so a second level-entry must attach a
        LanguageTopicLevel to the existing topic rather than duplicate it.
        """
        _MIGRATION_0014.seed_all_languages(django_apps, None)

        for code in SEED:
            distinct_names = {t['name'] for t in SEED[code]['topics']}
            assert LanguageTopic.objects.filter(
                language__code=code).count() == len(distinct_names)

        alphabet = LanguageTopic.objects.get(language__code='fr', name='Alphabet')
        assert set(alphabet.levels.values_list('level_choice', flat=True)) == {
            'beginner', 'intermediate'}

    def test_phonics_answers_are_deterministic_and_have_one_correct(self):
        _MIGRATION_0014.seed_all_languages(django_apps, None)

        topic = SEED['ko']['topics'][0]
        prompt, wrong = topic['phonics_mcq'][0]
        exercise = LanguageExercise.objects.get(
            topic_level__topic__language__code='ko',
            exercise_type='phonics_mcq',
            prompt=prompt,
        )
        answers = list(exercise.answers.order_by('display_order'))
        # Fixed order, correct answer first — the frontend shuffles at render
        # time. This is deliberately unlike the management command, which
        # shuffles at write time.
        assert [a.answer_text for a in answers] == [prompt] + list(wrong)
        assert [a.is_correct for a in answers] == [True, False, False, False]

    def test_it_is_idempotent(self):
        """Deploys re-run migrations on databases where someone already ran the
        management command by hand to unblock themselves."""
        _MIGRATION_0014.seed_all_languages(django_apps, None)
        first = (Language.objects.count(), LanguageExercise.objects.count())

        _MIGRATION_0014.seed_all_languages(django_apps, None)
        assert (Language.objects.count(), LanguageExercise.objects.count()) == first

    def test_it_tops_up_the_languages_0010_already_seeded(self):
        """The quiet half of the bug.

        0010 froze en/si/ta in June; the content added to them afterwards went
        only into the management command. A database that has applied 0010 and
        nothing else is short an English 'Vowels (intermediate)' topic, a
        Sinhala 'Consonants (advanced)' topic and seven whole Tamil topics. 0014
        has to close that gap, not just add the four new languages.
        """
        _MIGRATION_0010.seed_exercises(django_apps, None)
        for code in ('en', 'si', 'ta'):
            before = LanguageExercise.objects.filter(
                topic_level__topic__language__code=code).count()
            assert before < expected_exercise_count(code), (
                f'{code}: 0010 alone already matches seed_data, so this test no '
                f'longer proves 0014 tops anything up')

        _MIGRATION_0014.seed_all_languages(django_apps, None)

        for code in ('en', 'si', 'ta'):
            after = LanguageExercise.objects.filter(
                topic_level__topic__language__code=code).count()
            # ">=" not "==": 0010 also wrote a handful of prompts the live SEED
            # has since dropped, and 0014 has no business deleting them.
            assert after >= expected_exercise_count(code)

        # The seven Tamil topics that no server has ever had must now exist by
        # name (0010 also left two topics behind that the live SEED dropped, so
        # this checks presence rather than a total).
        seeded_tamil = set(
            LanguageTopic.objects.filter(language__code='ta')
            .values_list('name', flat=True))
        assert seeded_tamil >= {t['name'] for t in SEED['ta']['topics']}
        assert 'குறில் எழுத்துகள் (Short Vowels)' in seeded_tamil

        # ...and English's 'Vowels' must now carry its intermediate level.
        assert LanguageTopicLevel.objects.filter(
            topic__language__code='en', topic__name='Vowels',
            level_choice='intermediate').exists()

    def test_it_does_not_disturb_rows_0010_already_wrote(self):
        _MIGRATION_0010.seed_exercises(django_apps, None)
        existing = dict(
            LanguageExercise.objects
            .filter(topic_level__topic__language__code='en')
            .values_list('id', 'prompt')
        )

        _MIGRATION_0014.seed_all_languages(django_apps, None)

        still_there = dict(
            LanguageExercise.objects
            .filter(id__in=existing)
            .values_list('id', 'prompt')
        )
        assert still_there == existing, (
            '0014 rewrote or removed exercises 0010 had created; it must only '
            'add what is missing')


# ---------------------------------------------------------------------------
# The count the CI gate is calibrated against
# ---------------------------------------------------------------------------

@pytest.mark.django_db
def test_expected_count_matches_what_seeding_actually_writes():
    """``expected_exercise_count`` calibrates ``manage.py check_language_seed``.

    Over-count and CI's fresh-database gate is permanently red; under-count and
    it is permanently vacuous — it would have passed on the very database that
    was missing French. Run against 0014 alone on an empty database, so the
    number is measured against the live SEED exactly; a real server also
    carries rows 0010 wrote that the live SEED has since dropped, which is why
    check_language_seed asserts "at least" rather than equality.
    """
    _MIGRATION_0014.seed_all_languages(django_apps, None)

    for code in SEED:
        actual = LanguageExercise.objects.filter(
            topic_level__topic__language__code=code).count()
        assert actual == expected_exercise_count(code), (
            f'{code}: seeding wrote {actual} exercises, '
            f'expected_exercise_count() predicts {expected_exercise_count(code)}')


# ---------------------------------------------------------------------------
# The check command CI runs against a freshly migrated database
# ---------------------------------------------------------------------------

@pytest.mark.django_db
class TestCheckLanguageSeedCommand:

    def test_it_fails_loudly_on_an_unseeded_database(self):
        with pytest.raises(CommandError) as excinfo:
            call_command('check_language_seed')
        message = str(excinfo.value)
        assert 'fr' in message and 'ko' in message
        assert 'migration' in message, (
            'The failure must name the remedy — a data migration — or it sends '
            'the next person hunting the deploy script again.')

    def test_it_fails_when_a_language_row_exists_but_is_empty(self):
        """The disguised version: the hub lists the language, every topic empty."""
        _MIGRATION_0010.seed_exercises(django_apps, None)
        _MIGRATION_0014.seed_all_languages(django_apps, None)
        LanguageExercise.objects.filter(
            topic_level__topic__language__code='ja').delete()

        with pytest.raises(CommandError, match='fewer exercises'):
            call_command('check_language_seed')

    def test_it_passes_once_both_migrations_have_run(self):
        _MIGRATION_0010.seed_exercises(django_apps, None)
        _MIGRATION_0014.seed_all_languages(django_apps, None)

        call_command('check_language_seed')  # must not raise

        assert set(Language.objects.values_list('code', flat=True)) == set(SEED)
