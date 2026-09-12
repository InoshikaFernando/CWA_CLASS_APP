"""``number_line`` question type through the AI-import path.

Proves the importer turns a number_line payload into a question with the stored
number_line_spec and NO answer rows (it grades from the spec), that a malformed
spec is skipped rather than imported broken, that ``measure`` and ``number_line``
are in the extraction enum, and that the preview edit step round-trips the JSON
spec. Mirrors test_plane_graph_import.py.
"""
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import (
    CLASSIFICATION_TOOL,
    _build_classification_prompt,
    save_questions_from_session,
)
from maths.models import Question


def _payload(q):
    return {
        'year_level': 4, 'subject': 'Mathematics', 'strand': 'Number',
        'topic': 'Number Line', 'questions': [q],
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_measure_and_number_line(self):
        enum = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                ["items"]["properties"]["question_type"]["enum"])
        self.assertIn('measure', enum)
        self.assertIn('number_line', enum)

    def test_number_line_spec_field_present(self):
        props = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                 ["items"]["properties"])
        self.assertIn('number_line_spec', props)

    def test_prompt_keeps_the_mark_and_read_guidance(self):
        prompt = _build_classification_prompt([], [])
        self.assertIn('number_line', prompt)
        self.assertIn('put the value(s) in target', prompt)
        self.assertIn('put the marked position(s) in given', prompt)

    def test_prompt_asks_for_an_inequality_block_not_a_tick_list(self):
        # A "graph the inequality" answer is a ray: enumerating its ticks is
        # what dropped the boundary tick and failed correct answers.
        prompt = _build_classification_prompt([], [])
        self.assertIn('do NOT list its ticks in target', prompt)
        # The JSON example must reach the model as JSON. It lives in an
        # f-string, so its braces are escaped in source — a regression here
        # renders {{"op": ...}} or raises on build.
        self.assertIn('inequality {"op": "<="|"<"|">="|">", "value": -2}', prompt)
        self.assertNotIn('{{', prompt)


class SaveNumberLineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'nl_super', 'nl_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})

    def _save(self, q):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='nl.pdf', extracted_data=_payload(q))
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_mark_imports_with_spec_and_no_answers(self):
        result = self._save({
            'question_text': 'Draw a number line from -3 to 7 and mark 2.',
            'question_type': 'number_line',
            'number_line_spec': {'min': -3, 'max': 7, 'step': 1,
                                 'mode': 'mark', 'target': [2]},
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        q = Question.objects.get(question_type='number_line')
        self.assertEqual(q.number_line_spec['target'], [2])
        self.assertEqual(q.answers.count(), 0)

    def test_read_imports_with_spec(self):
        result = self._save({
            'question_text': 'What value does the arrow point to?',
            'question_type': 'number_line',
            'number_line_spec': {'min': 0, 'max': 10, 'step': 2,
                                 'mode': 'read', 'given': [6]},
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        q = Question.objects.get(question_type='number_line')
        self.assertEqual(q.number_line_spec['given'], [6])
        self.assertEqual(q.answers.count(), 0)

    def test_invalid_spec_is_skipped(self):
        result = self._save({
            'question_text': 'Broken number line.',
            'question_type': 'number_line',
            'number_line_spec': {'min': 0, 'max': 10, 'step': 2,
                                 'mode': 'mark', 'target': [3]},  # 3 off-tick
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Broken number line.').exists())


class PreviewRoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'nl_prev', 'nl_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})

    def test_post_preserves_number_line_spec(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='nl.pdf',
            extracted_data=_payload({
                'question_text': 'Mark 2.',
                'question_type': 'number_line',
                'number_line_spec': {'min': -3, 'max': 7, 'step': 1,
                                     'mode': 'mark', 'target': [2]},
                'difficulty': 1, 'points': 1,
            }),
        )
        self.client.force_login(self.user)
        edited = {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [5]}
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '4', 'subject': 'Mathematics', 'strand': 'Number',
                'topic': 'Number Line',
                'q_0_include': 'on', 'q_0_text': 'Mark 2.',
                'q_0_type': 'number_line', 'q_0_difficulty': '1', 'q_0_points': '1',
                'q_0_year_level': '4', 'q_0_subject': 'Mathematics',
                'q_0_strand': 'Number', 'q_0_topic': 'Number Line',
                'q_0_number_line_spec': json.dumps(edited),
            },
        )
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        q = session.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'number_line')
        self.assertEqual(q['number_line_spec']['target'], [5])
