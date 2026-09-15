"""
Unit tests for CPP-315: Grammar fill-in-the-blank and sentence ordering.

Tests:
  TestFillBlankCorrect              — correct answer → score=100, is_correct=True
  TestFillBlankIncorrect            — wrong answer → score=0, returns grammar explanation
  TestFillBlankNoAnswer             — missing answer_id → score=0
  TestFillBlankRetryOverwrites      — second POST always updates (even if lower score)
  TestFillBlankGetRendersTemplate   — GET returns 200 with sentence gap and answer buttons

  TestSentenceOrderExactMatch       — all words correct → score=100, is_correct=True
  TestSentenceOrderPartialCredit    — partial match → proportional score
  TestSentenceOrder80PctThreshold   — ≥80% correct → is_correct=True
  TestSentenceOrderBelow80          — <80% correct → is_correct=False
  TestSentenceOrderBestScoreKept    — retry only updates if score improves
  TestSentenceOrderEmptySubmit      — empty list → score=0
  TestSentenceOrderGetRendersTemplate — GET returns 200 with tiles template
"""
import json
from decimal import Decimal

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language,
    LanguageAnswer,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)


pytestmark = pytest.mark.cpp315


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass315!'):
    u = CustomUser.objects.create_user(
        username=username, password=password,
        first_name='Test', last_name='Student', email=f'{username}@test.com',
    )
    student_role, _ = Role.objects.get_or_create(name='student')
    UserRole.objects.get_or_create(user=u, role=student_role)
    return u


def _make_lang():
    lang, _ = Language.objects.get_or_create(
        code='en315',
        defaults={'name': 'English 315', 'script_type': 'latin', 'is_active': True},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Grammar',
        defaults={'order': 0, 'is_active': True},
    )
    # Use a beginner level so these grading tests aren't blocked by the
    # cpp316 stage-progression gate (only beginner is unlocked by default).
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='beginner',
    )
    return lang, level


def _make_fill_blank(level, sentence='The cat ___ on the mat.', explanation='Past tense.'):
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.GRAMMAR_FILL_BLANK,
        prompt=sentence,
        puzzle_data={'blank_position': 2, 'grammar_explanation': explanation},
        points=5,
        is_active=True,
    )
    correct = LanguageAnswer.objects.create(exercise=ex, answer_text='sat', is_correct=True, display_order=0)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sit', is_correct=False, display_order=1)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sits', is_correct=False, display_order=2)
    LanguageAnswer.objects.create(exercise=ex, answer_text='sitting', is_correct=False, display_order=3)
    return ex, correct


def _make_sentence_order(level, words=None):
    words = words or ['The', 'cat', 'sat', 'on', 'the', 'mat.']
    ex = LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.SENTENCE_ORDER,
        prompt=' '.join(words),
        puzzle_data={'word_order': words},
        points=5,
        is_active=True,
    )
    return ex


def _url(ex):
    return reverse('languages:exercise_detail', kwargs={'exercise_id': ex.id})


# ===========================================================================
# Grammar Fill-in-the-Blank Tests
# ===========================================================================

@pytest.mark.django_db
class TestFillBlankCorrect:
    def test_correct_answer_returns_100_and_correct_flag(self):
        student = _make_student('gfb_correct_315')
        lang, level = _make_lang()
        ex, correct_ans = _make_fill_blank(level)

        c = Client()
        c.login(username='gfb_correct_315', password='TestPass315!')
        resp = c.post(_url(ex), {'selected_answer_id': correct_ans.pk, 'csrfmiddlewaretoken': 'x'})

        assert resp.status_code == 200
        data = resp.json()
        assert data['is_correct'] is True
        assert data['correct_answer_id'] == correct_ans.pk
        assert data['points_earned'] == '5'

        sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert sa.score == 100.0
        assert sa.is_correct is True
        assert sa.points_earned == Decimal('5')


@pytest.mark.django_db
class TestFillBlankIncorrect:
    def test_wrong_answer_returns_0_and_explanation(self):
        student = _make_student('gfb_wrong_315')
        lang, level = _make_lang()
        explanation = 'Past tense of sit is sat.'
        ex, correct_ans = _make_fill_blank(level, explanation=explanation)
        wrong_ans = ex.answers.filter(is_correct=False).first()

        c = Client()
        c.login(username='gfb_wrong_315', password='TestPass315!')
        resp = c.post(_url(ex), {'selected_answer_id': wrong_ans.pk})

        data = resp.json()
        assert data['is_correct'] is False
        assert data['correct_answer_id'] == correct_ans.pk
        assert data['grammar_explanation'] == explanation
        assert data['points_earned'] == '0'


@pytest.mark.django_db
class TestFillBlankNoAnswer:
    def test_missing_answer_id_scores_zero(self):
        _make_student('gfb_noanswer_315')
        lang, level = _make_lang()
        ex, _ = _make_fill_blank(level)

        c = Client()
        c.login(username='gfb_noanswer_315', password='TestPass315!')
        resp = c.post(_url(ex), {'selected_answer_id': ''})

        data = resp.json()
        assert data['is_correct'] is False
        assert data['points_earned'] == '0'


@pytest.mark.django_db
class TestFillBlankRetryOverwrites:
    def test_second_post_always_updates_record(self):
        student = _make_student('gfb_retry_315')
        lang, level = _make_lang()
        ex, correct_ans = _make_fill_blank(level)
        wrong_ans = ex.answers.filter(is_correct=False).first()

        c = Client()
        c.login(username='gfb_retry_315', password='TestPass315!')

        # First attempt: wrong
        c.post(_url(ex), {'selected_answer_id': wrong_ans.pk})
        sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert sa.is_correct is False

        # Second attempt: correct
        c.post(_url(ex), {'selected_answer_id': correct_ans.pk})
        sa.refresh_from_db()
        assert sa.is_correct is True
        assert sa.score == 100.0


@pytest.mark.django_db
class TestFillBlankGetRendersTemplate:
    def test_get_returns_200_with_blank_sentence(self):
        _make_student('gfb_get_315')
        lang, level = _make_lang()
        ex, _ = _make_fill_blank(level, sentence='The dog ___ at night.')

        c = Client()
        c.login(username='gfb_get_315', password='TestPass315!')
        resp = c.get(_url(ex))

        assert resp.status_code == 200
        assert b'grammar-blank' in resp.content
        assert b'The dog' in resp.content
        assert b'at night.' in resp.content


# ===========================================================================
# Sentence Order Tests
# ===========================================================================

@pytest.mark.django_db
class TestSentenceOrderExactMatch:
    def test_exact_match_scores_100_and_correct(self):
        student = _make_student('so_exact_315')
        lang, level = _make_lang()
        words = ['The', 'cat', 'sat', 'on', 'the', 'mat.']
        ex = _make_sentence_order(level, words)

        c = Client()
        c.login(username='so_exact_315', password='TestPass315!')
        resp = c.post(_url(ex), {'submitted_order': json.dumps(words)})

        data = resp.json()
        assert data['is_correct'] is True
        assert data['score'] == 100.0
        assert data['correct_count'] == 6
        assert data['total'] == 6

        sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert sa.is_correct is True
        assert sa.score == 100.0
        assert sa.points_earned == Decimal('5.00')


@pytest.mark.django_db
class TestSentenceOrderPartialCredit:
    def test_4_of_6_correct_gives_proportional_score(self):
        student = _make_student('so_partial_315')
        lang, level = _make_lang()
        words = ['The', 'cat', 'sat', 'on', 'the', 'mat.']
        ex = _make_sentence_order(level, words)

        # Submit with 4 correct positions: swap 'sat' and 'on'
        submitted = ['The', 'cat', 'on', 'sat', 'the', 'mat.']
        c = Client()
        c.login(username='so_partial_315', password='TestPass315!')
        resp = c.post(_url(ex), {'submitted_order': json.dumps(submitted)})

        data = resp.json()
        assert data['correct_count'] == 4
        assert data['total'] == 6
        assert data['score'] == pytest.approx(66.7, abs=0.1)
        assert data['is_correct'] is False

        sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert sa.score == pytest.approx(66.7, abs=0.1)
        # Points earned proportional: 66.7% of 5 = ~3.33
        assert float(sa.points_earned) == pytest.approx(3.33, abs=0.02)


@pytest.mark.django_db
class TestSentenceOrder80PctThreshold:
    def test_5_of_6_correct_is_correct_true(self):
        student = _make_student('so_80pct_315')
        lang, level = _make_lang()
        words = ['She', 'likes', 'to', 'read', 'books', 'daily.']
        ex = _make_sentence_order(level, words)

        # 5 correct (83.3%) — swap last two
        submitted = ['She', 'likes', 'to', 'read', 'daily.', 'books']
        c = Client()
        c.login(username='so_80pct_315', password='TestPass315!')
        resp = c.post(_url(ex), {'submitted_order': json.dumps(submitted)})

        data = resp.json()
        assert data['correct_count'] == 4
        assert data['is_correct'] is False  # 4/6 = 66.7% < 80%

        # Now try 5/6 correct (83.3%)
        submitted2 = ['She', 'likes', 'to', 'read', 'books', 'books']
        resp2 = c.post(_url(ex), {'submitted_order': json.dumps(submitted2)})
        data2 = resp2.json()
        assert data2['correct_count'] == 5
        assert data2['score'] == pytest.approx(83.3, abs=0.1)
        assert data2['is_correct'] is True


@pytest.mark.django_db
class TestSentenceOrderBelow80:
    def test_below_80pct_is_not_correct(self):
        _make_student('so_below_315')
        lang, level = _make_lang()
        words = ['A', 'B', 'C', 'D', 'E']
        ex = _make_sentence_order(level, words)

        # 3/5 = 60% < 80%
        submitted = ['A', 'B', 'C', 'E', 'D']
        c = Client()
        c.login(username='so_below_315', password='TestPass315!')
        resp = c.post(_url(ex), {'submitted_order': json.dumps(submitted)})

        data = resp.json()
        assert data['correct_count'] == 3
        assert data['is_correct'] is False


@pytest.mark.django_db
class TestSentenceOrderBestScoreKept:
    def test_retry_only_updates_when_score_improves(self):
        student = _make_student('so_bestscore_315')
        lang, level = _make_lang()
        words = ['The', 'cat', 'sat', 'on', 'the', 'mat.']
        ex = _make_sentence_order(level, words)

        c = Client()
        c.login(username='so_bestscore_315', password='TestPass315!')

        # First: perfect
        c.post(_url(ex), {'submitted_order': json.dumps(words)})
        sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
        assert sa.score == 100.0

        # Second: worse — should NOT overwrite best score
        bad = ['mat.', 'the', 'on', 'sat', 'cat', 'The']
        c.post(_url(ex), {'submitted_order': json.dumps(bad)})
        sa.refresh_from_db()
        assert sa.score == 100.0  # best score preserved


@pytest.mark.django_db
class TestSentenceOrderEmptySubmit:
    def test_empty_submission_scores_zero(self):
        student = _make_student('so_empty_315')
        lang, level = _make_lang()
        words = ['Hello', 'world.']
        ex = _make_sentence_order(level, words)

        c = Client()
        c.login(username='so_empty_315', password='TestPass315!')
        resp = c.post(_url(ex), {'submitted_order': json.dumps([])})

        data = resp.json()
        assert data['score'] == 0.0
        assert data['is_correct'] is False
        assert data['correct_count'] == 0


@pytest.mark.django_db
class TestSentenceOrderGetRendersTemplate:
    def test_get_returns_200_with_word_bank(self):
        _make_student('so_get_315')
        lang, level = _make_lang()
        ex = _make_sentence_order(level)

        c = Client()
        c.login(username='so_get_315', password='TestPass315!')
        resp = c.get(_url(ex))

        assert resp.status_code == 200
        assert b'word-bank' in resp.content
        assert b'answer-zone' in resp.content
        assert b'Sortable.min.js' in resp.content
