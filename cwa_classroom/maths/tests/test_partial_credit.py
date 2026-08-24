"""Part-by-part credit for questions that ask for more than one value.

The money-chart case from the field: a table with ten cells, nine filled in
correctly, was marked wrong and scored zero, and the feedback said only "Not
quite right". These tests pin the two halves of the fix — nine tenths of the
marks, and a breakdown that names the tenth cell.

Covers ``maths.partial_credit`` itself, the per-part graders in
``blank_grading`` / ``geometry_grading``, that their all-or-nothing wrappers
still agree with them about what "correct" means, and the ``credit_state``
display filter.
"""
from django.test import SimpleTestCase

from maths.blank_grading import grade_fill_blank, grade_fill_blank_parts
from maths.geometry_grading import grade_table, grade_table_parts
from maths.partial_credit import Part, PartialGrade, points_for
from maths.templatetags.maths_format import credit_state


def _blanks(*values):
    return {'blanks': list(values)}


# The chart from the report: "write the decimal form of each money value",
# eight rows of one answer cell each.
MONEY_SPEC = {
    'headers': ['Money value (¢)', 'Decimal form'],
    'rows': [
        [{'given': '56'}, {'answer': '0.56'}],
        [{'given': '84'}, {'answer': '0.84'}],
        [{'given': '7'}, {'answer': '0.07'}],
        [{'given': '96'}, {'answer': '0.96'}],
    ],
}


def _money_cells(*typed):
    return {'cells': {f'{i},1': v for i, v in enumerate(typed)}}


class PartialGradeTests(SimpleTestCase):
    def _grade(self, correct, total, noun='blank'):
        parts = [
            Part(f'Blank {i + 1}', 'x', 'x', i < correct) for i in range(total)
        ]
        return PartialGrade(parts, noun=noun)

    def test_fraction_is_the_share_of_parts_right(self):
        self.assertEqual(self._grade(9, 10).fraction, 0.9)

    def test_correct_only_when_every_part_is_right(self):
        self.assertFalse(self._grade(9, 10).is_correct)
        self.assertTrue(self._grade(10, 10).is_correct)

    def test_an_empty_grade_is_never_correct(self):
        # A question with no parts is unanswerable — it must not come back
        # "correct" just because nothing failed.
        empty = PartialGrade([])
        self.assertFalse(empty.is_correct)
        self.assertEqual(empty.fraction, 0.0)

    def test_summary_counts_in_words(self):
        self.assertEqual(
            self._grade(9, 10).summary(), '9 of the 10 blanks are right.')

    def test_summary_uses_the_types_own_noun(self):
        self.assertIn('cells', self._grade(2, 3, noun='cell').summary())

    def test_corrections_name_every_wrong_part(self):
        grade = PartialGrade([
            Part('Blank 1', '0.56', '0.56', True),
            Part('Blank 3', '.70', '0.07', False),
            Part('Blank 4', '', '0.96', False),
        ])
        lines = grade.corrections()
        self.assertEqual(len(lines), 2)
        self.assertIn('Blank 3: you wrote ".70" — the answer is "0.07".', lines)
        # An empty gap is described as skipped, not as a wrong value.
        self.assertIn('Blank 4: you left it empty — the answer is "0.96".', lines)

    def test_answer_data_carries_the_fraction_and_the_parts(self):
        data = self._grade(9, 10).as_answer_data()
        self.assertEqual(data['score_fraction'], 0.9)
        self.assertEqual(data['parts_correct'], 9)
        self.assertEqual(data['parts_total'], 10)
        self.assertEqual(len(data['parts']), 10)


class PointsForTests(SimpleTestCase):
    def _grade(self, correct, total):
        return PartialGrade(
            [Part('p', 'x', 'x', i < correct) for i in range(total)])

    def test_nine_of_ten_earns_nine_tenths_of_a_point(self):
        self.assertEqual(points_for(1, self._grade(9, 10)), 0.9)

    def test_scales_to_the_questions_own_points(self):
        self.assertEqual(points_for(5, self._grade(9, 10)), 4.5)

    def test_rounds_to_two_places(self):
        self.assertEqual(points_for(1, self._grade(2, 3)), 0.67)

    def test_full_marks_are_never_shaved_by_rounding(self):
        self.assertEqual(points_for(1, self._grade(3, 3)), 1.0)

    def test_no_grade_is_worth_nothing(self):
        self.assertEqual(points_for(1, None), 0.0)


class FillBlankPartsTests(SimpleTestCase):
    SPEC = {'blanks': [
        {'answers': ['15']},
        {'answers': ['live', 'survive']},
        {'answers': ['67.0']},
    ]}

    def test_every_blank_right_is_full_marks(self):
        grade = grade_fill_blank_parts(self.SPEC, _blanks('15', 'live', '67.0'))
        self.assertTrue(grade.is_correct)
        self.assertEqual(grade.fraction, 1.0)

    def test_two_of_three_scores_two_thirds(self):
        grade = grade_fill_blank_parts(self.SPEC, _blanks('15', 'die', '67.0'))
        self.assertFalse(grade.is_correct)
        self.assertEqual(grade.correct, 2)
        self.assertEqual(grade.total, 3)

    def test_a_blank_left_empty_costs_only_that_blank(self):
        grade = grade_fill_blank_parts(self.SPEC, _blanks('15', '', '67.0'))
        self.assertEqual(grade.correct, 2)
        self.assertEqual(grade.wrong_parts[0].typed, '')

    def test_wrong_part_reports_what_was_typed_and_wanted(self):
        grade = grade_fill_blank_parts(self.SPEC, _blanks('15', 'die', '67.0'))
        wrong = grade.wrong_parts[0]
        self.assertEqual(wrong.label, 'Blank 2')
        self.assertEqual(wrong.typed, 'die')
        # Every accepted spelling is offered, not just the first.
        self.assertEqual(wrong.expected, 'live or survive')

    def test_any_accepted_spelling_counts(self):
        grade = grade_fill_blank_parts(self.SPEC, _blanks('15', 'SURVIVE', '67.0'))
        self.assertTrue(grade.is_correct)

    def test_a_json_string_payload_grades_the_same(self):
        grade = grade_fill_blank_parts(
            self.SPEC, '{"blanks": ["15", "live", "67.0"]}')
        self.assertTrue(grade.is_correct)

    def test_no_verdict_when_the_payload_has_the_wrong_length(self):
        # Three gaps answered with two values cannot be lined up: gap 2's value
        # might be gap 3's, so any per-gap credit would be a coincidence.
        self.assertIsNone(grade_fill_blank_parts(self.SPEC, _blanks('15', 'live')))

    def test_no_verdict_on_an_unusable_spec_or_payload(self):
        self.assertIsNone(grade_fill_blank_parts(None, _blanks('15')))
        self.assertIsNone(grade_fill_blank_parts({'blanks': []}, _blanks('15')))
        self.assertIsNone(grade_fill_blank_parts(self.SPEC, 'not json'))
        self.assertIsNone(grade_fill_blank_parts(self.SPEC, {'nope': []}))

    def test_the_boolean_grader_still_agrees(self):
        for payload in (_blanks('15', 'live', '67.0'),
                        _blanks('15', 'die', '67.0'),
                        _blanks('15', 'live'),
                        'not json'):
            grade = grade_fill_blank_parts(self.SPEC, payload)
            expected = grade is not None and grade.is_correct
            self.assertEqual(grade_fill_blank(self.SPEC, payload), expected)


class TablePartsTests(SimpleTestCase):
    def test_the_money_chart_with_one_cell_wrong(self):
        grade = grade_table_parts(
            MONEY_SPEC, _money_cells('0.56', '0.84', '0.70', '0.96'))
        self.assertFalse(grade.is_correct)
        self.assertEqual(grade.correct, 3)
        self.assertEqual(points_for(1, grade), 0.75)

    def test_a_wrong_cell_is_labelled_by_its_row_and_column(self):
        grade = grade_table_parts(
            MONEY_SPEC, _money_cells('0.56', '0.84', '0.70', '0.96'))
        wrong = grade.wrong_parts[0]
        self.assertEqual(wrong.label, 'Decimal form for 7')
        self.assertEqual(wrong.typed, '0.70')
        self.assertEqual(wrong.expected, '0.07')

    def test_a_missing_cell_costs_only_that_cell(self):
        grade = grade_table_parts(MONEY_SPEC, {'cells': {'0,1': '0.56'}})
        self.assertEqual(grade.correct, 1)
        self.assertEqual(grade.total, 4)
        self.assertEqual(grade.wrong_parts[0].typed, '')

    def test_every_cell_right_is_full_marks(self):
        grade = grade_table_parts(
            MONEY_SPEC, _money_cells('0.56', '0.84', '0.07', '0.96'))
        self.assertTrue(grade.is_correct)
        self.assertEqual(points_for(1, grade), 1.0)

    def test_tolerance_is_honoured_per_cell(self):
        spec = dict(MONEY_SPEC, tolerance=0.01)
        grade = grade_table_parts(
            spec, _money_cells('0.57', '0.84', '0.07', '0.96'))
        self.assertTrue(grade.is_correct)

    def test_no_verdict_on_an_unusable_spec_or_payload(self):
        self.assertIsNone(grade_table_parts(None, _money_cells('0.56')))
        self.assertIsNone(grade_table_parts({'headers': [], 'rows': []},
                                            _money_cells('0.56')))
        self.assertIsNone(grade_table_parts(MONEY_SPEC, 'not json'))
        self.assertIsNone(grade_table_parts(MONEY_SPEC, {'nope': {}}))

    def test_the_boolean_grader_still_agrees(self):
        for payload in (_money_cells('0.56', '0.84', '0.07', '0.96'),
                        _money_cells('0.56', '0.84', '0.70', '0.96'),
                        {'cells': {}},
                        'not json'):
            grade = grade_table_parts(MONEY_SPEC, payload)
            expected = grade is not None and grade.is_correct
            self.assertEqual(grade_table(MONEY_SPEC, payload), expected)


class _Row:
    """Stand-in for a stored answer row, as the display filter sees one."""

    def __init__(self, answer_data=None, is_correct=False, ai_score_fraction=None):
        self.answer_data = answer_data or {}
        self.is_correct = is_correct
        self.ai_score_fraction = ai_score_fraction


class CreditStateForPartGradedAnswersTests(SimpleTestCase):
    def _data(self, correct, total):
        parts = [Part(f'B{i}', 'x', 'x', i < correct) for i in range(total)]
        return PartialGrade(parts).as_answer_data()

    def test_some_gaps_right_reads_as_partial(self):
        # Those gaps earned points; showing the answer as flat "wrong" would
        # contradict the score printed beside it.
        row = _Row(self._data(9, 10))
        self.assertEqual(credit_state(row), 'partial')

    def test_one_gap_right_still_reads_as_partial(self):
        # No 0.5 floor here: unlike an AI confidence score, the fraction is a
        # count of gaps, and one right gap is one gap's worth of marks.
        self.assertEqual(credit_state(_Row(self._data(1, 10))), 'partial')

    def test_every_gap_right_reads_as_correct(self):
        row = _Row(self._data(10, 10), is_correct=True)
        self.assertEqual(credit_state(row), 'correct')

    def test_no_gap_right_reads_as_wrong(self):
        self.assertEqual(credit_state(_Row(self._data(0, 10))), 'wrong')

    def test_ai_graded_answers_keep_their_own_tiers(self):
        self.assertEqual(credit_state(_Row(ai_score_fraction=0.85)), 'partial')
        self.assertEqual(credit_state(_Row(ai_score_fraction=0.49)), 'wrong')

    def test_plain_answers_are_never_partial(self):
        self.assertEqual(credit_state(_Row(is_correct=True)), 'correct')
        self.assertEqual(credit_state(_Row()), 'wrong')
