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
    ClassRoom,
    Enrollment,
    Level,
    Question,
    StudentAnswer,
    StudentFinalAnswer,
    TimeLog,
    Topic,
)


def _create_student(username="student1", password="testpass123"):
    """Helper: create a student user with the individual_student role."""
    user = CustomUser.objects.create_user(username=username, password=password)
    role, _ = Role.objects.get_or_create(
        name=Role.INDIVIDUAL_STUDENT,
        defaults={"display_name": "Individual Student"},
    )
    UserRole.objects.get_or_create(user=user, role=role)
    return user


def _create_teacher(username="teacher1", password="testpass123"):
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
# 1. BasicFactsTest
# ---------------------------------------------------------------------------
class BasicFactsTest(TestCase):
    """Test the Basic Facts quiz flow (addition levels 100+)."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _create_student()
        # Basic Facts Addition topic + Level 100 (display_level=1)
        cls.addition_topic = Topic.objects.create(name="Addition")
        cls.bf_level = Level.objects.create(level_number=100, title="Addition Level 1")
        cls.bf_level.topics.add(cls.addition_topic)

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="testpass123")

    # -- subtopic page --
    def test_basic_facts_subtopic_page_loads(self):
        url = reverse("maths:basic_facts_subtopic", kwargs={"subtopic_name": "Addition"})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Addition")

    def test_basic_facts_subtopic_invalid_returns_redirect(self):
        url = reverse("maths:basic_facts_subtopic", kwargs={"subtopic_name": "InvalidTopic"})
        resp = self.client.get(url)
        # Invalid subtopic redirects to dashboard
        self.assertEqual(resp.status_code, 302)

    # -- quiz page loads --
    def test_take_basic_facts_quiz_loads(self):
        """GET the basic facts quiz page; it should generate dynamic questions."""
        url = reverse(
            "maths:take_basic_facts_quiz",
            kwargs={"basic_topic": "addition", "display_level": 1},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    # -- submit answers --
    def test_submit_basic_facts_answers(self):
        """POST answers to a basic facts quiz and verify a BasicFactsResult is created."""
        quiz_url = reverse(
            "maths:take_basic_facts_quiz",
            kwargs={"basic_topic": "addition", "display_level": 1},
        )
        # GET first to populate session with generated questions + timer
        resp = self.client.get(quiz_url)
        self.assertEqual(resp.status_code, 200)

        # Extract the session-stored questions to build correct POST data
        session = self.client.session
        questions_data = session.get("quiz_questions_100", [])
        self.assertTrue(len(questions_data) > 0, "Session should contain generated questions")

        post_data = {}
        for q in questions_data:
            # Submit the correct answer so we can verify the score
            post_data[f"question_{q['index']}"] = q["correct_answer"]

        resp = self.client.post(quiz_url, data=post_data)
        self.assertEqual(resp.status_code, 200)

        # A BasicFactsResult should now exist for this student + level
        results = BasicFactsResult.objects.filter(student=self.student, level=self.bf_level)
        self.assertTrue(results.exists(), "BasicFactsResult should be created after submission")
        result = results.first()
        self.assertEqual(result.score, result.total_points, "All answers were correct")


# ---------------------------------------------------------------------------
# 2. TopicsTest
# ---------------------------------------------------------------------------
class TopicsTest(TestCase):
    """Test topic listing, level detail, and taking a regular (non-basic-facts) quiz."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _create_student()
        cls.topic = Topic.objects.create(name="Whole Numbers")
        cls.level = Level.objects.create(level_number=3, title="Year 3")
        cls.level.topics.add(cls.topic)

        # Create several questions so the quiz can load
        for i in range(5):
            _create_question_with_answers(
                cls.level,
                topic=cls.topic,
                question_text=f"What is {i}+1?",
                correct_answer=str(i + 1),
                wrong_answers=[str(i), str(i + 2), str(i + 3)],
            )

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="testpass123")

    def test_topic_list_loads(self):
        url = reverse("maths:topics")
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Whole Numbers")

    def test_level_detail_loads(self):
        url = reverse("maths:level_detail", kwargs={"level_number": self.level.level_number})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_take_quiz_loads(self):
        """GET the quiz page for a level that has database-backed questions."""
        url = reverse("maths:take_quiz", kwargs={"level_number": self.level.level_number})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_take_quiz_post_creates_student_answers(self):
        """POST answers to a regular quiz and verify StudentAnswer rows are created."""
        quiz_url = reverse("maths:take_quiz", kwargs={"level_number": self.level.level_number})

        # GET to populate session
        self.client.get(quiz_url)

        # Build POST data using correct answer IDs
        questions = Question.objects.filter(level=self.level).prefetch_related("answers")
        post_data = {}
        for q in questions:
            correct = q.answers.filter(is_correct=True).first()
            post_data[f"question_{q.id}"] = str(correct.id)

        resp = self.client.post(quiz_url, data=post_data)
        self.assertEqual(resp.status_code, 200)

        # StudentAnswer rows should exist
        sa_count = StudentAnswer.objects.filter(student=self.student).count()
        self.assertGreater(sa_count, 0, "StudentAnswer rows should be created after submission")


# ---------------------------------------------------------------------------
# 3. TimesTablesTest
# ---------------------------------------------------------------------------
class TimesTablesTest(TestCase):
    """Test multiplication and division selection pages and quiz pages."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _create_student()
        # Year 5 has tables 1-12
        cls.level = Level.objects.create(level_number=5, title="Year 5")

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="testpass123")

    def test_multiplication_selection_loads(self):
        url = reverse("maths:multiplication_selection", kwargs={"level_number": 5})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Multiplication")

    def test_division_selection_loads(self):
        url = reverse("maths:division_selection", kwargs={"level_number": 5})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Division")

    def test_multiplication_quiz_loads(self):
        """Load the multiplication quiz for the 5x table."""
        url = reverse(
            "maths:multiplication_quiz",
            kwargs={"level_number": 5, "table_number": 5},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_division_quiz_loads(self):
        """Load the division quiz for the 7x table."""
        url = reverse(
            "maths:division_quiz",
            kwargs={"level_number": 5, "table_number": 7},
        )
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_submit_times_table_answers(self):
        """POST answers to a multiplication quiz and verify results."""
        quiz_url = reverse(
            "maths:multiplication_quiz",
            kwargs={"level_number": 5, "table_number": 5},
        )
        # GET to generate/seed questions
        resp = self.client.get(quiz_url)
        self.assertEqual(resp.status_code, 200)

        # The times_table_quiz view creates Question/Answer rows in the DB.
        # Find the topic created for this table.
        topic_name = "Multiplication (5\u00d7)"
        topic = Topic.objects.filter(name=topic_name).first()
        self.assertIsNotNone(topic, f"Topic '{topic_name}' should be auto-created")

        questions = Question.objects.filter(level=self.level, topic=topic).prefetch_related("answers")
        self.assertTrue(questions.exists(), "Questions should exist for 5x multiplication")

        # Build POST with correct answers and append ?completed=1 (topic_questions completion flow)
        post_data = {}
        for q in questions:
            correct = q.answers.filter(is_correct=True).first()
            if correct:
                post_data[f"question_{q.id}"] = str(correct.id)

        # The topic_questions view uses submit_topic_answer AJAX for individual answers,
        # then redirects with ?completed=1 for scoring.  We can test the submit_topic_answer
        # endpoint directly.
        submit_url = reverse("maths:submit_topic_answer")
        q = questions.first()
        correct_ans = q.answers.filter(is_correct=True).first()
        payload = {
            "question_id": q.id,
            "answer_id": correct_ans.id,
            "attempt_id": str(uuid.uuid4()),
        }
        resp = self.client.post(
            submit_url,
            data=json.dumps(payload),
            content_type="application/json",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertTrue(data["is_correct"])


# ---------------------------------------------------------------------------
# 4. ProgressTrackingTest
# ---------------------------------------------------------------------------
class ProgressTrackingTest(TestCase):
    """Test the student progress dashboard views."""

    @classmethod
    def setUpTestData(cls):
        cls.student = _create_student()
        cls.topic = Topic.objects.create(name="Measurements")
        cls.level = Level.objects.create(level_number=4, title="Year 4")
        cls.level.topics.add(cls.topic)

    def setUp(self):
        self.client = Client()
        self.client.login(username="student1", password="testpass123")

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
        self.client.login(username="student1", password="testpass123")

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
