"""
test_scoring.py
~~~~~~~~~~~~~~~
Tests for calculate_coding_points and scoring integration with api_submit_problem.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from coding.models import (
    CodingLanguage,
    CodingProblem,
    CodingTopic,
    ProblemTestCase,
    calculate_coding_points,
)

User = get_user_model()


class TestCalculateCodingPoints(TestCase):

    def test_full_pass_reflects_speed(self):
        self.assertEqual(calculate_coding_points(5, 5, 0), 100.0)
        self.assertLess(calculate_coding_points(5, 5, 15), 100.0)
        self.assertLess(
            calculate_coding_points(5, 5, 30),
            calculate_coding_points(5, 5, 15),
        )

    def test_partial_pass_still_penalises_time(self):
        points = calculate_coding_points(3, 5, 20)
        self.assertLess(points, 100.0)
        self.assertGreater(points, 0.0)


class TestApiScoringRuntime(TestCase):
    """Verifies that scoring uses Piston's run_time_seconds, not time_taken_seconds."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='score_student', password='testpass123',
            email='score_student@test.com',
        )
        cls.lang, _ = CodingLanguage.objects.get_or_create(
            slug='python',
            defaults={'name': 'Python', 'color': '#3b82f6', 'order': 1, 'is_active': True},
        )
        cls.topic, _ = CodingTopic.objects.get_or_create(
            language=cls.lang, slug='scr-variables',
            defaults={'name': 'Variables', 'order': 1, 'is_active': True},
        )
        cls.problem = CodingProblem.objects.create(
            language=cls.lang,
            title='Reverse a String',
            description='Read a string and print it reversed.',
            starter_code='s = input()\n',
            difficulty=1,
            is_active=True,
        )
        ProblemTestCase.objects.create(
            problem=cls.problem,
            input_data='hello', expected_output='olleh',
            is_visible=True, display_order=1, description='Basic word',
        )
        ProblemTestCase.objects.create(
            problem=cls.problem,
            input_data='a', expected_output='a',
            is_visible=False, display_order=2, description='Single char',
        )

    def setUp(self):
        self.client.force_login(self.student)

    def test_api_submit_problem_uses_execution_runtime(self):
        url = reverse('coding:api_submit_problem', args=[self.problem.id])
        code = 'print(input()[::-1])'
        # Both submissions have the same Piston times — score must be identical
        # regardless of the different time_taken_seconds sent by the client.
        piston_results = [
            {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.10},
            {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
            {'stdout': 'olleh', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.10},
            {'stdout': 'a',     'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.05},
        ]
        with patch('coding.execution.run_code') as mock_run_code:
            mock_run_code.side_effect = piston_results

            resp1 = self.client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 500}),
                content_type='application/json',
            )
            self.assertEqual(resp1.status_code, 200)
            data1 = resp1.json()
            self.assertEqual(data1['attempt_points'], calculate_coding_points(2, 2, 0.15))

            resp2 = self.client.post(
                url,
                data=json.dumps({'code': code, 'time_taken_seconds': 10}),
                content_type='application/json',
            )
            self.assertEqual(resp2.status_code, 200)
            data2 = resp2.json()
            self.assertEqual(data2['attempt_points'], calculate_coding_points(2, 2, 0.15))
            self.assertEqual(data2['attempt_points'], data1['attempt_points'])
