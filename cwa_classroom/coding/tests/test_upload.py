"""
test_upload.py
~~~~~~~~~~~~~~
Tests for subject-aware question upload — Coding subject path.

Coverage:
  1. CodingExerciseParser unit tests (parser in isolation)
     - Valid JSON creates CodingExercise records
     - Duplicate title → update not insert
     - Missing required fields return errors
     - Unknown language slug returns descriptive error
     - Unknown topic slug returns descriptive error
     - Invalid level returns descriptive error
     - Empty exercises array returns error
     - display_order defaults to array index when omitted
     - starter_code / hints default to empty string when omitted

  2. Upload view integration tests (POST /upload-questions/)
     - Coding upload creates CodingExercise records
     - Coding upload with unknown language returns 200 + errors
     - Coding upload with invalid JSON returns 200 + errors
     - Template download returns valid JSON for coding subject
     - Mathematics upload still works after refactor (regression guard)
"""

from __future__ import annotations

import io
import json

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from accounts.models import Role
from coding.models import CodingExercise, CodingLanguage, CodingTopic, TopicLevel

User = get_user_model()


# ---------------------------------------------------------------------------
# Fixtures helpers
# ---------------------------------------------------------------------------

def _make_language(slug='python', name='Python'):
    lang, _ = CodingLanguage.objects.get_or_create(
        slug=slug,
        defaults={
            'name': name,
            'color': '#3776AB',
            'order': 1,
            'is_active': True,
            'description': f'{name} programming language',
        },
    )
    return lang


def _make_topic(language, slug='loops', name='Loops'):
    topic, _ = CodingTopic.objects.get_or_create(
        language=language,
        slug=slug,
        defaults={'name': name, 'order': 1},
    )
    return topic


def _coding_payload(
    language='python',
    topic='loops',
    level='beginner',
    exercises=None,
) -> bytes:
    if exercises is None:
        exercises = [
            {
                'title': 'For Loop: Print 1-5',
                'instructions': 'Use a for loop to print numbers 1 through 5.',
                'starter_code': 'for i in range(?, ?):\n    print(?)\n',
                'expected_output': '1\n2\n3\n4\n5',
                'hints': 'range(1, 6) generates 1-5',
                'display_order': 1,
            }
        ]
    return json.dumps({
        'subject': 'coding',
        'language': language,
        'topic': topic,
        'level': level,
        'exercises': exercises,
    }).encode()


# ---------------------------------------------------------------------------
# 1. CodingExerciseParser — unit tests
# ---------------------------------------------------------------------------

class CodingExerciseParserTests(TestCase):
    """Parser unit tests — no HTTP layer."""

    @classmethod
    def setUpTestData(cls):
        cls.lang = _make_language()
        cls.topic = _make_topic(cls.lang)

    def _run_parser(self, payload_bytes, filename='exercises.json'):
        from classroom.upload_services import CodingExerciseParser
        parser = CodingExerciseParser()
        f = io.BytesIO(payload_bytes)
        f.name = filename
        return parser.process(f, user=None, post_data={})

    def test_valid_payload_inserts_exercise(self):
        result = self._run_parser(_coding_payload())
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(len(result['errors']), 0)
        self.assertTrue(
            CodingExercise.objects.filter(
                topic_level__topic=self.topic,
                topic_level__level_choice='beginner',
                title='For Loop: Print 1-5',
            ).exists()
        )

    def test_duplicate_title_updates_not_inserts(self):
        self._run_parser(_coding_payload())
        result = self._run_parser(_coding_payload())
        self.assertEqual(result['updated'], 1)
        self.assertEqual(result['inserted'], 0)
        count = CodingExercise.objects.filter(
            topic_level__topic=self.topic,
            topic_level__level_choice='beginner',
            title='For Loop: Print 1-5',
        ).count()
        self.assertEqual(count, 1)

    def test_missing_title_returns_error(self):
        payload = _coding_payload(exercises=[{
            'instructions': 'Do something.',
            'expected_output': 'ok',
        }])
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('title' in e for e in result['errors']))

    def test_missing_instructions_returns_error(self):
        payload = _coding_payload(exercises=[{
            'title': 'My Exercise',
            'expected_output': 'ok',
        }])
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('instructions' in e for e in result['errors']))

    def test_missing_expected_output_defaults_to_empty(self):
        """expected_output is optional; omitting it creates the exercise with '' output."""
        payload = _coding_payload(exercises=[{
            'title': 'My Exercise',
            'instructions': 'Do something.',
        }])
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 0)
        self.assertEqual(result['inserted'], 1)
        ex = CodingExercise.objects.get(title='My Exercise')
        self.assertEqual(ex.expected_output, '')

    def test_unknown_language_slug_returns_descriptive_error(self):
        payload = _coding_payload(language='rust')
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('rust' in e.lower() for e in result['errors']))
        self.assertTrue(any('available' in e.lower() for e in result['errors']))

    def test_unknown_topic_slug_returns_descriptive_error(self):
        payload = _coding_payload(topic='recursion')
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('recursion' in e.lower() for e in result['errors']))

    def test_invalid_level_returns_descriptive_error(self):
        payload = _coding_payload(level='expert')
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('expert' in e.lower() for e in result['errors']))
        self.assertTrue(any('beginner' in e.lower() for e in result['errors']))

    def test_empty_exercises_array_returns_error(self):
        payload = _coding_payload(exercises=[])
        result = self._run_parser(payload)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(len(result['errors']) > 0)

    def test_display_order_defaults_to_array_index(self):
        payload = _coding_payload(exercises=[
            {'title': 'Ex One', 'instructions': 'Do A.', 'expected_output': 'A'},
            {'title': 'Ex Two', 'instructions': 'Do B.', 'expected_output': 'B'},
        ])
        self._run_parser(payload)
        ex1 = CodingExercise.objects.get(topic_level__topic=self.topic, title='Ex One')
        ex2 = CodingExercise.objects.get(topic_level__topic=self.topic, title='Ex Two')
        self.assertEqual(ex1.order, 1)  # array index 1 (1-based)
        self.assertEqual(ex2.order, 2)

    def test_optional_fields_default_to_empty_string(self):
        payload = _coding_payload(exercises=[{
            'title': 'Minimal',
            'instructions': 'Do minimal.',
            'expected_output': 'done',
        }])
        self._run_parser(payload)
        ex = CodingExercise.objects.get(topic_level__topic=self.topic, title='Minimal')
        self.assertEqual(ex.starter_code, '')
        self.assertEqual(ex.hints, '')

    def test_result_detail_contains_language_topic_level(self):
        result = self._run_parser(_coding_payload())
        detail = result['detail']
        self.assertIn('language', detail)
        self.assertIn('topic', detail)
        self.assertIn('level', detail)
        self.assertEqual(detail['level'], 'beginner')

    def test_multiple_exercises_in_one_file(self):
        exercises = [
            {'title': f'Ex {i}', 'instructions': f'Do {i}.', 'expected_output': str(i)}
            for i in range(1, 6)
        ]
        payload = _coding_payload(exercises=exercises)
        result = self._run_parser(payload)
        self.assertEqual(result['inserted'], 5)
        self.assertEqual(result['failed'], 0)

    def test_invalid_json_returns_error(self):
        f = io.BytesIO(b'this is not json {{{')
        f.name = 'bad.json'
        from classroom.upload_services import CodingExerciseParser
        result = CodingExerciseParser().process(f, user=None, post_data={})
        self.assertGreater(result['failed'], 0)
        self.assertTrue(len(result['errors']) > 0)

    def test_all_three_levels_accepted(self):
        for level in ('beginner', 'intermediate', 'advanced'):
            payload = _coding_payload(
                level=level,
                exercises=[{
                    'title': f'Level test {level}',
                    'instructions': 'Test.',
                    'expected_output': 'ok',
                }],
            )
            result = self._run_parser(payload)
            self.assertEqual(result['failed'], 0, f'Level "{level}" was rejected')


# ---------------------------------------------------------------------------
# 2. Upload view integration tests
# ---------------------------------------------------------------------------

class CodingUploadViewTests(TestCase):
    """End-to-end tests through the /upload-questions/ view."""

    @classmethod
    def setUpTestData(cls):
        cls.role_hoi, _ = Role.objects.get_or_create(
            name=Role.HEAD_OF_INSTITUTE,
            defaults={'display_name': 'Head of Institute'},
        )
        cls.superuser = User.objects.create_superuser(
            'cu_super', 'wlhtestmails+cu_super@gmail.com', 'password1!',
        )
        cls.hoi_user = User.objects.create_user(
            'cu_hoi', 'wlhtestmails+cu_hoi@gmail.com', 'password1!',
        )
        cls.hoi_user.roles.add(cls.role_hoi)

        cls.lang = _make_language()
        cls.topic = _make_topic(cls.lang)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.superuser)

    def _post_coding(self, payload_bytes, filename='exercises.json'):
        f = io.BytesIO(payload_bytes)
        f.name = filename
        return self.client.post(
            reverse('upload_questions'),
            {'subject': 'coding', 'upload_file': f},
        )

    # ── Success cases ──────────────────────────────────────────────────

    def test_coding_upload_creates_exercise_records(self):
        resp = self._post_coding(_coding_payload())
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertEqual(results['inserted'], 1)
        self.assertEqual(results['failed'], 0)
        self.assertEqual(results['subject'], 'coding')

    def test_coding_upload_subject_shown_in_results(self):
        resp = self._post_coding(_coding_payload())
        self.assertEqual(resp.context['selected_subject'], 'coding')

    def test_coding_upload_exercise_saved_to_correct_topic_and_level(self):
        self._post_coding(_coding_payload())
        self.assertTrue(
            CodingExercise.objects.filter(
                topic_level__topic=self.topic,
                topic_level__level_choice='beginner',
                title='For Loop: Print 1-5',
            ).exists()
        )

    def test_bulk_upload_50_exercises(self):
        exercises = [
            {
                'title': f'Bulk Exercise {i:02d}',
                'instructions': f'Do task {i}.',
                'expected_output': str(i),
                'display_order': i,
            }
            for i in range(1, 51)
        ]
        resp = self._post_coding(_coding_payload(exercises=exercises))
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertEqual(results['inserted'], 50)
        self.assertEqual(results['failed'], 0)

    def test_duplicate_upload_updates_exercise(self):
        self._post_coding(_coding_payload())
        resp = self._post_coding(_coding_payload())
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertEqual(results['updated'], 1)
        self.assertEqual(results['inserted'], 0)

    # ── Error cases ────────────────────────────────────────────────────

    def test_unknown_language_returns_200_with_error(self):
        resp = self._post_coding(_coding_payload(language='cobol'))
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertGreater(results['failed'], 0)
        self.assertTrue(any('cobol' in e.lower() for e in results['errors']))

    def test_unknown_topic_returns_200_with_error(self):
        resp = self._post_coding(_coding_payload(topic='big-o-notation'))
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertGreater(results['failed'], 0)

    def test_invalid_level_returns_200_with_error(self):
        resp = self._post_coding(_coding_payload(level='master'))
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertGreater(results['failed'], 0)
        self.assertTrue(any('master' in e.lower() for e in results['errors']))

    def test_missing_file_redirects(self):
        resp = self.client.post(
            reverse('upload_questions'),
            {'subject': 'coding'},
        )
        self.assertEqual(resp.status_code, 302)

    def test_unknown_subject_slug_redirects(self):
        f = io.BytesIO(b'{}')
        f.name = 'x.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'subject': 'science', 'upload_file': f},
        )
        self.assertEqual(resp.status_code, 302)

    def test_unauthenticated_redirects_to_login(self):
        self.client.logout()
        resp = self.client.get(reverse('upload_questions'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url.lower())

    # ── Template download ──────────────────────────────────────────────

    def test_template_download_coding_returns_json_file(self):
        resp = self.client.get(
            reverse('upload_questions_template'),
            {'subject': 'coding'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/json')
        self.assertIn('attachment', resp['Content-Disposition'])
        self.assertIn('coding', resp['Content-Disposition'])
        data = json.loads(resp.content)
        self.assertEqual(data['subject'], 'coding')
        self.assertIn('exercises', data)
        self.assertTrue(len(data['exercises']) > 0)

    def test_template_download_mathematics_returns_json_file(self):
        resp = self.client.get(
            reverse('upload_questions_template'),
            {'subject': 'mathematics'},
        )
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertIn('questions', data)

    def test_template_download_unknown_subject_returns_404(self):
        resp = self.client.get(
            reverse('upload_questions_template'),
            {'subject': 'unknown'},
        )
        self.assertEqual(resp.status_code, 404)

    # ── Help partial ───────────────────────────────────────────────────

    def test_help_partial_coding_returns_200(self):
        resp = self.client.get(
            reverse('upload_questions_help'),
            {'subject': 'coding'},
        )
        self.assertEqual(resp.status_code, 200)

    def test_help_partial_mathematics_returns_200(self):
        resp = self.client.get(
            reverse('upload_questions_help'),
            {'subject': 'mathematics'},
        )
        self.assertEqual(resp.status_code, 200)

    # ── Regression: maths still works ─────────────────────────────────

    def test_maths_upload_still_works_after_refactor(self):
        """Zero regression: maths upload path unchanged."""
        from classroom.models import Level as ClassroomLevel, Subject
        Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        ClassroomLevel.objects.get_or_create(
            level_number=4, defaults={'display_name': 'Year 4'},
        )
        payload = json.dumps({
            'topic': 'Fractions',
            'year_level': 4,
            'questions': [{
                'question_text': 'What is 1/2 + 1/4?',
                'question_type': 'multiple_choice',
                'difficulty': 1,
                'points': 1,
                'answers': [
                    {'text': '3/4', 'is_correct': True, 'order': 1},
                    {'text': '1/2', 'is_correct': False, 'order': 2},
                ],
            }],
        }).encode()
        f = io.BytesIO(payload)
        f.name = 'questions.json'
        resp = self.client.post(
            reverse('upload_questions'),
            {'subject': 'mathematics', 'upload_file': f},
        )
        self.assertEqual(resp.status_code, 200)
        results = resp.context['upload_results_list'][0]
        self.assertEqual(results['subject'], 'mathematics')
        self.assertEqual(results['failed'], 0)
