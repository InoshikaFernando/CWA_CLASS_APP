"""Partial credit on the worksheet answer surface.

A fill-in-the-blank sentence and a table of values ask for several values, so
they are marked one value at a time: the points are the share the student got
right, and the feedback names each gap that cost a mark. This exercises that
through the real POST — the view, the stored row and the rendered feedback —
rather than the grader alone, because the score a child sees is the view's
output, not the grader's.

The grading rules themselves are pinned in maths/tests/test_partial_credit.py.
"""
import json

from django.urls import reverse

from worksheets.models import WorksheetStudentAnswer
from worksheets.tests.test_views import SessionDispatchTestBase

SENTENCE = 'Ten cents is $___ and one dollar is $___.'
BLANK_SPEC = {'blanks': [{'answers': ['0.10']}, {'answers': ['1.00']}]}

# "Write the decimal form of each money value" — four rows, one answer cell each.
MONEY_SPEC = {
    'headers': ['Money value (¢)', 'Decimal form'],
    'rows': [
        [{'given': '56'}, {'answer': '0.56'}],
        [{'given': '84'}, {'answer': '0.84'}],
        [{'given': '7'}, {'answer': '0.07'}],
        [{'given': '96'}, {'answer': '0.96'}],
    ],
}


class PartialCreditAnswerViewTests(SessionDispatchTestBase):

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

    def _table_question(self, points=1):
        return self._make_question(
            qtype='table_of_values', points=points, table_spec=MONEY_SPEC,
            question_text='Write the decimal form of each money value.')

    def _blank_question(self, points=1):
        return self._make_question(
            qtype='fill_blank', points=points, blank_spec=BLANK_SPEC,
            question_text=SENTENCE)

    # ── table of values — the money chart ────────────────────────────────

    def test_three_of_four_cells_earns_three_quarters_of_the_points(self):
        q = self._table_question()
        _, row = self._submit(q, {'cells': {
            '0,1': '0.56', '1,1': '0.84', '2,1': '0.70', '3,1': '0.96'}})
        self.assertFalse(row.is_correct)   # full marks still means every cell
        self.assertEqual(row.points_earned, 0.75)

    def test_the_stored_row_says_which_cell_was_wrong(self):
        q = self._table_question()
        _, row = self._submit(q, {'cells': {
            '0,1': '0.56', '1,1': '0.84', '2,1': '0.70', '3,1': '0.96'}})
        self.assertEqual(row.answer_data['parts_correct'], 3)
        self.assertEqual(row.answer_data['parts_total'], 4)
        wrong = [p for p in row.answer_data['parts'] if not p['is_correct']]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]['label'], 'Decimal form for 7')
        self.assertEqual(wrong[0]['typed'], '0.70')
        self.assertEqual(wrong[0]['expected'], '0.07')

    def test_the_feedback_says_what_went_wrong(self):
        q = self._table_question()
        resp, _ = self._submit(q, {'cells': {
            '0,1': '0.56', '1,1': '0.84', '2,1': '0.70', '3,1': '0.96'}})
        html = resp.content.decode()
        # Amber "partially correct", not the flat red "Not quite right" a
        # nearly-complete chart used to get.
        self.assertIn('Partially correct', html)
        self.assertIn('3 of the 4 cells are right.', html)
        self.assertIn('Decimal form for 7', html)
        self.assertIn('0.07', html)

    def test_every_cell_right_is_still_full_marks(self):
        q = self._table_question()
        _, row = self._submit(q, {'cells': {
            '0,1': '0.56', '1,1': '0.84', '2,1': '0.07', '3,1': '0.96'}})
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, 1.0)

    def test_every_cell_wrong_still_scores_zero(self):
        q = self._table_question()
        _, row = self._submit(q, {'cells': {
            '0,1': '9', '1,1': '9', '2,1': '9', '3,1': '9'}})
        self.assertFalse(row.is_correct)
        self.assertEqual(row.points_earned, 0.0)
        # ...and is still explained gap by gap, which is the part a student
        # can act on.
        self.assertEqual(len(row.answer_data['parts']), 4)

    def test_partial_credit_scales_with_the_questions_points(self):
        q = self._table_question(points=4)
        _, row = self._submit(q, {'cells': {
            '0,1': '0.56', '1,1': '0.84', '2,1': '0.70', '3,1': '0.96'}})
        self.assertEqual(row.points_earned, 3.0)

    # ── fill-in-the-blank sentence ───────────────────────────────────────

    def test_one_blank_of_two_earns_half_the_points(self):
        q = self._blank_question()
        _, row = self._submit(q, {'blanks': ['0.10', '1']})
        self.assertFalse(row.is_correct)
        self.assertEqual(row.points_earned, 0.5)
        self.assertEqual(row.answer_data['parts_correct'], 1)

    def test_an_empty_blank_is_named_in_the_feedback(self):
        q = self._blank_question()
        resp, row = self._submit(q, {'blanks': ['0.10', '']})
        self.assertEqual(row.points_earned, 0.5)
        self.assertIn('you left it empty', resp.content.decode())

    def test_both_blanks_right_is_full_marks(self):
        q = self._blank_question()
        _, row = self._submit(q, {'blanks': ['0.10', '1.00']})
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, 1.0)

    def test_a_payload_that_does_not_line_up_scores_zero(self):
        # Two gaps answered with one value: no per-gap verdict is possible, so
        # it falls back to the all-or-nothing grader rather than inventing a
        # fraction from values that may belong to the wrong gaps.
        q = self._blank_question()
        _, row = self._submit(q, {'blanks': ['0.10']})
        self.assertFalse(row.is_correct)
        self.assertEqual(row.points_earned, 0.0)
        self.assertEqual(row.answer_data, {})
