"""
Unit tests for CPP-309: Languages app — models, plugin, and data migration.
"""

import pytest
from django.db import IntegrityError
from django.test import TestCase

from languages.models import (
    Language,
    LanguageAnswer,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_language(name='TestLang', code='xx', script='latin'):
    return Language.objects.create(name=name, code=code, script_type=script)


def _make_topic(language, name='Alphabet'):
    return LanguageTopic.objects.create(language=language, name=name)


def _make_level(topic, level=LanguageTopicLevel.BEGINNER):
    return LanguageTopicLevel.objects.create(topic=topic, level_choice=level)


def _make_exercise(topic_level, exercise_type=LanguageExercise.PHONICS_MCQ, prompt='Pick the sound'):
    return LanguageExercise.objects.create(
        topic_level=topic_level, exercise_type=exercise_type, prompt=prompt, points=1,
    )


def _make_answer(exercise, text, correct=False):
    return LanguageAnswer.objects.create(exercise=exercise, answer_text=text, is_correct=correct)


# ---------------------------------------------------------------------------
# Language model
# ---------------------------------------------------------------------------

class LanguageModelTests(TestCase):

    def test_create_and_str(self):
        lang = _make_language()
        assert str(lang) == 'TestLang'

    def test_code_unique(self):
        _make_language(code='xx')
        with self.assertRaises(IntegrityError):
            _make_language(code='xx', name='Duplicate')

    def test_script_type_choices(self):
        for code, script in [('xsi', 'sinhala'), ('xta', 'tamil'), ('xhi', 'devanagari')]:
            lang = Language.objects.create(name=code, code=code, script_type=script)
            assert lang.script_type == script

    def test_ordering(self):
        Language.objects.create(name='ZZZ', code='zzz', order=998)
        Language.objects.create(name='ZZA', code='zza', order=997)
        # Both have higher order than seeded records (max order=3), so filter to just these
        custom = list(Language.objects.filter(code__in=['zzz', 'zza']).order_by('order'))
        assert custom[0].code == 'zza'
        assert custom[1].code == 'zzz'


# ---------------------------------------------------------------------------
# LanguageTopic model
# ---------------------------------------------------------------------------

class LanguageTopicTests(TestCase):

    def setUp(self):
        self.lang = _make_language()

    def test_create_and_str(self):
        topic = _make_topic(self.lang, 'Vowels')
        assert 'TestLang' in str(topic)
        assert 'Vowels' in str(topic)

    def test_ordering_by_order_field(self):
        LanguageTopic.objects.create(language=self.lang, name='Z Topic', order=10)
        LanguageTopic.objects.create(language=self.lang, name='A Topic', order=1)
        topics = list(LanguageTopic.objects.filter(language=self.lang))
        assert topics[0].name == 'A Topic'


# ---------------------------------------------------------------------------
# LanguageTopicLevel model
# ---------------------------------------------------------------------------

class LanguageTopicLevelTests(TestCase):

    def setUp(self):
        lang = _make_language()
        self.topic = _make_topic(lang)

    def test_create_beginner(self):
        level = _make_level(self.topic, LanguageTopicLevel.BEGINNER)
        assert level.level_choice == 'beginner'

    def test_unique_together_enforced(self):
        _make_level(self.topic, LanguageTopicLevel.BEGINNER)
        with self.assertRaises(IntegrityError):
            _make_level(self.topic, LanguageTopicLevel.BEGINNER)

    def test_str_contains_level_display(self):
        level = _make_level(self.topic, LanguageTopicLevel.INTERMEDIATE)
        assert 'Intermediate' in str(level)


# ---------------------------------------------------------------------------
# LanguageExercise model
# ---------------------------------------------------------------------------

class LanguageExerciseTests(TestCase):

    def setUp(self):
        lang = _make_language()
        topic = _make_topic(lang)
        self.level = _make_level(topic)

    def test_all_exercise_types_valid(self):
        valid_types = [t[0] for t in LanguageExercise.EXERCISE_TYPES]
        for ex_type in valid_types:
            ex = LanguageExercise.objects.create(
                topic_level=self.level,
                exercise_type=ex_type,
                prompt=f'Test {ex_type}',
                points=2,
            )
            assert ex.pk is not None

    def test_str_contains_type_and_prompt(self):
        ex = _make_exercise(self.level, prompt='What sound does A make?')
        assert 'Phonics' in str(ex)
        assert 'What sound' in str(ex)

    def test_default_points_is_one(self):
        ex = _make_exercise(self.level)
        assert ex.points == 1


# ---------------------------------------------------------------------------
# LanguageStudentAnswer model
# ---------------------------------------------------------------------------

class LanguageStudentAnswerTests(TestCase):

    def setUp(self):
        from accounts.models import CustomUser
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        self.exercise = _make_exercise(level)
        self.student = CustomUser.objects.create_user(
            username='langstudent', email='ls@test.com', password='pass',
        )

    def test_create_student_answer(self):
        ans = LanguageStudentAnswer.objects.create(
            student=self.student, exercise=self.exercise, is_correct=True, points_earned=1,
        )
        assert ans.pk is not None
        assert 'langstudent' in str(ans)

    def test_unique_together_student_exercise(self):
        LanguageStudentAnswer.objects.create(
            student=self.student, exercise=self.exercise,
        )
        with self.assertRaises(IntegrityError):
            LanguageStudentAnswer.objects.create(
                student=self.student, exercise=self.exercise,
            )


# ---------------------------------------------------------------------------
# LanguagesPlugin
# ---------------------------------------------------------------------------

class LanguagesPluginTests(TestCase):

    def _plugin(self):
        from classroom.subject_registry import get
        return get('languages')

    def test_plugin_registered_under_slug(self):
        plugin = self._plugin()
        assert plugin is not None
        assert plugin.slug == 'languages'
        assert plugin.display_name == 'Languages'
        assert plugin.supports_homework is True

    def test_has_content_false_when_no_exercises(self):
        plugin = self._plugin()
        assert plugin.has_content() is False

    def test_has_content_true_when_exercise_exists(self):
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        _make_exercise(level)
        plugin = self._plugin()
        assert plugin.has_content() is True

    def test_grade_answer_phonics_mcq_correct(self):
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        ex = _make_exercise(level, exercise_type=LanguageExercise.PHONICS_MCQ)
        _make_answer(ex, 'B', correct=False)
        right = _make_answer(ex, 'A', correct=True)

        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': str(right.pk)})
        assert result['is_correct'] is True
        assert result['points_earned'] == 1

    def test_grade_answer_phonics_mcq_wrong(self):
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        ex = _make_exercise(level, exercise_type=LanguageExercise.PHONICS_MCQ)
        wrong = _make_answer(ex, 'B', correct=False)
        _make_answer(ex, 'A', correct=True)

        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': str(wrong.pk)})
        assert result['is_correct'] is False
        assert result['points_earned'] == 0

    def test_grade_answer_letter_writing_with_strokes(self):
        import json
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        ex = _make_exercise(level, exercise_type=LanguageExercise.LETTER_WRITING, prompt='A')

        stroke_payload = {'version': '5.3.1', 'objects': [{'type': 'path'}]}
        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {'stroke_data': json.dumps(stroke_payload)})

        assert result['is_correct'] is True
        assert result['points_earned'] == ex.points
        assert result['answer_data']['stroke_data'] == stroke_payload

    def test_grade_answer_letter_writing_empty_canvas(self):
        import json
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        ex = _make_exercise(level, exercise_type=LanguageExercise.LETTER_WRITING, prompt='A')

        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {'stroke_data': json.dumps({'objects': []})})

        assert result['is_correct'] is False
        assert result['points_earned'] == 0

    def test_grade_answer_spelling_type_correct(self):
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        # SPELLING_TYPE grades the typed word against the exercise prompt (the
        # word to spell) — matching the standalone view's _spelling_type.
        ex = _make_exercise(level, exercise_type=LanguageExercise.SPELLING_TYPE, prompt='cat')

        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': 'CAT'})
        assert result['is_correct'] is True

    def test_grade_answer_spelling_type_wrong(self):
        lang = _make_language()
        topic = _make_topic(lang)
        level = _make_level(topic)
        ex = _make_exercise(level, exercise_type=LanguageExercise.SPELLING_TYPE, prompt='Spell cat')
        _make_answer(ex, 'cat', correct=True)

        plugin = self._plugin()
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': 'dog'})
        assert result['is_correct'] is False


# ---------------------------------------------------------------------------
# Data migration: seeded records
# ---------------------------------------------------------------------------

class DataMigrationTests(TestCase):

    def setUp(self):
        # On SQLite the test DB is built directly from models with migrations
        # skipped (see conftest.django_db_use_migrations), so the data migration
        # that seeds the Languages subject + base languages never runs. Invoke
        # its seed function directly so these tests verify the seeding logic in
        # any DB mode — get_or_create is idempotent, so it's a no-op when the
        # migration already ran (MySQL).
        from importlib import import_module
        from django.apps import apps as global_apps
        seed = import_module(
            'classroom.migrations.0101_seed_languages_subject'
        ).seed_data
        seed(global_apps, None)

    def test_subject_languages_seeded(self):
        from classroom.models import Subject
        assert Subject.objects.filter(slug='languages').exists()

    def test_initial_languages_seeded(self):
        assert Language.objects.filter(code='en').exists()
        assert Language.objects.filter(code='si').exists()
        assert Language.objects.filter(code='ta').exists()

    def test_english_is_latin_script(self):
        lang = Language.objects.get(code='en')
        assert lang.script_type == 'latin'

    def test_sinhala_script_type(self):
        lang = Language.objects.get(code='si')
        assert lang.script_type == 'sinhala'
