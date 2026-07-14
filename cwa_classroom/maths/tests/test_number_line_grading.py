"""Pure-function tests for the ``number_line`` grading helpers.

Covers ``number_line_ticks`` (scale → tick list), ``validate_number_line_spec``
(the strict import/clean gate) and ``grade_number_line`` (mark set-comparison +
read numeric tolerance). No DB — these mirror the pure-function style of
``test_geometry_grading``. Epic follows the measure/plane geometry types.
"""
from django.test import SimpleTestCase

from maths.geometry_grading import (
    grade_number_line,
    number_line_ticks,
    validate_number_line_spec,
)


class NumberLineTicksTests(SimpleTestCase):
    def test_ticks_unit_step(self):
        self.assertEqual(
            number_line_ticks({'min': -3, 'max': 7, 'step': 1}),
            [-3, -2, -1, 0, 1, 2, 3, 4, 5, 6, 7],
        )

    def test_ticks_wider_step(self):
        self.assertEqual(
            number_line_ticks({'min': 0, 'max': 10, 'step': 2}),
            [0, 2, 4, 6, 8, 10],
        )

    def test_ticks_none_for_bad_scale(self):
        self.assertIsNone(number_line_ticks({'min': 7, 'max': 7, 'step': 1}))
        self.assertIsNone(number_line_ticks({'min': 0, 'max': 5, 'step': 0}))
        self.assertIsNone(number_line_ticks('nope'))

    def test_ticks_none_when_too_many(self):
        # A huge range at step 1 would emit thousands of ticks — refuse it.
        self.assertIsNone(number_line_ticks({'min': 0, 'max': 5000, 'step': 1}))

    def test_ticks_decimal_step_keeps_last_tick(self):
        # 0.3 / 0.1 == 2.9999999999999996 in float; truncation would drop the
        # final 0.3 tick, so the builder rounds before truncating.
        self.assertEqual(
            number_line_ticks({'min': 0, 'max': 0.3, 'step': 0.1}),
            [0, 0.1, 0.2, 0.3],
        )

    def test_decimal_target_on_tick_is_valid_and_graded(self):
        spec = {'min': 0, 'max': 0.3, 'step': 0.1, 'mode': 'mark', 'target': [0.3]}
        validate_number_line_spec(spec)  # must not raise
        self.assertTrue(grade_number_line(spec, '{"marks": [0.3]}'))


class ValidateSpecTests(SimpleTestCase):
    def test_valid_mark_spec(self):
        validate_number_line_spec(
            {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2]})

    def test_valid_read_spec(self):
        validate_number_line_spec(
            {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]})

    def test_mode_defaults_to_mark(self):
        # No mode → treated as mark, so a target is required.
        validate_number_line_spec({'min': 0, 'max': 5, 'step': 1, 'target': [3]})

    def test_reject_non_dict(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec([1, 2, 3])

    def test_reject_min_not_less_than_max(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 5, 'max': 5, 'step': 1, 'mode': 'mark', 'target': [5]})

    def test_reject_bad_step(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': -1, 'mode': 'mark', 'target': [3]})

    def test_reject_unknown_mode(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': 1, 'mode': 'wiggle', 'target': [3]})

    def test_reject_off_tick_target(self):
        # step 2 → ticks 0,2,4… so 3 is unreachable and must be rejected.
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 10, 'step': 2, 'mode': 'mark', 'target': [3]})

    def test_reject_out_of_range_target(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': 1, 'mode': 'mark', 'target': [9]})

    def test_reject_empty_target(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': 1, 'mode': 'mark', 'target': []})

    def test_read_requires_given(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': 1, 'mode': 'read'})

    def test_reject_negative_tolerance(self):
        with self.assertRaises(ValueError):
            validate_number_line_spec(
                {'min': 0, 'max': 5, 'step': 1, 'mode': 'read',
                 'given': [3], 'tolerance': -1})


class GradeMarkTests(SimpleTestCase):
    spec = {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2, 5]}

    def test_correct_set(self):
        self.assertTrue(grade_number_line(self.spec, '{"marks": [2, 5]}'))

    def test_order_independent(self):
        self.assertTrue(grade_number_line(self.spec, '{"marks": [5, 2]}'))

    def test_missing_a_mark_is_wrong(self):
        self.assertFalse(grade_number_line(self.spec, '{"marks": [2]}'))

    def test_extra_mark_is_wrong(self):
        self.assertFalse(grade_number_line(self.spec, '{"marks": [2, 5, 6]}'))

    def test_int_float_equivalence(self):
        self.assertTrue(grade_number_line(self.spec, '{"marks": [2.0, 5.0]}'))

    def test_malformed_payload_is_wrong(self):
        self.assertFalse(grade_number_line(self.spec, 'not json'))
        self.assertFalse(grade_number_line(self.spec, '{"marks": "x"}'))
        self.assertFalse(grade_number_line(self.spec, ''))


class GradeReadTests(SimpleTestCase):
    def test_exact_read(self):
        spec = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]}
        self.assertTrue(grade_number_line(spec, '6'))
        self.assertFalse(grade_number_line(spec, '7'))

    def test_read_within_tolerance(self):
        spec = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read',
                'given': [6], 'tolerance': 1}
        self.assertTrue(grade_number_line(spec, '7'))
        self.assertFalse(grade_number_line(spec, '8'))

    def test_read_strips_unit_text(self):
        spec = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]}
        self.assertTrue(grade_number_line(spec, '6 cm'))

    def test_multi_value_read_multiset(self):
        spec = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [2, 8]}
        self.assertTrue(grade_number_line(spec, '2, 8'))
        self.assertTrue(grade_number_line(spec, '8 2'))
        self.assertFalse(grade_number_line(spec, '2'))       # too few
        self.assertFalse(grade_number_line(spec, '2, 8, 8'))  # too many

    def test_unparseable_read_is_wrong(self):
        spec = {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]}
        self.assertFalse(grade_number_line(spec, 'abc'))
