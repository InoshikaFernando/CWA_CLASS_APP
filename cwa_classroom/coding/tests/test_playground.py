"""
test_playground.py
~~~~~~~~~~~~~~~~~~
Tests for the standalone online compilers (playgrounds).

Covers:
  - playground_index       GET  /coding/playground/
  - playground             GET  /coding/playground/<lang>/
  - api_playground_run     POST /coding/api/playground-run/

These tools are decoupled from CodingLanguage DB rows, so no seed data
is required beyond an authenticated user.
"""
import json
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

User = get_user_model()

_PISTON_PASS = {'stdout': 'hi\n', 'stderr': '', 'exit_code': 0, 'run_time_seconds': 0.02}


def _post(client, url, payload):
    return client.post(url, data=json.dumps(payload), content_type='application/json')


class TestPlaygroundPages(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='pg_user', password='testpass123', email='pg_user@test.com',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_index_lists_all_compilers(self):
        resp = self.client.get(reverse('coding:playground_index'))
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode()
        self.assertIn('Python', body)
        self.assertIn('JavaScript', body)
        self.assertIn('HTML / CSS', body)

    def test_index_requires_login(self):
        resp = Client().get(reverse('coding:playground_index'))
        self.assertEqual(resp.status_code, 302)

    def test_python_playground_renders(self):
        resp = self.client.get(reverse('coding:playground', kwargs={'lang': 'python'}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Python Compiler')
        self.assertContains(resp, 'main.py')

    def test_javascript_playground_renders(self):
        resp = self.client.get(reverse('coding:playground', kwargs={'lang': 'javascript'}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'main.js')

    def test_html_css_playground_has_preview_iframe(self):
        resp = self.client.get(reverse('coding:playground', kwargs={'lang': 'html-css'}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ed-preview-frame')
        self.assertContains(resp, 'style.css')

    def test_unknown_language_404(self):
        resp = self.client.get(reverse('coding:playground', kwargs={'lang': 'cobol'}))
        self.assertEqual(resp.status_code, 404)

    def test_playground_url_not_shadowed_by_topic_list(self):
        """The literal /playground/ route must win over the <lang_slug>/ catch-all."""
        match = reverse('coding:playground_index')
        self.assertEqual(match, '/coding/playground/')


class TestApiPlaygroundRun(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            username='pg_run', password='testpass123', email='pg_run@test.com',
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_requires_login(self):
        resp = _post(Client(), reverse('coding:api_playground_run'),
                     {'language': 'python', 'code': 'print(1)'})
        self.assertEqual(resp.status_code, 302)

    def test_get_returns_405(self):
        resp = self.client.get(reverse('coding:api_playground_run'))
        self.assertEqual(resp.status_code, 405)

    def test_malformed_json_returns_400(self):
        resp = self.client.post(reverse('coding:api_playground_run'),
                                data='not-json', content_type='application/json')
        self.assertEqual(resp.status_code, 400)

    def test_missing_code_returns_400(self):
        resp = _post(self.client, reverse('coding:api_playground_run'),
                     {'language': 'python', 'code': '   '})
        self.assertEqual(resp.status_code, 400)

    def test_unsupported_language_returns_400(self):
        resp = _post(self.client, reverse('coding:api_playground_run'),
                     {'language': 'cobol', 'code': 'print(1)'})
        self.assertEqual(resp.status_code, 400)

    def test_html_css_is_not_runnable_server_side(self):
        """HTML/CSS is preview-only and must be rejected by the run endpoint."""
        resp = _post(self.client, reverse('coding:api_playground_run'),
                     {'language': 'html-css', 'code': '<h1>Hi</h1>'})
        self.assertEqual(resp.status_code, 400)

    def test_python_runs_via_piston(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            resp = _post(self.client, reverse('coding:api_playground_run'),
                         {'language': 'python', 'code': 'print("hi")'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['stdout'], 'hi\n')
        mock_rc.assert_called_once_with('python', 'print("hi")', '')

    def test_javascript_runs_via_piston(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            resp = _post(self.client, reverse('coding:api_playground_run'),
                         {'language': 'javascript', 'code': 'console.log("hi")'})
        self.assertEqual(resp.status_code, 200)
        mock_rc.assert_called_once_with('javascript', 'console.log("hi")', '')

    def test_stdin_forwarded(self):
        with patch('coding.execution.run_code', return_value=_PISTON_PASS) as mock_rc:
            _post(self.client, reverse('coding:api_playground_run'),
                  {'language': 'python', 'code': 'print(input())', 'stdin': 'world'})
        mock_rc.assert_called_once_with('python', 'print(input())', 'world')

    def test_piston_error_forwarded_as_200(self):
        err = {'stdout': '', 'stderr': 'boom', 'exit_code': 1, 'error': 'timeout'}
        with patch('coding.execution.run_code', return_value=err):
            resp = _post(self.client, reverse('coding:api_playground_run'),
                         {'language': 'python', 'code': 'while True: pass'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['exit_code'], 1)
