"""
Unit tests for CPP-316: Stage progression tracking.

TestFirstStageUnlocked       — beginner LanguageProgress created with is_unlocked=True
TestStageLocksByDefault      — non-beginner has no row → locked
TestStageUnlockAt80Percent   — after 80% mastery, next level is_unlocked=True
TestStageStaysLockedBelow80  — below 80% avg → stays locked
TestCompletedAtSetOnMastery  — completed_at populated on mastery
TestRetryUpdatesProgress     — re-attempt with better score recalculates correctly
TestBestScoreAvgComputation  — avg is across exercises, not answer count
"""

import pytest
from django.test import Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from languages.models import (
    Language, LanguageAnswer, LanguageExercise,
    LanguageProgress, LanguageStudentAnswer, LanguageTopic, LanguageTopicLevel,
)
from languages.views import _recalculate_progress


pytestmark = pytest.mark.cpp316


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_student(username, password='TestPass316!'):
    u = CustomUser.objects.create_user(
        username=username, password=password,
        first_name='Test', last_name='Student', email=f'{username}@test.com',
    )
    role, _ = Role.objects.get_or_create(name='student')
    UserRole.objects.get_or_create(user=u, role=role)
    return u


def _make_lang():
    lang, _ = Language.objects.get_or_create(
        code='en316',
        defaults={'name': 'English 316', 'script_type': 'latin', 'is_active': True},
    )
    topic, _ = LanguageTopic.objects.get_or_create(
        language=lang, name='Grammar 316',
        defaults={'order': 0, 'is_active': True},
    )
    beg, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='beginner',
    )
    inter, _ = LanguageTopicLevel.objects.get_or_create(
        topic=topic, level_choice='intermediate',
    )
    return lang, topic, beg, inter


def _make_exercises(level, count=5, points=5):
    exercises = []
    for i in range(count):
        ex = LanguageExercise.objects.create(
            topic_level=level,
            exercise_type=LanguageExercise.SPELLING_MCQ,
            prompt=f'word_{i}',
            points=points,
            is_active=True,
        )
        LanguageAnswer.objects.create(exercise=ex, answer_text='correct', is_correct=True)
        LanguageAnswer.objects.create(exercise=ex, answer_text='wrong', is_correct=False)
        exercises.append(ex)
    return exercises


def _submit_scores(student, exercises, scores):
    for ex, score in zip(exercises, scores):
        is_correct = score >= 80.0
        LanguageStudentAnswer.objects.get_or_create(
            student=student,
            exercise=ex,
            defaults={'score': score, 'is_correct': is_correct, 'points_earned': ex.points if is_correct else 0},
        )


# ===========================================================================

@pytest.mark.django_db
class TestFirstStageUnlocked:
    def test_beginner_progress_created_unlocked(self):
        student = _make_student('prog_beg_316')
        _, _, beg, _ = _make_lang()
        exercises = _make_exercises(beg, count=3)

        # Answer one exercise to trigger recalculation
        _submit_scores(student, exercises[:1], [90.0])
        _recalculate_progress(student, beg)

        p = LanguageProgress.objects.get(student=student, topic_level=beg)
        assert p.is_unlocked is True


@pytest.mark.django_db
class TestStageLocksByDefault:
    def test_intermediate_locked_without_progress(self):
        from languages.views import _is_level_locked
        student = _make_student('prog_lock_316')
        _, _, _, inter = _make_lang()

        assert _is_level_locked(student, inter) is True


@pytest.mark.django_db
class TestStageUnlockAt80Percent:
    def test_intermediate_unlocked_after_mastery(self):
        student = _make_student('prog_unlock_316')
        _, _, beg, inter = _make_lang()
        exercises = _make_exercises(beg, count=5)

        # 5/5 with avg 100 — clear mastery
        _submit_scores(student, exercises, [100.0] * 5)
        _recalculate_progress(student, beg)

        beg_p = LanguageProgress.objects.get(student=student, topic_level=beg)
        assert beg_p.completed_at is not None

        inter_p = LanguageProgress.objects.get(student=student, topic_level=inter)
        assert inter_p.is_unlocked is True


@pytest.mark.django_db
class TestStageStaysLockedBelow80:
    def test_below_80pct_avg_keeps_intermediate_locked(self):
        student = _make_student('prog_below_316')
        _, _, beg, inter = _make_lang()
        exercises = _make_exercises(beg, count=5)

        # avg = 60 — below mastery threshold
        _submit_scores(student, exercises, [60.0] * 5)
        _recalculate_progress(student, beg)

        beg_p = LanguageProgress.objects.get(student=student, topic_level=beg)
        assert beg_p.completed_at is None

        assert not LanguageProgress.objects.filter(student=student, topic_level=inter).exists()


@pytest.mark.django_db
class TestCompletedAtSetOnMastery:
    def test_completed_at_set_when_mastery_achieved(self):
        student = _make_student('prog_done_316')
        _, _, beg, _ = _make_lang()
        exercises = _make_exercises(beg, count=3)

        _submit_scores(student, exercises, [85.0, 90.0, 95.0])
        _recalculate_progress(student, beg)

        p = LanguageProgress.objects.get(student=student, topic_level=beg)
        assert p.completed_at is not None
        assert p.exercises_completed == 3
        assert p.exercises_total == 3


@pytest.mark.django_db
class TestRetryUpdatesProgress:
    def test_better_score_on_retry_recalculates(self):
        student = _make_student('prog_retry_316')
        _, _, beg, inter = _make_lang()
        exercises = _make_exercises(beg, count=3)

        # First: below mastery
        _submit_scores(student, exercises, [50.0, 50.0, 50.0])
        _recalculate_progress(student, beg)

        p = LanguageProgress.objects.get(student=student, topic_level=beg)
        assert p.completed_at is None
        assert p.best_score_avg == pytest.approx(50.0, abs=0.1)

        # Improve scores
        for ex in exercises:
            sa = LanguageStudentAnswer.objects.get(student=student, exercise=ex)
            sa.score = 90.0
            sa.is_correct = True
            sa.save(update_fields=['score', 'is_correct'])

        _recalculate_progress(student, beg)
        p.refresh_from_db()
        assert p.best_score_avg == pytest.approx(90.0, abs=0.1)
        assert p.completed_at is not None


@pytest.mark.django_db
class TestBestScoreAvgComputation:
    def test_avg_across_exercises(self):
        student = _make_student('prog_avg_316')
        _, _, beg, _ = _make_lang()
        exercises = _make_exercises(beg, count=4)

        # 4 exercises with different scores
        _submit_scores(student, exercises, [80.0, 90.0, 100.0, 70.0])
        _recalculate_progress(student, beg)

        p = LanguageProgress.objects.get(student=student, topic_level=beg)
        # avg = (80+90+100+70)/4 = 85
        assert p.best_score_avg == pytest.approx(85.0, abs=0.1)
        # exercises_completed (score>=80): 3
        assert p.exercises_completed == 3
