"""``sketch_graph`` question type through the AI-import path.

"Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex,
x-axis and y-axis intercepts and equation of the axis of symmetry." The app
cannot take a drawn curve, but the marks are for the features the stem names —
so the type is imported with the spec it is graded from and NO answer rows.

Proves the enum offers it, the importer stores the spec, a malformed spec is
skipped rather than imported broken, and the preview edit step round-trips the
JSON spec. Mirrors test_number_line_import.py.
"""
import json

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import CLASSIFICATION_TOOL, save_questions_from_session
from maths.models import Question


SPEC = {
    'equation': 'y = x^2 + x - 2',
    'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
    'curve': {'type': 'quadratic', 'a': 1, 'b': 1, 'c': -2},
    'features': [
        {'kind': 'vertex', 'points': [[-0.5, -2.25]]},
        {'kind': 'x_intercept', 'points': [[-2, 0], [1, 0]]},
        {'kind': 'y_intercept', 'points': [[0, -2]]},
        {'kind': 'axis_of_symmetry', 'value': -0.5},
    ],
}

TEXT = ('Sketch the graph of y = x^2 + x - 2 showing the coordinates of the '
        'vertex, x-axis and y-axis intercepts and equation of the axis of '
        'symmetry.')


def _payload(q):
    return {
        'year_level': 10, 'subject': 'Mathematics', 'strand': 'Algebra',
        'topic': 'Quadratics', 'questions': [q],
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_sketch_graph(self):
        enum = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                ["items"]["properties"]["question_type"]["enum"])
        self.assertIn('sketch_graph', enum)

    def test_sketch_spec_field_present(self):
        props = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                 ["items"]["properties"])
        self.assertIn('sketch_spec', props)

    def test_the_prompt_tells_the_model_when_to_use_it(self):
        from ai_import.services import _build_classification_prompt
        prompt = _build_classification_prompt([], [])
        self.assertIn('sketch_graph', prompt)
        self.assertIn('axis_of_symmetry', prompt)


class SaveSketchGraphTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'sk_super', 'sk_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=10, defaults={'display_name': 'Year 10'})

    def _save(self, q):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='sk.pdf', extracted_data=_payload(q))
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_it_imports_with_its_spec_and_no_answers(self):
        result = self._save({
            'question_text': TEXT, 'question_type': 'sketch_graph',
            'sketch_spec': SPEC, 'difficulty': 2, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        q = Question.objects.get(question_type='sketch_graph')
        self.assertEqual(len(q.sketch_spec['features']), 4)
        self.assertEqual(q.answers.count(), 0)

    def test_the_imported_question_grades_its_sketch_and_its_features(self):
        self._save({
            'question_text': TEXT, 'question_type': 'sketch_graph',
            'sketch_spec': SPEC, 'difficulty': 2, 'points': 1,
        })
        q = Question.objects.get(question_type='sketch_graph')
        grade = q.grade_text_answer_parts(json.dumps({
            'features': {
                'vertex': '(-0.5, -2.25)', 'x_intercept': '(-2, 0), (1, 0)',
                'y_intercept': '(0, -2)', 'axis_of_symmetry': 'x = -0.5',
            },
            # The imported plane is something the student can sketch on, and the
            # sketch is marked with the boxes.
            'points': [[-2, 0], [-1, -2], [1, 0]],
        }))
        self.assertTrue(grade.is_correct)
        self.assertEqual(grade.total, 5)

    def test_invalid_spec_is_skipped(self):
        result = self._save({
            'question_text': 'Broken sketch.', 'question_type': 'sketch_graph',
            # A vertex the declared plane cannot show — a mis-read, and the
            # student would be marked against it.
            'sketch_spec': dict(SPEC, features=[
                {'kind': 'vertex', 'points': [[-40, 0]]}]),
            'difficulty': 2, 'points': 1,
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertFalse(Question.objects.filter(question_text='Broken sketch.').exists())


class PreviewRoundTripTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'sk_prev', 'sk_prev@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=10, defaults={'display_name': 'Year 10'})

    def test_post_preserves_sketch_spec(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='sk.pdf',
            extracted_data=_payload({
                'question_text': TEXT, 'question_type': 'sketch_graph',
                'sketch_spec': SPEC, 'difficulty': 2, 'points': 1,
            }),
        )
        self.client.force_login(self.user)
        edited = dict(SPEC, features=[{'kind': 'vertex', 'points': [[-0.5, -2.25]]}])
        resp = self.client.post(
            reverse('ai_import:preview', args=[session.pk]),
            data={
                'year_level': '10', 'subject': 'Mathematics', 'strand': 'Algebra',
                'topic': 'Quadratics',
                'q_0_include': 'on', 'q_0_text': TEXT,
                'q_0_type': 'sketch_graph', 'q_0_difficulty': '2', 'q_0_points': '1',
                'q_0_year_level': '10', 'q_0_subject': 'Mathematics',
                'q_0_strand': 'Algebra', 'q_0_topic': 'Quadratics',
                'q_0_sketch_spec': json.dumps(edited),
            },
        )
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        q = session.extracted_data['questions'][0]
        self.assertEqual(q['question_type'], 'sketch_graph')
        self.assertEqual(len(q['sketch_spec']['features']), 1)

    def test_the_preview_page_offers_the_spec_editor(self):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='sk.pdf',
            extracted_data=_payload({
                'question_text': TEXT, 'question_type': 'sketch_graph',
                'sketch_spec': SPEC, 'difficulty': 2, 'points': 1,
            }),
        )
        self.client.force_login(self.user)
        html = self.client.get(
            reverse('ai_import:preview', args=[session.pk])).content.decode()
        self.assertIn('q_0_sketch_spec', html)
