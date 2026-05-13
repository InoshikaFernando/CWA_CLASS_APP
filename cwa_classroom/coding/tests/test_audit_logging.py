"""
coding/tests/test_audit_logging.py — Audit logging tests for coding views (CPP-270).
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from audit.models import AuditLog
from classroom.models import School, SchoolStudent
from coding.models import (
    CodingExercise,
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    ProblemTestCase,
    StudentExerciseSubmission,
    StudentProblemSubmission,
    TopicLevel,
)

User = get_user_model()


class CodingAuditLoggingTestBase(TestCase):
    """Shared fixtures for coding audit tests."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Code School')
        cls.student = User.objects.create_user(
            username='codestudent', password='pass1234', email='cs@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )

        cls.python_lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={
                'name': 'Python', 'color': '#3b82f6', 'order': 1,
                'is_active': True,
            },
        )
        cls.topic = CodingTopic.objects.create(
            language=cls.python_lang, name='Basics', slug='basics', is_active=True,
        )
        cls.topic_level = TopicLevel.objects.create(
            topic=cls.topic, level_choice=CodingExercise.BEGINNER,
        )

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()


class TestCodingExerciseQuizAuditLog(CodingAuditLoggingTestBase):
    """Quiz-type exercise submission logs coding_exercise_submitted."""

    def test_quiz_exercise_submit_logs_event(self):
        exercise = CodingExercise.objects.create(
            topic_level=self.topic_level,
            title='What prints?',
            description='What does print(1+1) output?',
            question_type='short_answer',
            correct_short_answer='2',
            is_active=True,
        )

        self.client.login(username='codestudent', password='pass1234')
        url = reverse('coding:exercise_detail', kwargs={
            'lang_slug': 'python', 'exercise_id': exercise.id,
        })
        resp = self.client.post(url, {'quiz_answer': '2'})
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='coding_exercise_submitted').first()
        self.assertIsNotNone(log, 'No coding_exercise_submitted audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.category, 'data_change')
        self.assertEqual(log.detail['exercise_id'], exercise.id)
        self.assertTrue(log.detail['is_completed'])


class TestCodingProblemAuditLog(CodingAuditLoggingTestBase):
    """Problem submission logs coding_problem_submitted."""

    @patch('coding.execution.run_code')
    def test_problem_submit_logs_event(self, mock_run):
        mock_run.return_value = {
            'stdout': 'olleh', 'stderr': '', 'exit_code': 0,
            'run_time_seconds': 0.01,
        }

        problem = CodingProblem.objects.create(
            language=self.python_lang,
            title='Reverse String',
            description='Reverse a string.',
            starter_code='def reverse(s): pass',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=problem,
            input_data='hello',
            expected_output='olleh',
            is_visible=True,
            display_order=1,
        )

        self.client.login(username='codestudent', password='pass1234')
        url = reverse('coding:api_submit_problem', kwargs={'problem_id': problem.id})
        resp = self.client.post(
            url,
            data=json.dumps({
                'code': 'def reverse(s): return s[::-1]\nprint(reverse(input()))',
                'language_slug': 'python',
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='coding_problem_submitted').first()
        self.assertIsNotNone(log, 'No coding_problem_submitted audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.detail['problem_id'], problem.id)
        self.assertIn('passed_all', log.detail)
        self.assertIn('attempt_number', log.detail)


class TestCodingAuditResilience(CodingAuditLoggingTestBase):
    """log_event failure must not break exercise submission."""

    def test_log_event_failure_does_not_break_quiz_exercise(self):
        exercise = CodingExercise.objects.create(
            topic_level=self.topic_level,
            title='Resilience Test',
            description='Test question',
            question_type='short_answer',
            correct_short_answer='yes',
            is_active=True,
        )

        self.client.login(username='codestudent', password='pass1234')
        url = reverse('coding:exercise_detail', kwargs={
            'lang_slug': 'python', 'exercise_id': exercise.id,
        })

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.post(url, {'quiz_answer': 'yes'})

        self.assertEqual(resp.status_code, 200)
        self.assertTrue(
            StudentExerciseSubmission.objects.filter(
                student=self.student, exercise=exercise,
            ).exists(),
            'Submission not created when log_event failed',
        )
