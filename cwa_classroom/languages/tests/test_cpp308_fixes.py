"""
Unit tests for CPP-308 fixes.

TestAdvancedCrosswordRouting   — ADVANCED_CROSSWORD no longer returns 404
TestTTSLangCode                — en → en-NZ, fallback → en-NZ
TestLanguageProgressAdmin      — LanguageProgress registered in admin
TestStageUnlockedSignal        — _recalculate_progress returns bool
TestStageUnlockedInResponse    — POST handlers include stage_unlocked in JSON
TestAdvancedCrosswordInIndex   — advanced_crossword appears in cw_exercises list
TestEmptyStateFlag             — unlocked level with no exercises detected
TestWorksheetBuilderLanguages  — _languages_response returns exercises
"""

import json
import pytest
from django.contrib.admin.sites import AdminSite
from django.test import Client, RequestFactory
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageProgress, LanguageStudentAnswer, LanguageTopic, LanguageTopicLevel,
)
from languages.views import _recalculate_progress
from languages.utils import get_tts_lang_code


pytestmark = pytest.mark.cpp308


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass308!'):
    u = CustomUser.objects.create_user(
        username=username, password=password,
        first_name='Test', last_name='Student', email=f'{username}@test308.com',
        profile_completed=True, must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name='student', defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _make_lang(suffix=''):
    lang, _ = Language.objects.get_or_create(
        code=f'en308{suffix}'[:10],
        defaults={'name': f'English308{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 90},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'Grammar308{suffix}',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    inter, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='intermediate')
    return lang, topic, beg, inter


def _make_exercise(level, ex_type=LanguageExercise.SPELLING_MCQ, points=5):
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=ex_type,
        prompt='testword',
        points=points,
        is_active=True,
    )
    LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False, display_order=1)
    return ex


# ===========================================================================
# TTS
# ===========================================================================

@pytest.mark.django_db
class TestTTSLangCode:

    def test_english_maps_to_en_nz(self):
        assert get_tts_lang_code('en') == 'en-NZ'

    def test_sinhala_maps_to_si_lk(self):
        assert get_tts_lang_code('si') == 'si-LK'

    def test_unknown_code_fallback_is_en_nz(self):
        assert get_tts_lang_code('xx_unknown') == 'en-NZ'

    def test_arabic_maps_correctly(self):
        assert get_tts_lang_code('ar') == 'ar-SA'


# ===========================================================================
# Admin registration
# ===========================================================================

@pytest.mark.django_db
class TestLanguageProgressAdmin:

    def test_language_progress_in_default_admin(self):
        from django.contrib import admin
        from languages.models import LanguageProgress
        assert admin.site.is_registered(LanguageProgress), \
            "LanguageProgress must be registered with the default admin site"


# ===========================================================================
# _recalculate_progress returns bool
# ===========================================================================

@pytest.mark.django_db
class TestStageUnlockedSignal:

    def test_returns_false_when_no_mastery(self):
        _, _, beg, _ = _make_lang('rfa')
        ex = _make_exercise(beg)
        student = _make_student('stu_rfa')
        LanguageStudentAnswer.objects.create(
            student=student, exercise=ex, score=50.0, is_correct=False, points_earned=0,
        )
        result = _recalculate_progress(student, beg)
        assert result is False

    def test_returns_true_on_first_mastery(self):
        _, _, beg, inter = _make_lang('rtm')
        exs = [_make_exercise(beg) for _ in range(3)]
        student = _make_student('stu_rtm')
        for ex in exs:
            LanguageStudentAnswer.objects.create(
                student=student, exercise=ex, score=90.0, is_correct=True, points_earned=ex.points,
            )
        result = _recalculate_progress(student, beg)
        assert result is True

    def test_returns_false_on_repeated_mastery_call(self):
        _, _, beg, inter = _make_lang('rrm')
        exs = [_make_exercise(beg) for _ in range(3)]
        student = _make_student('stu_rrm')
        for ex in exs:
            LanguageStudentAnswer.objects.create(
                student=student, exercise=ex, score=90.0, is_correct=True, points_earned=ex.points,
            )
        _recalculate_progress(student, beg)  # first call sets completed_at
        result = _recalculate_progress(student, beg)  # second call → already completed
        assert result is False

    def test_returns_false_when_no_exercises(self):
        _, _, beg, _ = _make_lang('rne')
        student = _make_student('stu_rne')
        result = _recalculate_progress(student, beg)
        assert result is False


# ===========================================================================
# stage_unlocked in POST response
# ===========================================================================

@pytest.mark.django_db
class TestStageUnlockedInResponse:

    def test_spelling_mcq_post_includes_stage_unlocked(self):
        _, _, beg, _ = _make_lang('sir')
        ex = _make_exercise(beg, LanguageExercise.SPELLING_MCQ)
        student = _make_student('stu_sir')
        correct_answer = ex.answers.filter(is_correct=True).first()

        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.post(url, {'selected_answer_id': correct_answer.pk})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert 'stage_unlocked' in data
        assert isinstance(data['stage_unlocked'], bool)

    def test_spelling_type_post_includes_stage_unlocked(self):
        _, _, beg, _ = _make_lang('stp')
        ex = LanguageExercise.objects.create(
            topic_level=beg, exercise_type=LanguageExercise.SPELLING_TYPE,
            prompt='hello', points=5, is_active=True,
        )
        student = _make_student('stu_stp')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.post(url, {'answer': 'hello'})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert 'stage_unlocked' in data


# ===========================================================================
# ADVANCED_CROSSWORD routing fix
# ===========================================================================

@pytest.mark.django_db
class TestAdvancedCrosswordRouting:

    def test_advanced_crossword_does_not_404(self):
        _, _, beg, _ = _make_lang('acr')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.ADVANCED_CROSSWORD,
            prompt='Advanced CW',
            points=5,
            is_active=True,
            puzzle_data={'words': [], 'width': 5, 'height': 5},
        )
        student = _make_student('stu_acr')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.get(url)
        assert resp.status_code == 200

    def test_advanced_crossword_post_returns_json(self):
        _, _, beg, _ = _make_lang('acp')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.ADVANCED_CROSSWORD,
            prompt='Advanced CW Post',
            points=5,
            is_active=True,
            puzzle_data={'words': [{'index': 0, 'answer': 'test', 'row': 0, 'col': 0, 'direction': 'across'}], 'width': 5, 'height': 5},
        )
        student = _make_student('stu_acp')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.post(url, {
            'word_answers': json.dumps({'0': 'test'}),
            'hints_used': '[]',
        })
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data.get('success') is True
        assert 'stage_unlocked' in data


# ===========================================================================
# ADVANCED_CROSSWORD appears in cw_exercises on index
# ===========================================================================

@pytest.mark.django_db
class TestAdvancedCrosswordInIndex:

    def test_advanced_crossword_exercise_visible_in_index(self):
        lang, _, beg, _ = _make_lang('acix')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.ADVANCED_CROSSWORD,
            prompt='Adv CW Idx',
            points=5,
            is_active=True,
            puzzle_data={'words': [], 'width': 5, 'height': 5},
        )
        student = _make_student('stu_acix')
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code == 200
        # The exercise prompt should appear in the rendered page
        assert b'Adv CW Idx' in resp.content


# ===========================================================================
# Worksheet builder Languages integration
# ===========================================================================

@pytest.mark.django_db
class TestWorksheetBuilderLanguages:

    def _make_teacher(self, username):
        from classroom.models import School
        u = CustomUser.objects.create_user(
            username=username, password='TestPass308!',
            first_name='Teacher', last_name='308', email=f'{username}@test308.com',
            profile_completed=True, must_change_password=False,
        )
        role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        UserRole.objects.get_or_create(user=u, role=role)
        school, _ = School.objects.get_or_create(
            name='WB School 308', defaults={'email': 'wb308@school.com'},
        )
        u._test_school = school
        return u

    def test_languages_question_list_returns_exercises(self):
        lang, topic, beg, _ = _make_lang('wbq')
        ex = _make_exercise(beg)
        teacher = self._make_teacher('tea_wbq308')
        client = Client()
        client.force_login(teacher)
        url = reverse('worksheets:builder_questions') + '?subject=languages'
        resp = client.get(url)
        assert resp.status_code == 200
        assert ex.prompt.encode() in resp.content

    def test_languages_preview_returns_200(self):
        _, _, beg, _ = _make_lang('wbp')
        ex = _make_exercise(beg)
        teacher = self._make_teacher('tea_wbp308')
        client = Client()
        client.force_login(teacher)
        url = reverse('worksheets:builder_preview', kwargs={'subject_slug': 'languages', 'content_id': ex.pk})
        resp = client.get(url)
        assert resp.status_code == 200
        assert ex.prompt.encode() in resp.content

    def test_languages_preview_unknown_id_returns_404(self):
        teacher = self._make_teacher('tea_wbx308')
        client = Client()
        client.force_login(teacher)
        url = reverse('worksheets:builder_preview', kwargs={'subject_slug': 'languages', 'content_id': 999999})
        resp = client.get(url)
        assert resp.status_code == 404
