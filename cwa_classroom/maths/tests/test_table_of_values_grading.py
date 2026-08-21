"""Pure-function tests for the ``table_of_values`` grading helpers.

Covers ``_table_cell_kind`` (cell classification), ``validate_table_spec`` (the
strict import/clean gate) and ``grade_table`` (all-or-nothing numeric-tolerance
grading of the filled cells). No DB — mirrors the pure-function style of
``test_number_line_grading`` / ``test_geometry_grading``.
"""
from django.test import SimpleTestCase

from maths.geometry_grading import (
    _table_cell_kind,
    grade_table,
    validate_table_spec,
)


# A small "compute y = x^2 - 2 for each given x" table: x is given, y is the
# blank the student fills. Answer cells sit at column 1 → keys "0,1", "1,1", "2,1".
def _spec(**overrides):
    spec = {
        'headers': ['x', 'y'],
        'rows': [
            [{'given': '-1'}, {'answer': '-1'}],
            [{'given': '0'}, {'answer': '-2'}],
            [{'given': '2'}, {'answer': '2'}],
        ],
    }
    spec.update(overrides)
    return spec


class CellKindTests(SimpleTestCase):
    def test_given_cell(self):
        self.assertEqual(_table_cell_kind({'given': '3'}), ('given', '3'))

    def test_answer_cell(self):
        self.assertEqual(_table_cell_kind({'answer': '7'}), ('answer', '7'))

    def test_both_keys_is_malformed(self):
        self.assertIsNone(_table_cell_kind({'given': '3', 'answer': '7'}))

    def test_neither_key_is_malformed(self):
        self.assertIsNone(_table_cell_kind({}))
        self.assertIsNone(_table_cell_kind({'value': '3'}))

    def test_non_dict_is_malformed(self):
        self.assertIsNone(_table_cell_kind('3'))
        self.assertIsNone(_table_cell_kind(None))


class ValidateSpecTests(SimpleTestCase):
    def test_valid_spec(self):
        validate_table_spec(_spec())  # must not raise

    def test_valid_with_tolerance(self):
        validate_table_spec(_spec(tolerance=0.5))

    def test_reject_non_dict(self):
        with self.assertRaises(ValueError):
            validate_table_spec([1, 2, 3])

    def test_reject_empty_headers(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(headers=[]))

    def test_reject_non_string_header(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(headers=['x', 2]))

    def test_reject_too_many_columns(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(headers=[f'c{i}' for i in range(9)]))

    def test_reject_empty_rows(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[]))

    def test_reject_too_many_rows(self):
        row = [{'given': '0'}, {'answer': '0'}]
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[row] * 21))

    def test_reject_wrong_row_length(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[[{'given': '0'}]]))  # 1 cell, 2 headers

    def test_reject_ambiguous_cell(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[[{'given': '0', 'answer': '0'}, {'answer': '1'}]]))

    def test_reject_non_numeric_answer(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[[{'given': '0'}, {'answer': 'up'}]]))

    def test_reject_no_answer_cells(self):
        # A table with only given cells is unanswerable.
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(rows=[[{'given': '0'}, {'given': '1'}]]))

    def test_reject_negative_tolerance(self):
        with self.assertRaises(ValueError):
            validate_table_spec(_spec(tolerance=-1))

    def test_given_cell_may_be_non_numeric(self):
        # Given cells are just shown text — a label column is allowed.
        validate_table_spec({
            'headers': ['point', 'y'],
            'rows': [[{'given': 'vertex'}, {'answer': '-4'}]],
        })


class GradeTests(SimpleTestCase):
    spec = _spec()

    def test_all_correct(self):
        payload = '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "2"}}'
        self.assertTrue(grade_table(self.spec, payload))

    def test_one_wrong_is_incorrect(self):
        payload = '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "3"}}'
        self.assertFalse(grade_table(self.spec, payload))

    def test_missing_cell_is_incorrect(self):
        payload = '{"cells": {"0,1": "-1", "1,1": "-2"}}'
        self.assertFalse(grade_table(self.spec, payload))

    def test_accepts_already_parsed_dict(self):
        self.assertTrue(grade_table(
            self.spec, {'cells': {'0,1': '-1', '1,1': '-2', '2,1': '2'}}))

    def test_int_float_equivalence(self):
        payload = '{"cells": {"0,1": "-1.0", "1,1": "-2", "2,1": "2.0"}}'
        self.assertTrue(grade_table(self.spec, payload))

    def test_extra_typed_cells_are_ignored(self):
        # A stray key (e.g. the student typed in a given column somehow) does not
        # matter — only the answer cells are graded.
        payload = '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "2", "0,0": "99"}}'
        self.assertTrue(grade_table(self.spec, payload))

    def test_tolerance_band(self):
        spec = _spec(
            rows=[[{'given': '3'}, {'answer': '9.2'}]],
            tolerance=0.5,
        )
        self.assertTrue(grade_table(spec, '{"cells": {"0,1": "9.5"}}'))
        self.assertTrue(grade_table(spec, '{"cells": {"0,1": "9"}}'))
        self.assertFalse(grade_table(spec, '{"cells": {"0,1": "10"}}'))

    def test_malformed_payload_is_incorrect(self):
        self.assertFalse(grade_table(self.spec, 'not json'))
        self.assertFalse(grade_table(self.spec, ''))
        self.assertFalse(grade_table(self.spec, '[]'))
        self.assertFalse(grade_table(self.spec, '{"cells": "x"}'))
        self.assertFalse(grade_table(self.spec, '{}'))

    def test_unparseable_cell_is_incorrect(self):
        payload = '{"cells": {"0,1": "-1", "1,1": "-2", "2,1": "two"}}'
        self.assertFalse(grade_table(self.spec, payload))

    def test_malformed_spec_is_incorrect(self):
        self.assertFalse(grade_table('nope', '{"cells": {}}'))
        self.assertFalse(grade_table({'headers': 'x', 'rows': []}, '{"cells": {}}'))
