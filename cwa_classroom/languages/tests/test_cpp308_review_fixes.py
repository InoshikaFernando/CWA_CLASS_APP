"""
Unit tests for CPP-308 senior tech-lead review fixes.

Covers:
- Level ordering: languages_index returns beginner → intermediate → advanced
- MCQ handler refactor: _mcq_handler drives both phonics and spelling correctly
- updated_at: LanguageStudentAnswer.updated_at is set and updated on save
- pick_homework_items: returns correct count using Python shuffle, not ORDER BY RAND()
- Stroke data size guard: oversized stroke_data (>500 KB) is rejected gracefully
- Grammar blank_position: no longer leaked into template context
- Grammar fill_blank: sentence split on '___' renders correctly
"""

import json

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageStudentAnswer, LanguageTopic, LanguageTopicLevel,
)


pytestmark = pytest.mark.cpp308


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username):
    u = CustomUser.objects.create_user(
        username=username, password='ReviewPass!',
        first_name='Rev', last_name='Student',
        email=f'{username}@rev308.com',
        profile_completed=True, must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(name='student', defaults={'display_name': 'Student'})
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _make_lang_all_levels(suffix=''):
    code = f'rv{suffix}'[:10]
    lang, _ = Language.objects.get_or_create(
        code=code,
        defaults={'name': f'RevLang{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 95},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name=f'RevTopic{suffix}',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _   = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='beginner')
    inter, _ = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='intermediate')
    adv, _   = LanguageTopicLevel.objects.get_or_create(topic=topic, level_choice='advanced')
    return lang, topic, beg, inter, adv


def _make_exercise(level, ex_type=LanguageExercise.SPELLING_MCQ, points=3):
    ex = LanguageExercise.objects.create(
        topic_level=level, exercise_type=ex_type,
        prompt='wordrev', points=points, is_active=True,
    )
    LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='wrong',   is_correct=False, display_order=1)
    return ex


# ===========================================================================
# Level ordering on languages_index
# ===========================================================================

@pytest.mark.django_db
class TestLevelOrdering:

    def test_beginner_appears_before_intermediate_in_index_html(self):
        """Index page must render Beginner chip before Intermediate chip."""
        lang, _, beg, inter, adv = _make_lang_all_levels('ord')
        _make_exercise(beg)
        _make_exercise(inter)
        _make_exercise(adv)

        student = _make_student('stu_ord')
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('languages:index'))
        assert resp.status_code == 200

        content = resp.content.decode()
        beg_pos   = content.find('Beginner')
        inter_pos = content.find('Intermediate')
        adv_pos   = content.find('Advanced')

        assert beg_pos   != -1, 'Beginner not found in response'
        assert inter_pos != -1, 'Intermediate not found in response'
        assert adv_pos   != -1, 'Advanced not found in response'
        assert beg_pos < inter_pos, 'Beginner must appear before Intermediate'
        assert inter_pos < adv_pos,  'Intermediate must appear before Advanced'

    def test_context_levels_ordered_by_progression(self):
        """Topic.levels.all() in context must return B→I→A via Prefetch ordering."""
        lang, topic, beg, inter, adv = _make_lang_all_levels('ctx')
        _make_exercise(beg)
        _make_exercise(inter)
        _make_exercise(adv)

        student = _make_student('stu_ctx')
        client = Client()
        client.force_login(student)
        resp = client.get(reverse('languages:index'))

        ctx_lang = next(
            (l for l in resp.context['languages'] if l.code == lang.code), None
        )
        assert ctx_lang is not None
        ctx_topic = next(t for t in ctx_lang.topics.all())
        levels = list(ctx_topic.levels.all())
        choices = [lv.level_choice for lv in levels]
        assert choices == ['beginner', 'intermediate', 'advanced'], \
            f'Expected [beginner, intermediate, advanced], got {choices}'


# ===========================================================================
# MCQ handler refactor — both exercise types still work
# ===========================================================================

@pytest.mark.django_db
class TestMCQHandlerRefactor:

    def test_phonics_mcq_post_returns_correct_json(self):
        _, _, beg, _, _ = _make_lang_all_levels('pmh')
        ex = LanguageExercise.objects.create(
            topic_level=beg, exercise_type=LanguageExercise.PHONICS_MCQ,
            prompt='A', points=4, is_active=True,
        )
        correct = LanguageAnswer.objects.create(exercise=ex, answer_text='ay', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=ex, answer_text='ee', is_correct=False, display_order=1)

        student = _make_student('stu_pmh')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})

        resp = client.post(url, {'selected_answer_id': correct.pk})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True
        assert data['is_correct'] is True
        assert 'stage_unlocked' in data
        assert data['correct_answer_id'] == correct.pk

    def test_spelling_mcq_post_returns_correct_json(self):
        _, _, beg, _, _ = _make_lang_all_levels('smh')
        ex = _make_exercise(beg, LanguageExercise.SPELLING_MCQ)
        correct = ex.answers.filter(is_correct=True).first()

        student = _make_student('stu_smh')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})

        resp = client.post(url, {'selected_answer_id': correct.pk})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True
        assert data['is_correct'] is True
        assert 'stage_unlocked' in data

    def test_phonics_wrong_answer_is_not_correct(self):
        _, _, beg, _, _ = _make_lang_all_levels('pwrong')
        ex = LanguageExercise.objects.create(
            topic_level=beg, exercise_type=LanguageExercise.PHONICS_MCQ,
            prompt='B', points=4, is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='bee', is_correct=True, display_order=0)
        wrong = LanguageAnswer.objects.create(exercise=ex, answer_text='cee', is_correct=False, display_order=1)

        student = _make_student('stu_pwrong')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})

        resp = client.post(url, {'selected_answer_id': wrong.pk})
        data = json.loads(resp.content)
        assert data['is_correct'] is False


# ===========================================================================
# updated_at field on LanguageStudentAnswer
# ===========================================================================

@pytest.mark.django_db
class TestUpdatedAtField:

    def test_updated_at_set_on_creation(self):
        _, _, beg, _, _ = _make_lang_all_levels('uat')
        ex = _make_exercise(beg)
        student = _make_student('stu_uat')

        ans = LanguageStudentAnswer.objects.create(
            student=student, exercise=ex,
            score=80.0, is_correct=True, points_earned=ex.points,
        )
        assert ans.updated_at is not None

    def test_updated_at_changes_on_resave(self):
        import time
        _, _, beg, _, _ = _make_lang_all_levels('uatup')
        ex = _make_exercise(beg)
        student = _make_student('stu_uatup')

        ans = LanguageStudentAnswer.objects.create(
            student=student, exercise=ex,
            score=50.0, is_correct=False, points_earned=0,
        )
        first_ts = ans.updated_at

        time.sleep(0.05)
        ans.score = 90.0
        ans.is_correct = True
        ans.save()  # full save — auto_now only fires in SQL when field is not excluded by update_fields
        ans.refresh_from_db()

        assert ans.updated_at > first_ts, 'updated_at should advance after resave'

    def test_answered_at_does_not_change_on_resave(self):
        """answered_at is auto_now_add — must stay fixed; updated_at moves."""
        import time
        _, _, beg, _, _ = _make_lang_all_levels('atfix')
        ex = _make_exercise(beg)
        student = _make_student('stu_atfix')

        ans = LanguageStudentAnswer.objects.create(
            student=student, exercise=ex,
            score=40.0, is_correct=False, points_earned=0,
        )
        original_answered_at = ans.answered_at

        time.sleep(0.05)
        ans.score = 95.0
        ans.save(update_fields=['score'])
        ans.refresh_from_db()

        assert ans.answered_at == original_answered_at, 'answered_at must not change'


# ===========================================================================
# pick_homework_items — Python shuffle, not ORDER BY RAND()
# ===========================================================================

@pytest.mark.django_db
class TestPickHomeworkItemsShuffle:

    def test_returns_up_to_n_pks(self):
        from languages.plugin import LanguagesPlugin
        _, _, beg, _, _ = _make_lang_all_levels('phi')
        exs = [_make_exercise(beg) for _ in range(6)]

        plugin = LanguagesPlugin()
        result = plugin.pick_homework_items(None, [beg.pk], n=4)
        assert len(result) == 4

    def test_all_returned_pks_are_valid_exercises(self):
        from languages.plugin import LanguagesPlugin
        _, _, beg, _, _ = _make_lang_all_levels('phv')
        exs = [_make_exercise(beg) for _ in range(5)]
        valid_pks = {ex.pk for ex in exs}

        plugin = LanguagesPlugin()
        result = plugin.pick_homework_items(None, [beg.pk], n=3)
        for pk in result:
            assert pk in valid_pks

    def test_returns_all_when_fewer_than_n(self):
        from languages.plugin import LanguagesPlugin
        _, _, beg, _, _ = _make_lang_all_levels('phn')
        exs = [_make_exercise(beg) for _ in range(2)]

        plugin = LanguagesPlugin()
        result = plugin.pick_homework_items(None, [beg.pk], n=10)
        assert len(result) == 2

    def test_empty_level_returns_empty(self):
        from languages.plugin import LanguagesPlugin
        _, _, beg, inter, _ = _make_lang_all_levels('phe')

        plugin = LanguagesPlugin()
        result = plugin.pick_homework_items(None, [inter.pk], n=5)
        assert result == []


# ===========================================================================
# Stroke data size guard (>500 KB rejected)
# ===========================================================================

@pytest.mark.django_db
class TestStrokeDataSizeGuard:

    def _make_letter_exercise(self, suffix=''):
        _, _, beg, _, _ = _make_lang_all_levels(f'sg{suffix}')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.LETTER_WRITING,
            prompt='A',
            points=2,
            is_active=True,
        )
        return ex

    def test_oversized_stroke_data_still_returns_success(self):
        ex = self._make_letter_exercise('ok')
        student = _make_student('stu_sgok')
        client = Client()
        client.force_login(student)

        oversized = 'x' * 600_000  # 600 KB — exceeds 500 KB guard
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.post(url, {'stroke_data': oversized, 'score': '75'})
        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['success'] is True

    def test_oversized_stroke_data_saved_as_empty_dict(self):
        ex = self._make_letter_exercise('empty')
        student = _make_student('stu_sgempty')
        client = Client()
        client.force_login(student)

        oversized = 'x' * 600_000
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        client.post(url, {'stroke_data': oversized, 'score': '60'})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.stroke_data == {}, \
            'Oversized stroke_data should be stored as empty dict'

    def test_oversized_stroke_data_score_is_zero(self):
        """Oversized stroke_data is rejected → no strokes → client score ignored → 0."""
        ex = self._make_letter_exercise('score')
        student = _make_student('stu_sgscore')
        client = Client()
        client.force_login(student)

        oversized = 'x' * 600_000
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        client.post(url, {'stroke_data': oversized, 'score': '82'})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.score == 0.0, 'Score must be 0 when stroke_data is rejected (no strokes = no attempt)'

    def test_normal_stroke_data_passes_through(self):
        ex = self._make_letter_exercise('norm')
        student = _make_student('stu_sgnorm')
        client = Client()
        client.force_login(student)

        valid_payload = json.dumps({'version': '5.3.1', 'objects': [{'type': 'path', 'path': 'M 0 0'}]})
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        client.post(url, {'stroke_data': valid_payload, 'score': '90'})

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert ans.stroke_data != {}, 'Valid stroke_data should be stored'
        assert ans.stroke_data.get('version') == '5.3.1'


# ===========================================================================
# Grammar fill_blank — blank_position removed, sentence split correct
# ===========================================================================

@pytest.mark.django_db
class TestGrammarFillBlankContext:

    def test_sentence_split_on_triple_underscore(self):
        _, _, beg, _, _ = _make_lang_all_levels('gfb')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
            prompt='The cat ___ on the mat.',
            puzzle_data={'grammar_explanation': 'sat is past tense'},
            points=5,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='sat', is_correct=True, display_order=0)

        student = _make_student('stu_gfb')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.get(url)

        assert resp.status_code == 200
        assert b'The cat ' in resp.content
        assert b'on the mat.' in resp.content

    def test_blank_position_not_in_response_context(self):
        _, _, beg, _, _ = _make_lang_all_levels('gfbnp')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
            prompt='She ___ to school.',
            puzzle_data={'blank_position': 1, 'grammar_explanation': 'goes = third person singular'},
            points=5,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='goes', is_correct=True, display_order=0)

        student = _make_student('stu_gfbnp')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.get(url)

        assert 'blank_position' not in resp.context, \
            'blank_position should not be in template context'

    def test_grammar_post_returns_explanation(self):
        _, _, beg, _, _ = _make_lang_all_levels('gfbp')
        ex = LanguageExercise.objects.create(
            topic_level=beg,
            exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
            prompt='He ___ happy.',
            puzzle_data={'grammar_explanation': 'is = present tense of be'},
            points=5,
            is_active=True,
        )
        correct = LanguageAnswer.objects.create(exercise=ex, answer_text='is', is_correct=True, display_order=0)
        LanguageAnswer.objects.create(exercise=ex, answer_text='was', is_correct=False, display_order=1)

        student = _make_student('stu_gfbp')
        client = Client()
        client.force_login(student)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})
        resp = client.post(url, {'selected_answer_id': correct.pk})

        assert resp.status_code == 200
        data = json.loads(resp.content)
        assert data['is_correct'] is True
        assert 'is = present tense' in data['grammar_explanation']
