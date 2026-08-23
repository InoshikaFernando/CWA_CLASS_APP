"""Pure-function tests for the fill-in-the-blank helpers.

Covers blank detection (``count_blanks`` / ``split_on_blanks``),
``validate_blank_spec`` (the strict import/clean gate), ``derive_blank_spec``
(the one mapping rule the importer, the teacher form and the
``convert_fill_blanks`` command all share), ``grade_fill_blank`` (all-or-nothing)
and the review-surface describers. No DB — mirrors the pure-function style of
``test_table_of_values_grading`` / ``test_number_line_grading``.
"""
import json

from django.test import SimpleTestCase

from maths.blank_grading import (
    MAX_BLANKS,
    count_blanks,
    derive_blank_spec,
    describe_blank_answer,
    describe_blank_spec,
    grade_fill_blank,
    split_on_blanks,
    validate_blank_spec,
)

# The Q9 life-table question from the worksheet this type was built for.
SENTENCE = (
    'Out of 100 000 births, 99 231 females are expected to survive to the age '
    'of ___. From that age, the survivors are expected to ___ for another '
    '67.0 years.'
)
SPEC = {'blanks': [{'answers': ['15']}, {'answers': ['live', 'survive']}]}


def _payload(*values):
    return json.dumps({'blanks': list(values)})


class CountBlanksTests(SimpleTestCase):
    def test_counts_each_run(self):
        self.assertEqual(count_blanks(SENTENCE), 2)

    def test_run_length_does_not_matter(self):
        self.assertEqual(count_blanks('a __ b _____ c'), 2)

    def test_single_underscore_is_not_a_blank(self):
        # A lone "_" is a subscript in ordinary maths text ("a_1"), never a gap.
        self.assertEqual(count_blanks('Find a_1 given a_2 = 5.'), 0)

    def test_no_text(self):
        self.assertEqual(count_blanks(''), 0)
        self.assertEqual(count_blanks(None), 0)


class SplitOnBlanksTests(SimpleTestCase):
    def test_segments_surround_the_blanks(self):
        self.assertEqual(
            split_on_blanks('age of ___. Then ___ years'),
            ['age of ', '. Then ', ' years'],
        )

    def test_one_more_segment_than_blanks(self):
        segments = split_on_blanks(SENTENCE)
        self.assertEqual(len(segments), count_blanks(SENTENCE) + 1)

    def test_leading_and_trailing_blanks_keep_empty_segments(self):
        # The empty edges matter: the template needs the gap positions to line
        # up with the spec, not the visible text.
        self.assertEqual(split_on_blanks('___ and ___'), ['', ' and ', ''])


class ValidateBlankSpecTests(SimpleTestCase):
    def test_valid_spec(self):
        validate_blank_spec(SPEC, SENTENCE)  # does not raise

    def test_rejects_non_dict(self):
        with self.assertRaises(ValueError):
            validate_blank_spec([{'answers': ['15']}])

    def test_rejects_empty_blanks(self):
        with self.assertRaises(ValueError):
            validate_blank_spec({'blanks': []})

    def test_rejects_blank_with_no_answers(self):
        with self.assertRaises(ValueError):
            validate_blank_spec({'blanks': [{'answers': []}]})

    def test_rejects_blank_answer_string(self):
        with self.assertRaises(ValueError):
            validate_blank_spec({'blanks': [{'answers': ['  ']}]})

    def test_rejects_too_many_blanks(self):
        spec = {'blanks': [{'answers': ['x']}] * (MAX_BLANKS + 1)}
        with self.assertRaises(ValueError):
            validate_blank_spec(spec)

    def test_count_must_match_the_text(self):
        # The check that actually matters — a spec of the right SHAPE but the
        # wrong length mis-grades every attempt, silently.
        with self.assertRaises(ValueError) as ctx:
            validate_blank_spec(SPEC, 'Only one gap here: ___')
        self.assertIn('2 blank(s)', str(ctx.exception))

    def test_count_is_only_checked_when_text_is_given(self):
        validate_blank_spec(SPEC)  # does not raise


class GradeFillBlankTests(SimpleTestCase):
    def test_every_blank_right(self):
        self.assertTrue(grade_fill_blank(SPEC, _payload('15', 'live')))

    def test_alternative_spelling_accepted(self):
        self.assertTrue(grade_fill_blank(SPEC, _payload('15', 'survive')))

    def test_all_or_nothing(self):
        # One right, one wrong is wrong — matching grade_table.
        self.assertFalse(grade_fill_blank(SPEC, _payload('15', 'die')))
        self.assertFalse(grade_fill_blank(SPEC, _payload('20', 'live')))

    def test_folding_matches_short_answer_rules(self):
        self.assertTrue(grade_fill_blank(SPEC, _payload(' 15 ', 'LIVE')))
        spec = {'blanks': [{'answers': ['fifty-three']}]}
        self.assertTrue(grade_fill_blank(spec, _payload('fifty three')))
        spec = {'blanks': [{'answers': ['1,000']}]}
        self.assertTrue(grade_fill_blank(spec, _payload('1000')))

    def test_a_negative_sign_still_counts(self):
        spec = {'blanks': [{'answers': ['-5']}]}
        self.assertFalse(grade_fill_blank(spec, _payload('5')))

    def test_empty_blank_is_wrong(self):
        self.assertFalse(grade_fill_blank(SPEC, _payload('15', '')))
        self.assertFalse(grade_fill_blank(SPEC, _payload('15', None)))

    def test_wrong_number_of_values_is_wrong(self):
        self.assertFalse(grade_fill_blank(SPEC, _payload('15')))
        self.assertFalse(grade_fill_blank(SPEC, _payload('15', 'live', 'extra')))

    def test_malformed_payload_is_wrong_never_raises(self):
        for payload in ('', 'not json', '[]', '{}', '{"blanks": "15"}', None, 7):
            self.assertFalse(grade_fill_blank(SPEC, payload))

    def test_accepts_an_already_parsed_payload(self):
        self.assertTrue(grade_fill_blank(SPEC, {'blanks': ['15', 'live']}))

    def test_unusable_spec_is_never_silently_correct(self):
        for spec in (None, {}, {'blanks': []}, {'blanks': [{}]}, 'nope'):
            self.assertFalse(grade_fill_blank(spec, _payload('15', 'live')))


class DeriveBlankSpecTests(SimpleTestCase):
    def test_one_blank_takes_every_row_as_an_alternative(self):
        spec, reason = derive_blank_spec('The answer is ___.', ['15', 'fifteen'])
        self.assertEqual(reason, '')
        self.assertEqual(spec, {'blanks': [{'answers': ['15', 'fifteen']}]})

    def test_one_row_per_blank_maps_in_order(self):
        spec, reason = derive_blank_spec(SENTENCE, ['15', 'live'])
        self.assertEqual(reason, '')
        self.assertEqual(
            spec, {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_one_row_splits_on_semicolon(self):
        spec, _ = derive_blank_spec(SENTENCE, ['15; live'])
        self.assertEqual(
            spec, {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_one_row_splits_on_comma_when_there_is_no_semicolon(self):
        spec, _ = derive_blank_spec(SENTENCE, ['15, live'])
        self.assertEqual(
            spec, {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

    def test_semicolon_wins_over_comma(self):
        # "1,000" is one value, not two — so a semicolon, where present, decides
        # where one blank's answer ends and the next begins.
        spec, _ = derive_blank_spec('___ then ___', ['1,000; 2,000'])
        self.assertEqual(
            spec, {'blanks': [{'answers': ['1,000']}, {'answers': ['2,000']}]})

    def test_pipe_lists_alternatives_within_one_blank(self):
        spec, _ = derive_blank_spec(SENTENCE, ['15; live|survive'])
        self.assertEqual(spec, SPEC)

    def test_refuses_a_row_that_will_not_split(self):
        spec, reason = derive_blank_spec(SENTENCE, ['fifteen and living'])
        self.assertIsNone(spec)
        self.assertIn('does not split', reason)

    def test_refuses_a_mismatched_row_count(self):
        spec, reason = derive_blank_spec(SENTENCE, ['15', 'live', 'extra'])
        self.assertIsNone(spec)
        self.assertIn('3 correct answer rows', reason)

    def test_refuses_a_question_with_no_blanks(self):
        spec, reason = derive_blank_spec('What is 2 + 2?', ['4'])
        self.assertIsNone(spec)
        self.assertIn('no blanks', reason)

    def test_refuses_a_question_with_no_stored_answer(self):
        spec, reason = derive_blank_spec(SENTENCE, [])
        self.assertIsNone(spec)
        self.assertIn('no correct answer', reason)

    def test_refuses_more_blanks_than_allowed(self):
        spec, reason = derive_blank_spec('___ ' * (MAX_BLANKS + 1), ['x'])
        self.assertIsNone(spec)
        self.assertIn('more than the', reason)


class DescribeTests(SimpleTestCase):
    def test_payload_reads_as_a_list(self):
        self.assertEqual(describe_blank_answer(_payload('15', 'live')), '15, live')

    def test_unfilled_gap_shows_as_a_dash(self):
        self.assertEqual(describe_blank_answer(_payload('15', '')), '15, —')

    def test_non_blank_answers_pass_through_unchanged(self):
        # Review surfaces pipe every typed answer through this without first
        # asking what type the question was.
        self.assertEqual(describe_blank_answer('42'), '42')
        self.assertEqual(describe_blank_answer('{"cells": {}}'), '{"cells": {}}')

    def test_spec_reads_as_an_answer_key(self):
        self.assertEqual(describe_blank_spec(SPEC), '15, live or survive')

    def test_unusable_spec_describes_as_empty(self):
        self.assertEqual(describe_blank_spec(None), '')
