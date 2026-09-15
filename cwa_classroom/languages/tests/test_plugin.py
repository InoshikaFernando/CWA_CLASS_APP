"""
Unit tests for CPP-316: LanguagesPlugin homework methods.

TestHomeworkTopicTree         — returns 3-level list with correct structure
TestTopicTreeExcludesEmpty    — levels without active exercises excluded
TestPickHomeworkItems         — returns list of exercise pks
TestPickHomeworkItemsCapsAtN  — honours n limit
TestSaveHomeworkTopics        — sets M2M on homework
TestGradeAnswerMCQ            — correct/incorrect phonics grading
TestGradeAnswerSpellingType   — NFC text comparison
TestGradeAnswerSentenceOrder  — partial credit returned
"""

import json
import pytest
from django.test import Client

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageTopic, LanguageTopicLevel,
)
from languages.plugin import LanguagesPlugin


pytestmark = pytest.mark.cpp316

plugin = LanguagesPlugin()


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_teacher(username, password='TeacherPass316!'):
    u = CustomUser.objects.create_user(
        username=username, password=password,
        first_name='Teacher', last_name='Test', email=f'{username}@test.com',
    )
    role, _ = Role.objects.get_or_create(name='teacher')
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _setup_lang(suffix=''):
    code = f'pl{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'PluginLang{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Plugin Grammar',
        defaults={'order': 0, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='beginner',
    )
    return lang, topic, level


def _make_mcq_exercise(level):
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.PHONICS_MCQ,
        prompt='test prompt',
        points=5,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='right', is_correct=True)
    wrong   = LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False)
    return ex, correct, wrong


# ===========================================================================

@pytest.mark.django_db
class TestHomeworkTopicTree:
    def test_returns_three_level_list(self):
        lang, topic, level = _setup_lang('tree')
        # Ensure there's at least one active exercise in this level
        LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='hello',
            is_active=True,
        )

        tree = plugin.homework_topic_tree(classroom=None)
        assert isinstance(tree, list)
        assert len(tree) >= 1
        # Each entry is (lang_obj, [(topic, [level, ...]), ...])
        found = False
        for l_obj, mid_items in tree:
            if l_obj.code == lang.code:
                for t_obj, leaves in mid_items:
                    if t_obj.pk == topic.pk:
                        assert any(lv.pk == level.pk for lv in leaves)
                        found = True
        assert found, 'Created language/topic/level not found in tree'

    def test_level_name_property_available(self):
        _, _, level = _setup_lang('name')
        LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='hi',
            is_active=True,
        )
        tree = plugin.homework_topic_tree(classroom=None)
        for _, mid_items in tree:
            for _, leaves in mid_items:
                for lv in leaves:
                    assert hasattr(lv, 'name')
                    assert lv.name  # non-empty


@pytest.mark.django_db
class TestTopicTreeExcludesEmpty:
    def test_level_without_exercises_excluded(self):
        code = 'pe316'[:10]
        lang, _ = Language.objects.get_or_create(
            code=code,
            defaults={'name': 'PELang316', 'script_type': 'latin', 'is_active': True, 'order': 99},
        )
        topic, _ = LanguageTopic.objects.get_or_create(
            language=lang, name='Empty Topic', defaults={'order': 0, 'is_active': True},
        )
        level, _ = LanguageTopicLevel.objects.get_or_create(
            topic=topic, level_choice='beginner',
        )
        # No exercises in this level

        tree = plugin.homework_topic_tree(classroom=None)
        for l_obj, mid_items in tree:
            if l_obj.code == code:
                for t_obj, leaves in mid_items:
                    if t_obj.pk == topic.pk:
                        assert not any(lv.pk == level.pk for lv in leaves)


@pytest.mark.django_db
class TestPickHomeworkItems:
    def test_returns_list_of_pks(self):
        _, _, level = _setup_lang('pick')
        for i in range(3):
            LanguageExercise.objects.create(
                topic_level=level,
                exercise_type=LanguageExercise.SPELLING_TYPE,
                prompt=f'pick_{i}',
                is_active=True,
            )

        pks = plugin.pick_homework_items(classroom=None, selected_topic_ids=[level.pk], n=10)
        assert isinstance(pks, list)
        assert len(pks) >= 3
        assert all(isinstance(pk, int) for pk in pks)


@pytest.mark.django_db
class TestPickHomeworkItemsCapsAtN:
    def test_returns_at_most_n_items(self):
        _, _, level = _setup_lang('cap')
        for i in range(10):
            LanguageExercise.objects.create(
                topic_level=level,
                exercise_type=LanguageExercise.SPELLING_TYPE,
                prompt=f'cap_{i}',
                is_active=True,
            )

        pks = plugin.pick_homework_items(classroom=None, selected_topic_ids=[level.pk], n=3)
        assert len(pks) <= 3


@pytest.mark.django_db
class TestSaveHomeworkTopics:
    def test_sets_m2m_on_homework(self):
        from classroom.models import ClassRoom, School
        from homework.models import Homework
        from django.utils import timezone
        from datetime import timedelta

        teacher = _make_teacher('hw_teacher_316')
        school, _ = School.objects.get_or_create(
            name='Test School 316',
            defaults={'slug': 'test-school-316', 'email': 'ts316@test.com'},
        )
        classroom, _ = ClassRoom.objects.get_or_create(
            name='Class 316',
            school=school,
        )
        _, _, level = _setup_lang('save')
        LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='save_test',
            is_active=True,
        )
        hw = Homework.objects.create(
            classroom=classroom,
            created_by=teacher,
            title='Languages HW 316',
            subject_slug='languages',
            num_questions=5,
            due_date=timezone.now() + timedelta(days=7),
        )
        plugin.save_homework_topics(hw, [level.pk])

        assert hw.language_topic_levels.filter(pk=level.pk).exists()


@pytest.mark.django_db
class TestGradeAnswerMCQ:
    def test_correct_answer_graded_true(self):
        _, _, level = _setup_lang('gmcq')
        ex, correct, wrong = _make_mcq_exercise(level)

        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': str(correct.pk)})
        assert result['is_correct'] is True
        assert result['points_earned'] == 5

    def test_wrong_answer_graded_false(self):
        _, _, level = _setup_lang('gmcqw')
        ex, correct, wrong = _make_mcq_exercise(level)

        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': str(wrong.pk)})
        assert result['is_correct'] is False
        assert result['points_earned'] == 0


@pytest.mark.django_db
class TestGradeAnswerSpellingType:
    def test_correct_spelling_graded_true(self):
        _, _, level = _setup_lang('gsp')
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='hello',
            is_active=True,
        )
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': 'hello'})
        assert result['is_correct'] is True

    def test_case_insensitive_for_latin(self):
        _, _, level = _setup_lang('gspi')
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='Hello',
            is_active=True,
        )
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': 'HELLO'})
        assert result['is_correct'] is True


@pytest.mark.django_db
class TestGradeAnswerSentenceOrder:
    def test_partial_credit_returned(self):
        _, _, level = _setup_lang('gso')
        words = ['The', 'cat', 'sat', 'on', 'mat.']
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SENTENCE_ORDER,
            prompt=' '.join(words),
            puzzle_data={'word_order': words},
            is_active=True,
            points=10,
        )
        # Submit 3/5 correct (60%) — partial credit
        submitted = ['The', 'cat', 'mat.', 'on', 'sat']
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': json.dumps(submitted)})
        assert result['is_correct'] is False
        assert float(result['points_earned']) == pytest.approx(6.0, abs=0.1)

    def test_exact_match_full_credit(self):
        _, _, level = _setup_lang('gsoe')
        words = ['Go', 'now.']
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SENTENCE_ORDER,
            prompt='Go now.',
            puzzle_data={'word_order': words},
            is_active=True,
            points=5,
        )
        result = plugin.grade_answer(ex.pk, {f'answer_{ex.id}': json.dumps(words)})
        assert result['is_correct'] is True
