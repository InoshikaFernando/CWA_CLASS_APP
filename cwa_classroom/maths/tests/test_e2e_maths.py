"""
End-to-end tests for the maths app.

Covers:
  - Basic Facts quiz flow (subtopic selection, quiz loading, answer submission)
  - Topic quiz flow (topic list, level detail, take quiz)
  - Times Tables (multiplication/division selection and quiz)
  - Progress dashboard (student dashboard, detail view, results display)
  - Time tracking (TimeLog creation, daily/weekly accumulation, resets)
"""

import json
import uuid
from datetime import date, timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from maths.models import (
    Answer,
    BasicFactsResult,
    Question,
    StudentAnswer,
    StudentFinalAnswer,
    TimeLog,
)
from classroom.models import ClassRoom, Level, Topic


def _create_student(username="student1", password="password1!"):
    """Helper: create a student user with the individual_student role and active subscription."""
    from billing.models import Subscription
    user = CustomUser.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(
        name=Role.INDIVIDUAL_STUDENT,
        defaults={"display_name": "Individual Student"},
    )
    UserRole.objects.get_or_create(user=user, role=role)
    Subscription.objects.get_or_create(
        user=user, defaults={"status": Subscription.STATUS_ACTIVE},
    )
    return user


def _create_teacher(username="teacher1", password="password1!"):
    """Helper: create a teacher user."""
    user = CustomUser.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(
        name=Role.TEACHER,
        defaults={"display_name": "Teacher"},
    )
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _create_question_with_answers(level, topic=None, question_text="What is 2+2?",
                                   correct_answer="4", wrong_answers=None,
                                   question_type="multiple_choice"):
    """Helper: create a Question with Answer rows. Returns (question, correct_answer_obj)."""
    if wrong_answers is None:
        wrong_answers = ["3", "5", "6"]
    q = Question.objects.create(
        level=level,
        topic=topic,
        question_text=question_text,
        question_type=question_type,
        difficulty=1,
        points=1,
    )
    correct = Answer.objects.create(question=q, answer_text=correct_answer, is_correct=True, order=0)
    for idx, wrong in enumerate(wrong_answers, start=1):
        Answer.objects.create(question=q, answer_text=wrong, is_correct=False, order=idx)
    return q, correct


# ---------------------------------------------------------------------------
# 4. ProgressTrackingTest
# ---------------------------------------------------------------------------
class ProgressTrackingTest(TestCase):
    """Test the student progress dashboard views."""

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Subject
        cls.student = _create_student()
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.topic = Topic.objects.create(
            name="Measurements", slug="measurements-test", subject=cls.subject,
        )
        cls.level, _ = Level.objects.get_or_create(
            level_number=4, defaults={'display_name': 'Year 4'},
        )
        cls.topic.levels.add(cls.level)

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="password1!")

    def test_dashboard_loads_for_student(self):
        url = reverse("maths:dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_detail_loads(self):
        url = reverse("maths:dashboard_detail")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_shows_quiz_results_after_attempt(self):
        """After recording a StudentFinalAnswer the dashboard should still load."""
        StudentFinalAnswer.objects.create(
            student=self.student,
            topic=self.topic,
            level=self.level,
            quiz_type="topic",
            attempt_number=1,
            score=8,
            total_questions=10,
            points=72.5,
            time_taken_seconds=45,
        )
        url = reverse("maths:dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_dashboard_requires_login(self):
        """Unauthenticated request should redirect to login."""
        self.client.logout()
        url = reverse("maths:dashboard")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn("login", resp.url.lower())


# ---------------------------------------------------------------------------
# 5. TimeTrackingTest
# ---------------------------------------------------------------------------
class TimeTrackingTest(TestCase):
    """Test the TimeLog model and the update_time_log API endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _create_student()

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="password1!")

    # -- endpoint creates / returns entry --
    def test_update_time_log_creates_entry(self):
        """GET /api/update-time-log/ should create a TimeLog if none exists."""
        url = reverse("maths:update_time_log")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("daily_seconds", data)
        self.assertIn("weekly_seconds", data)
        # TimeLog record should exist
        self.assertTrue(TimeLog.objects.filter(student=self.student).exists())

    def test_update_time_log_unauthorized_for_anonymous(self):
        """Anonymous user should get 401."""
        self.client.logout()
        url = reverse("maths:update_time_log")
        resp = self.client.get(url)
        # Either 401 or redirect to login
        self.assertIn(resp.status_code, [302, 401])

    # -- daily accumulation --
    def test_daily_time_accumulates(self):
        """Time from quiz results completed today should accumulate in daily_total_seconds."""
        now = timezone.now()
        # Create a completed quiz result with time
        BasicFactsResult.objects.create(
            student=self.student,
            subtopic="Addition",
            level_number=1,
            session_id=str(uuid.uuid4()),
            score=8,
            total_points=10,
            time_taken_seconds=120,
            points=50.0,
        )
        BasicFactsResult.objects.create(
            student=self.student,
            subtopic="Addition",
            level_number=2,
            session_id=str(uuid.uuid4()),
            score=9,
            total_points=10,
            time_taken_seconds=90,
            points=65.0,
        )

        # Trigger time log update via the view (which calls get_or_create_time_log
        # but actual accumulation comes from update_time_log_from_activities)
        from maths.views import update_time_log_from_activities

        time_log = update_time_log_from_activities(self.student)
        self.assertEqual(time_log.daily_total_seconds, 210)

    # -- weekly accumulation --
    def test_weekly_time_accumulates(self):
        """Time from quiz results this week should accumulate in weekly_total_seconds."""
        StudentFinalAnswer.objects.create(
            student=self.student,
            quiz_type="topic",
            attempt_number=1,
            score=5,
            total_questions=10,
            points=40.0,
            time_taken_seconds=200,
        )

        from maths.views import update_time_log_from_activities

        time_log = update_time_log_from_activities(self.student)
        self.assertEqual(time_log.weekly_total_seconds, 200)

    # -- daily reset --
    def test_daily_reset_on_new_day(self):
        """When a new day begins, daily_total_seconds should be reset to 0."""
        time_log = TimeLog.objects.create(
            student=self.student,
            daily_total_seconds=300,
            weekly_total_seconds=1200,
            last_reset_week=timezone.now().isocalendar()[1],
        )
        # Force last_reset_date to yesterday
        yesterday = date.today() - timedelta(days=1)
        TimeLog.objects.filter(pk=time_log.pk).update(last_reset_date=yesterday)
        time_log.refresh_from_db()

        time_log.reset_daily_if_needed()
        time_log.refresh_from_db()
        self.assertEqual(time_log.daily_total_seconds, 0)

    # -- weekly reset --
    def test_weekly_reset_on_new_week(self):
        """When a new ISO week begins, weekly_total_seconds should be reset to 0."""
        from django.utils.timezone import localtime
        current_week = localtime(timezone.now()).isocalendar()[1]
        previous_week = current_week - 1 if current_week > 1 else 52
        time_log = TimeLog.objects.create(
            student=self.student,
            daily_total_seconds=100,
            weekly_total_seconds=5000,
            last_reset_week=previous_week,
        )

        time_log.reset_weekly_if_needed()
        time_log.refresh_from_db()
        self.assertEqual(time_log.weekly_total_seconds, 0)
        self.assertEqual(time_log.last_reset_week, current_week)
