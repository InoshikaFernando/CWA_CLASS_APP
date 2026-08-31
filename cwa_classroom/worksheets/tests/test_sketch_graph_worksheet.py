"""Worksheet support for the ``sketch_graph`` question type.

"Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex,
x-axis and y-axis intercepts and equation of the axis of symmetry" is the
question this type exists for. Covered here: the extractor is told to emit it
and the drawing sweep leaves it alone (that sweep is what used to send every one
of them to the teacher), the answer-partial dispatch entry, the interactive
session partial, and the real POST — the view, the stored row and the feedback a
student reads. Mirrors test_table_of_values_worksheet.py and
test_partial_credit_views.py.
"""
import json

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse

from worksheets.models import WorksheetStudentAnswer
from worksheets.services import (
    EXTRACTED_QUESTION_TYPES,
    WORKSHEET_SYSTEM_PROMPT,
    is_unanswerable_construction,
    route_constructions_to_teacher,
)
from worksheets.tests.test_views import SessionDispatchTestBase
from worksheets.views import ANSWER_PARTIAL_MAP

QUESTION_TEXT = (
    'Sketch the graph of y = x² + x - 2 showing the coordinates of the vertex, '
    'x-axis and y-axis intercepts and equation of the axis of symmetry.'
)

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

ALL_RIGHT = {'features': {
    'vertex': '(-0.5, -2.25)', 'x_intercept': '(-2, 0), (1, 0)',
    'y_intercept': '(0, -2)', 'axis_of_symmetry': 'x = -0.5',
}}


class ExtractionRulesTests(SimpleTestCase):
    """The extractor has to reach for this type, and must stop routing these
    questions to the teacher as drawings."""

    def test_the_type_is_one_the_extractor_may_emit(self):
        self.assertIn('sketch_graph', EXTRACTED_QUESTION_TYPES)

    def test_the_prompt_carries_the_rule_and_its_worked_example(self):
        self.assertIn('SKETCH A GRAPH SHOWING ITS KEY FEATURES',
                      WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('sketch_spec', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('axis_of_symmetry', WORKSHEET_SYSTEM_PROMPT)

    def test_a_sketch_with_features_is_no_longer_a_paper_only_drawing(self):
        q = {'question_text': QUESTION_TEXT, 'question_type': 'sketch_graph',
             'validation_type': 'auto', 'answers': []}
        self.assertFalse(is_unanswerable_construction(q))
        questions = [q]
        self.assertEqual(route_constructions_to_teacher(questions), 0)
        self.assertEqual(questions[0]['validation_type'], 'auto')

    def test_a_bare_sketch_instruction_is_still_the_teacher_s(self):
        """Nothing to type means nothing to grade — that one stays a drawing."""
        self.assertTrue(is_unanswerable_construction({
            'question_text': 'Sketch the graph of y = 2x.',
            'question_type': 'extended_answer', 'answers': [],
        }))


class SketchGraphWorksheetPartialTests(SessionDispatchTestBase):

    def _question(self, points=1):
        return self._make_question(
            qtype='sketch_graph', points=points, sketch_spec=SPEC,
            question_text=QUESTION_TEXT)

    def test_in_answer_partial_map(self):
        self.assertTrue(
            ANSWER_PARTIAL_MAP['sketch_graph'].endswith('_answer_sketch_graph.html'))

    def test_answer_partial_renders_interactive(self):
        html = render_to_string(
            'worksheets/partials/_answer_sketch_graph.html',
            {'question': self._question()})
        self.assertIn('data-sk-stage', html)           # interactive stage
        self.assertIn('data-sk-feature', html)         # one box per feature
        self.assertIn('name="text_answer"', html)      # boxes serialise here
        self.assertIn('data-kind="vertex"', html)

    def test_the_answers_never_reach_the_student_widget(self):
        html = render_to_string(
            'worksheets/partials/_answer_sketch_graph.html',
            {'question': self._question()})
        self.assertNotIn('-2.25', html)
        self.assertNotIn('x = -0.5', html)


class SketchGraphWorksheetGradingTests(SessionDispatchTestBase):

    def _question(self, points=1):
        return self._make_question(
            qtype='sketch_graph', points=points, sketch_spec=SPEC,
            question_text=QUESTION_TEXT)

    def _submit(self, question, payload):
        self.client.force_login(self.student)
        assignment, _ = self._make_worksheet_with_question(question)
        self._make_submission(assignment)
        resp = self.client.post(
            reverse('worksheets:answer', args=[assignment.pk]),
            {'content_id': question.pk, 'subject_slug': 'mathematics',
             'text_answer': json.dumps(payload)},
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        row = WorksheetStudentAnswer.objects.get(
            content_id=question.pk, subject_slug='mathematics')
        return resp, row

    def test_every_feature_right_is_full_marks(self):
        _, row = self._submit(self._question(), ALL_RIGHT)
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, 1.0)

    def test_three_features_of_four_earns_three_quarters(self):
        payload = {'features': dict(ALL_RIGHT['features'], vertex='(0, 0)')}
        _, row = self._submit(self._question(), payload)
        self.assertFalse(row.is_correct)   # full marks still means every feature
        self.assertEqual(row.points_earned, 0.75)
        self.assertEqual(row.answer_data['parts_correct'], 3)

    def test_the_feedback_names_the_feature_that_cost_the_mark(self):
        payload = {'features': dict(ALL_RIGHT['features'], vertex='(0, 0)')}
        resp, _ = self._submit(self._question(), payload)
        html = resp.content.decode()
        self.assertIn('Partially correct', html)
        self.assertIn('3 of the 4 features are right.', html)
        self.assertIn('Vertex (turning point)', html)
        self.assertIn('(-0.5, -2.25)', html)

    def test_an_untouched_question_scores_zero_but_is_still_explained(self):
        _, row = self._submit(self._question(), {'features': {}})
        self.assertFalse(row.is_correct)
        self.assertEqual(row.points_earned, 0.0)
        self.assertEqual(len(row.answer_data['parts']), 4)
