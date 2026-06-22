"""Cartesian-plane / read-graph question types through the AI-import path.

Proves the importer turns plot_points / read_graph payloads into questions with
the right structured spec and NO answer rows (they grade from the spec), that a
malformed plane_spec is skipped rather than imported broken, and that the preview
edit step round-trips the JSON spec without clobbering the type. Mirrors
test_column_import.py. No Anthropic API is involved — extraction happens upstream;
these test the save/preview steps only.
"""
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import CLASSIFICATION_TOOL, save_questions_from_session
from maths.models import Question


def _payload(q):
    return {
        'year_level': 4, 'subject': 'Mathematics', 'strand': 'Geometry',
        'topic': 'Coordinates', 'questions': [q],
    }


def _plane_spec(mode='points', target=None):
    return {
        'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
        'mode': mode,
        'target': target or {'points': [[3, -2], [1, 4]]},
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_new_types(self):
        enum = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                ["items"]["properties"]["question_type"]["enum"])
        for t in ('plot_points', 'plot_line', 'identify_coords', 'read_graph'):
            self.assertIn(t, enum)

    def test_spec_fields_present(self):
        props = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                 ["items"]["properties"])
        self.assertIn('plane_spec', props)
        self.assertIn('graph_spec', props)
        self.assertIn('numeric_answer', props)


class SavePlaneTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'plane_super', 'plane_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})

    def _save(self, q):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g4.pdf', extracted_data=_payload(q))
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_plot_points_imports_with_spec_and_no_answers(self):
        result = self._save({
            'question_text': 'Plot the points.',
            'question_type': 'plot_points',
            'plane_spec': _plane_spec(),
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        q = Question.objects.get(question_text='Plot the points.')
        self.assertEqual(q.question_type, 'plot_points')
        self.assertEqual(q.plane_spec['target']['points'], [[3, -2], [1, 4]])
        self.assertEqual(q.answers.count(), 0)        # graded from the spec

    def test_read_graph_imports_numeric_fields_no_answers(self):
        result = self._save({
            'question_text': 'How far had the car travelled at 40 minutes?',
            'question_type': 'read_graph',
            'numeric_answer': 130, 'answer_tolerance': 5, 'answer_unit': 'km',
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        q = Question.objects.get(question_type='read_graph')
        self.assertEqual(int(q.numeric_answer), 130)
        self.assertEqual(int(q.answer_tolerance), 5)
        self.assertEqual(q.answer_unit, 'km')
        self.assertEqual(q.answers.count(), 0)

    def test_invalid_plane_spec_is_skipped(self):
        result = self._save({
            'question_text': 'Broken plane.',
            'question_type': 'plot_points',
            'plane_spec': {'bounds': {'xmin': 5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                           'mode': 'points', 'target': {'points': [[0, 0]]}},
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Broken plane.').exists())

    def test_read_graph_without_numeric_answer_is_skipped(self):
        result = self._save({
            'question_text': 'No value.',
            'question_type': 'read_graph',
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='No value.').exists())


class PreviewRoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'plane_prev', 'plane_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=4, defaults={'display_name': 'Year 4'})

    def test_post_preserves_plane_spec(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='g4.pdf',
            extracted_data=_payload({
                'question_text': 'Plot the points.',
                'question_type': 'plot_points',
                'plane_spec': _plane_spec(),
                'difficulty': 1, 'points': 1,
            }),
        )
        self.client.force_login(self.user)
        edited = _plane_spec(target={'points': [[2, 2]]})
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '4', 'subject': 'Mathematics', 'strand': 'Geometry',
                'topic': 'Coordinates',
                'q_0_include': 'on', 'q_0_text': 'Plot the points.',
                'q_0_type': 'plot_points', 'q_0_difficulty': '1', 'q_0_points': '1',
                'q_0_year_level': '4', 'q_0_subject': 'Mathematics',
                'q_0_strand': 'Geometry', 'q_0_topic': 'Coordinates',
                'q_0_plane_spec': json.dumps(edited),
            },
        )
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        q = session.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'plot_points')
        self.assertEqual(q['plane_spec']['target']['points'], [[2, 2]])
