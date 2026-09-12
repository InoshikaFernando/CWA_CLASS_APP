"""A number-line INEQUALITY graph grades from the inequality, not a tick list.

The report these pin: a student graphed ``k <= -2`` on a -7..7 line by marking
-7 -6 -5 -4 -3 -2, and ``m > 1`` by marking 2 3 4 5 6 7. Both are right. Both
were marked wrong, because the answer key was a spelled-out list of ticks that
stopped one short — dropping the closed boundary (-2) on the ``<=`` and the
line's own end tick (7) on the ``>``.

So the tick set is now DERIVED from the stated inequality by filtering the
line's own ticks, and every operator is pinned here with the boundary tick both
included (``<=`` ``>=``) and excluded (``<`` ``>``), at both ends of the line.
Pure-function style, mirroring ``test_number_line_grading``; the two DB tests at
the end cover the answer key the teacher and the quiz feedback are shown.
"""
from django.test import SimpleTestCase, TestCase

from classroom.models import Level
from maths.geometry_grading import (
    fold_inequality_op,
    grade_number_line,
    inequality_ticks,
    number_line_targets,
    number_line_ticks,
    parse_inequality_text,
    spec_inequality,
    validate_number_line_spec,
)
from maths.models import Question

# The line the reported questions are drawn on.
LINE = {'min': -7, 'max': 7, 'step': 1, 'mode': 'mark'}
TICKS = list(range(-7, 8))


def _spec(op, value, **extra):
    return dict(LINE, inequality={'op': op, 'value': value}, **extra)


def _marks(values):
    return '{"marks": [%s]}' % ', '.join(str(v) for v in values)


class InequalityTicksTests(SimpleTestCase):
    """Every operator, with the boundary tick in and out."""

    def test_less_or_equal_keeps_the_boundary(self):
        # The reported Q10: k <= -2 over -7..7 is every tick from -7 to -2.
        self.assertEqual(inequality_ticks('<=', -2, TICKS),
                         [-7, -6, -5, -4, -3, -2])

    def test_less_than_drops_the_boundary(self):
        self.assertEqual(inequality_ticks('<', -2, TICKS),
                         [-7, -6, -5, -4, -3])

    def test_greater_or_equal_keeps_the_boundary(self):
        self.assertEqual(inequality_ticks('>=', 1, TICKS), [1, 2, 3, 4, 5, 6, 7])

    def test_greater_than_drops_the_boundary(self):
        # The reported Q11: m > 1 keeps 7, the line's own end tick.
        self.assertEqual(inequality_ticks('>', 1, TICKS), [2, 3, 4, 5, 6, 7])

    def test_ends_of_the_line_are_included(self):
        # An inequality satisfied by every tick keeps BOTH end ticks — the
        # off-by-one this replaced lost whichever end it counted towards.
        self.assertEqual(inequality_ticks('<=', 7, TICKS), TICKS)
        self.assertEqual(inequality_ticks('>=', -7, TICKS), TICKS)
        self.assertEqual(inequality_ticks('<', 7, TICKS), TICKS[:-1])
        self.assertEqual(inequality_ticks('>', -7, TICKS), TICKS[1:])

    def test_boundary_off_tick(self):
        # A bound between ticks belongs to neither: x < 2.5 and x <= 2.5 are the
        # same set of ticks.
        self.assertEqual(inequality_ticks('<', 2.5, TICKS), list(range(-7, 3)))
        self.assertEqual(inequality_ticks('<=', 2.5, TICKS), list(range(-7, 3)))

    def test_wider_step_line(self):
        ticks = number_line_ticks({'min': 0, 'max': 10, 'step': 2})
        self.assertEqual(inequality_ticks('>=', 4, ticks), [4, 6, 8, 10])
        self.assertEqual(inequality_ticks('>', 4, ticks), [6, 8, 10])

    def test_unknown_operator_or_bound_is_empty(self):
        self.assertEqual(inequality_ticks('=', 2, TICKS), [])
        self.assertEqual(inequality_ticks('<=', 'two', TICKS), [])
        self.assertEqual(inequality_ticks(None, 2, TICKS), [])
        self.assertEqual(inequality_ticks('<=', 2, []), [])

    def test_operator_spellings_fold(self):
        self.assertEqual(fold_inequality_op('≤'), '<=')
        self.assertEqual(fold_inequality_op('=<'), '<=')
        self.assertEqual(fold_inequality_op('≥'), '>=')
        self.assertEqual(fold_inequality_op('=>'), '>=')
        self.assertEqual(fold_inequality_op(' > '), '>')
        self.assertIsNone(fold_inequality_op('≠'))
        self.assertIsNone(fold_inequality_op(2))
        # Strict and non-strict never fold together — the boundary is the point.
        self.assertNotEqual(fold_inequality_op('<'), fold_inequality_op('≤'))

    def test_unicode_operator_derives_the_same_ticks(self):
        self.assertEqual(inequality_ticks('≤', -2, TICKS),
                         inequality_ticks('<=', -2, TICKS))
        self.assertEqual(inequality_ticks('≥', 1, TICKS),
                         inequality_ticks('>=', 1, TICKS))


class SpecTargetTests(SimpleTestCase):
    def test_inequality_spec_derives_its_targets(self):
        self.assertEqual(number_line_targets(_spec('<=', -2)),
                         [-7, -6, -5, -4, -3, -2])

    def test_inequality_wins_over_a_stale_target(self):
        # The exact shape of the bug: a spelled-out key that lost the boundary.
        # With the inequality stated, the stored list no longer decides.
        spec = _spec('<=', -2, target=[-7, -6, -5, -4, -3])
        self.assertEqual(number_line_targets(spec), [-7, -6, -5, -4, -3, -2])

    def test_plain_target_spec_is_untouched(self):
        self.assertEqual(
            number_line_targets({'min': -3, 'max': 7, 'step': 1,
                                 'mode': 'mark', 'target': [2, 5]}),
            [2, 5])

    def test_read_spec_still_falls_back_to_given(self):
        self.assertEqual(
            number_line_targets({'min': 0, 'max': 10, 'step': 2,
                                 'mode': 'read', 'given': [6]}),
            [6])

    def test_malformed_inequality_block_is_ignored_for_targets(self):
        # Grading falls back to the stored target rather than blowing up; the
        # validator is what refuses the spec at import/clean time.
        spec = dict(LINE, inequality={'op': '≠', 'value': 2}, target=[2])
        self.assertIsNone(spec_inequality(spec))
        self.assertEqual(number_line_targets(spec), [2])


class GradeInequalityTests(SimpleTestCase):
    """The reported answers, graded end to end through ``grade_number_line``."""

    def test_reported_q10_less_or_equal_is_correct(self):
        spec = _spec('<=', -2)
        self.assertTrue(grade_number_line(spec, _marks([-2, -3, -4, -5, -6, -7])))

    def test_reported_q11_greater_than_is_correct(self):
        spec = _spec('>', 1)
        self.assertTrue(grade_number_line(spec, _marks([2, 3, 4, 5, 6, 7])))

    def test_order_does_not_matter(self):
        spec = _spec('<=', -2)
        self.assertTrue(grade_number_line(spec, _marks([-4, -7, -2, -5, -3, -6])))

    def test_missing_the_boundary_is_wrong_for_non_strict(self):
        spec = _spec('<=', -2)
        self.assertFalse(grade_number_line(spec, _marks([-7, -6, -5, -4, -3])))

    def test_marking_the_boundary_is_wrong_for_strict(self):
        spec = _spec('<', -2)
        self.assertFalse(grade_number_line(spec, _marks([-7, -6, -5, -4, -3, -2])))
        self.assertTrue(grade_number_line(spec, _marks([-7, -6, -5, -4, -3])))

    def test_greater_or_equal_needs_the_boundary(self):
        spec = _spec('>=', 1)
        self.assertTrue(grade_number_line(spec, _marks([1, 2, 3, 4, 5, 6, 7])))
        self.assertFalse(grade_number_line(spec, _marks([2, 3, 4, 5, 6, 7])))

    def test_missing_the_end_tick_is_wrong(self):
        # The other half of the reported bug: a key that stopped before 7.
        spec = _spec('>', 1)
        self.assertFalse(grade_number_line(spec, _marks([2, 3, 4, 5, 6])))

    def test_int_float_equivalence(self):
        spec = _spec('>=', 1)
        self.assertTrue(grade_number_line(spec, _marks([1.0, 2.0, 3, 4, 5, 6, 7])))

    def test_blank_and_malformed_answers_are_wrong_not_errors(self):
        spec = _spec('<=', -2)
        self.assertFalse(grade_number_line(spec, ''))
        self.assertFalse(grade_number_line(spec, 'not json'))
        self.assertFalse(grade_number_line(spec, '{"marks": []}'))


class ValidateInequalitySpecTests(SimpleTestCase):
    def test_inequality_spec_is_valid_without_a_target(self):
        validate_number_line_spec(_spec('<=', -2))  # must not raise

    def test_agreeing_target_is_allowed(self):
        validate_number_line_spec(_spec('>', 1, target=[2, 3, 4, 5, 6, 7]))

    def test_disagreeing_target_is_rejected(self):
        # Loudly, at import/clean time — not quietly out-voting the inequality.
        with self.assertRaises(ValueError) as ctx:
            validate_number_line_spec(_spec('<=', -2, target=[-7, -6, -5, -4, -3]))
        self.assertIn('does not match the inequality', str(ctx.exception))

    def test_unknown_operator_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(_spec('≠', 2))

    def test_non_numeric_bound_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(_spec('<=', 'two'))

    def test_non_object_inequality_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(dict(LINE, inequality=['<=', -2]))

    def test_inequality_matching_no_tick_is_rejected(self):
        # x < -7 on a -7..7 line leaves nothing to mark.
        with self.assertRaises(ValueError) as ctx:
            validate_number_line_spec(_spec('<', -7))
        self.assertIn('no tick', str(ctx.exception))

    def test_inequality_in_read_mode_is_rejected(self):
        spec = {'min': -7, 'max': 7, 'step': 1, 'mode': 'read', 'given': [2],
                'inequality': {'op': '<=', 'value': -2}}
        with self.assertRaises(ValueError):
            validate_number_line_spec(spec)

    def test_plain_mark_spec_still_requires_a_target(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec({'min': -7, 'max': 7, 'step': 1, 'mode': 'mark'})


class ParseInequalityTextTests(SimpleTestCase):
    def test_reads_the_reported_questions(self):
        self.assertEqual(
            parse_inequality_text('Draw a graph for the inequality k <= -2.'),
            ('<=', -2))
        self.assertEqual(
            parse_inequality_text('Draw a graph for the inequality m > 1.'),
            ('>', 1))

    def test_reads_unicode_and_typo_spellings(self):
        self.assertEqual(parse_inequality_text('Graph x ≥ -3'), ('>=', -3))
        self.assertEqual(parse_inequality_text('Graph y ≤ 4'), ('<=', 4))
        self.assertEqual(parse_inequality_text('Graph y =< 4'), ('<=', 4))

    def test_reads_a_mirrored_statement(self):
        # "-2 >= k" states "k <= -2" — the operator mirrors, the bound does not.
        self.assertEqual(parse_inequality_text('Draw a graph for -2 ≥ k.'), ('<=', -2))
        self.assertEqual(parse_inequality_text('Draw a graph for 1 < m.'), ('>', 1))

    def test_reads_a_decimal_bound(self):
        self.assertEqual(parse_inequality_text('Graph t < 2.5'), ('<', 2.5))

    def test_no_inequality_reads_as_none(self):
        self.assertIsNone(parse_inequality_text('Mark 5 on the number line.'))
        self.assertIsNone(parse_inequality_text(''))
        self.assertIsNone(parse_inequality_text(None))

    def test_a_compound_inequality_reads_as_none(self):
        # Two statements — repairing one on a guess would be worse than leaving
        # the question to a person.
        self.assertIsNone(parse_inequality_text('Draw a graph for 1 < x <= 4.'))


class InequalityAnswerKeyTests(TestCase):
    """The key the teacher's answer sheet and the quiz feedback are shown."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994, defaults={'display_name': 'inequality fixture'})

    def _question(self, spec, text='Draw a graph for the inequality k <= -2.'):
        return Question.objects.create(
            level=self.level, question_text=text, difficulty=1, points=1,
            question_type=Question.NUMBER_LINE, number_line_spec=spec,
        )

    def test_answer_key_derives_from_the_inequality(self):
        q = self._question(_spec('<=', -2))
        data = q.number_line_data
        self.assertEqual(data['target_values'], [-7, -6, -5, -4, -3, -2])
        # Every answer mark lands on a drawn tick, so the key renders.
        self.assertEqual(len(data['answer']), 6)

    def test_answer_key_ignores_a_stale_target_list(self):
        q = self._question(_spec('<=', -2, target=[-7, -6, -5, -4, -3]))
        self.assertEqual(q.number_line_data['target_values'],
                         [-7, -6, -5, -4, -3, -2])

    def test_clean_rejects_a_key_that_contradicts_the_inequality(self):
        from django.core.exceptions import ValidationError
        q = Question(
            level=self.level, question_text='Draw a graph for k <= -2.',
            difficulty=1, points=1, question_type=Question.NUMBER_LINE,
            number_line_spec=_spec('<=', -2, target=[-7, -6, -5, -4, -3]),
        )
        with self.assertRaises(ValidationError):
            q.clean()
