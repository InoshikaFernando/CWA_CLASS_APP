"""
Unit tests for CPP-311: handwriting grading view logic (persistence,
clamping, star thresholds, best-score-on-retry) — decoupled from the
scoring algorithm itself, which is now server-side and covered separately
in test_cpp392_scoring_metric.py.

CPP-392 replaced the raw pixel-IoU metric and made the server authoritative:
it recomputes the score from the posted ink image via languages.scoring
rather than trusting a client-submitted number. These tests mock
scoring.compute_score() to inject a controlled score so they can keep
testing the view's persistence/clamping/threshold logic in isolation.

Tests:
  test_star_thresholds                        — _stars_from_score pure function coverage
  test_score_persisted                        — score field written to DB
  test_best_score_kept_on_retry                — second attempt (higher) overwrites
  test_lower_score_not_overwritten             — second attempt (lower) leaves DB unchanged
  test_score_below_50_not_correct              — score=30 → is_correct=False, points=0
  test_score_50_is_correct                     — boundary: score=50 → is_correct=True
  test_response_includes_stars                 — score=72 → response stars==2
  test_response_includes_best_score            — second POST returns best_score from DB
  test_client_score_field_is_ignored_even_when_extreme_{high,low}
                                                — a posted 'score' field can't override
                                                  the server-computed score (CPP-392)
"""
import json
from unittest.mock import patch

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language,
    LanguageExercise,
    LanguageStudentAnswer,
    LanguageTopic,
    LanguageTopicLevel,
)
from languages.views import _stars_from_score


pytestmark = pytest.mark.cpp311


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass311!'):
    u = CustomUser.objects.create_user(
        username=username,
        password=password,
        email=f'{username}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    role, _ = Role.objects.get_or_create(
        name=Role.STUDENT,
        defaults={'display_name': 'Student'},
    )
    UserRole.objects.get_or_create(user=u, role=role)
    return u, password


def _make_exercise(suffix='311'):
    lang, _ = Language.objects.get_or_create(
        code=f'en{suffix}',
        defaults={'name': f'English{suffix}', 'script_type': 'latin', 'is_active': True, 'order': 99},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang,
        name=f'Alphabet {suffix}',
        defaults={'order': 1, 'is_active': True},
    )
    level, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic,
        level_choice=LanguageTopicLevel.BEGINNER,
    )
    return LanguageExercise.objects.create(
        topic_level=level,
        exercise_type=LanguageExercise.LETTER_WRITING,
        prompt='A',
        points=5,
        is_active=True,
    )


def _post_score(client, url, score):
    """POST a submission that the (mocked) scorer reports as `score`.

    CPP-392 made the server authoritative: it recomputes the score from the
    posted ink image rather than trusting a client-submitted number, so
    these tests — which are about the *view's* persistence/clamping/
    threshold logic, not the scoring algorithm (see
    test_cpp392_scoring_metric.py for that) — mock the scorer instead of
    posting a 'score' field, which the view no longer reads.
    """
    stroke = json.dumps({'version': '5.3.1', 'objects': [{'type': 'path'}]})
    score = max(0.0, min(100.0, float(score)))
    reason = (
        'excellent_match' if score >= 85 else
        'close_match' if score >= 70 else
        'needs_practice' if score >= 50 else
        'shape_mismatch'
    )
    with patch('languages.views.scoring.compute_score', return_value=(score, reason)):
        return client.post(url, data={'stroke_data': stroke, 'ink_image': 'dummy'})


# ---------------------------------------------------------------------------
# Test 1: star thresholds (pure function — no DB)
# ---------------------------------------------------------------------------

class TestStarThresholds:

    def test_below_50_gives_0_stars(self):
        assert _stars_from_score(0) == 0
        assert _stars_from_score(49) == 0
        assert _stars_from_score(49.9) == 0

    def test_50_gives_1_star(self):
        assert _stars_from_score(50) == 1
        assert _stars_from_score(69) == 1
        assert _stars_from_score(69.9) == 1

    def test_70_gives_2_stars(self):
        assert _stars_from_score(70) == 2
        assert _stars_from_score(84) == 2
        assert _stars_from_score(84.9) == 2

    def test_85_gives_3_stars(self):
        assert _stars_from_score(85) == 3
        assert _stars_from_score(100) == 3


# ---------------------------------------------------------------------------
# Test 2: score field persisted to DB
# ---------------------------------------------------------------------------

class TestScorePersisted:

    @pytest.mark.django_db
    def test_score_written_to_student_answer(self):
        student, pwd = _make_student('stu_score_311a')
        exercise = _make_exercise('311a')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = _post_score(client, url, 72)

        assert resp.status_code == 200
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.score == pytest.approx(72.0)


# ---------------------------------------------------------------------------
# Test 3: best-score kept on retry (higher score)
# ---------------------------------------------------------------------------

class TestBestScoreKeptOnRetry:

    @pytest.mark.django_db
    def test_higher_score_overwrites(self):
        student, pwd = _make_student('stu_best_311b')
        exercise = _make_exercise('311b')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        _post_score(client, url, 60)
        _post_score(client, url, 80)

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.score == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Test 4: lower score does NOT overwrite DB
# ---------------------------------------------------------------------------

class TestLowerScoreNotOverwritten:

    @pytest.mark.django_db
    def test_lower_score_leaves_db_unchanged(self):
        student, pwd = _make_student('stu_lower_311c')
        exercise = _make_exercise('311c')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        _post_score(client, url, 80)
        _post_score(client, url, 50)

        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.score == pytest.approx(80.0)


# ---------------------------------------------------------------------------
# Test 5: score < 50 → is_correct=False, points=0
# ---------------------------------------------------------------------------

class TestScoreBelow50NotCorrect:

    @pytest.mark.django_db
    def test_score_30_not_correct(self):
        student, pwd = _make_student('stu_low_311d')
        exercise = _make_exercise('311d')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = _post_score(client, url, 30)
        data = resp.json()

        assert data['is_correct'] is False
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is False
        assert ans.points_earned == 0


# ---------------------------------------------------------------------------
# Test 6: score == 50 boundary → is_correct=True
# ---------------------------------------------------------------------------

class TestScoreBoundary50IsCorrect:

    @pytest.mark.django_db
    def test_score_50_is_correct(self):
        student, pwd = _make_student('stu_bound_311e')
        exercise = _make_exercise('311e')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = _post_score(client, url, 50)
        data = resp.json()

        assert data['is_correct'] is True
        ans = LanguageStudentAnswer.objects.get(student=student, exercise=exercise)
        assert ans.is_correct is True
        assert int(ans.points_earned) == exercise.points


# ---------------------------------------------------------------------------
# Test 7: response includes correct stars
# ---------------------------------------------------------------------------

class TestResponseIncludesStars:

    @pytest.mark.django_db
    def test_score_72_returns_2_stars(self):
        student, pwd = _make_student('stu_stars_311f')
        exercise = _make_exercise('311f')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = _post_score(client, url, 72)
        data = resp.json()

        assert data['stars'] == 2

    @pytest.mark.django_db
    def test_score_85_returns_3_stars(self):
        student, pwd = _make_student('stu_stars3_311g')
        exercise = _make_exercise('311g')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        resp = _post_score(client, url, 85)
        data = resp.json()

        assert data['stars'] == 3


# ---------------------------------------------------------------------------
# Test 8: response includes best_score from DB
# ---------------------------------------------------------------------------

class TestResponseIncludesBestScore:

    @pytest.mark.django_db
    def test_second_post_returns_db_best_score(self):
        student, pwd = _make_student('stu_best2_311h')
        exercise = _make_exercise('311h')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        _post_score(client, url, 80)
        resp2 = _post_score(client, url, 50)
        data = resp2.json()

        # Second attempt is lower; best_score must reflect DB value (80)
        assert data['best_score'] == pytest.approx(80.0)

    @pytest.mark.django_db
    def test_client_score_field_is_ignored_even_when_extreme_high(self):
        """CPP-392: the server recomputes the score from the ink image and
        never reads a client-submitted 'score' field — a malicious/broken
        client posting an out-of-range value can't influence what's stored."""
        student, pwd = _make_student('stu_clamp_311i')
        exercise = _make_exercise('311i')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        stroke = json.dumps({'version': '5.3.1', 'objects': [{'type': 'path'}]})
        with patch('languages.views.scoring.compute_score', return_value=(42.0, 'needs_practice')):
            resp = client.post(url, data={'stroke_data': stroke, 'ink_image': 'dummy', 'score': '999'})
        data = resp.json()

        assert data['score'] == pytest.approx(42.0), \
            "client-posted 'score': '999' must not override the server-computed score"

    @pytest.mark.django_db
    def test_client_score_field_is_ignored_even_when_extreme_low(self):
        student, pwd = _make_student('stu_clamp0_311j')
        exercise = _make_exercise('311j')

        client = Client()
        client.login(username=student.username, password=pwd)
        url = reverse('languages:exercise_detail', kwargs={'exercise_id': exercise.pk})

        stroke = json.dumps({'version': '5.3.1', 'objects': [{'type': 'path'}]})
        with patch('languages.views.scoring.compute_score', return_value=(10.0, 'shape_mismatch')):
            resp = client.post(url, data={'stroke_data': stroke, 'ink_image': 'dummy', 'score': '-50'})
        data = resp.json()

        assert data['score'] == pytest.approx(10.0), \
            "client-posted 'score': '-50' must not override the server-computed score"
        assert data['is_correct'] is False
