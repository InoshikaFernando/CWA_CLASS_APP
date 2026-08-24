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
    bare_unit_answers,
    count_blanks,
    derive_blank_spec,
    describe_blank_answer,
    describe_blank_spec,
    grade_fill_blank,
    split_on_blanks,
    unit_repeat_blanks,
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
        # No separator at all, so there is no honest way to say which half of it
        # belongs to which gap.
        spec, reason = derive_blank_spec(SENTENCE, ['fifteen living'])
        self.assertIsNone(spec)
        self.assertIn('does not split', reason)

    def test_and_is_a_separator_too(self):
        # "15 and live" says the same as "15; live" — a teacher writing the
        # natural English form should not have the question refused.
        spec, _ = derive_blank_spec(SENTENCE, ['15 and live'])
        self.assertEqual(
            spec, {'blanks': [{'answers': ['15']}, {'answers': ['live']}]})

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


class DeriveFromProductionShapesTests(SimpleTestCase):
    """The answer shapes a real conversion run over the question bank turned up.

    Every case here is a question that existed in production; the first dry run
    mapped several of them onto the wrong gaps, which is what these pin shut.
    ``positional_rows=False`` is what the bulk command passes — rows on legacy
    questions were written to fill one answer box.
    """

    def _derive(self, text, rows, **kwargs):
        kwargs.setdefault('positional_rows', False)
        spec, reason = derive_blank_spec(text, rows, **kwargs)
        return (describe_blank_spec(spec) if spec else None), reason

    # ── rows that are spellings of one answer, not one value per gap ─────

    def test_refuses_rows_that_are_spellings_of_the_rule(self):
        # 3 gaps, 3 rows — but the rows spell the RULE, and the gap values
        # (45, 90, 105) are not stored at all. Mapping row i onto gap i asked
        # the student for "+15" where the answer was 45.
        got, reason = self._derive(
            'Complete the pattern: 30, ___, 60, 75, ___, ___. What is the rule?',
            ['+15', 'add 15', '+ 15'])
        self.assertIsNone(got)
        self.assertTrue(reason)

    # NOTE: the rule-prefixed row list and the "9" / "9 and 9" pair used to be
    # refused here. Both now convert correctly, because one of their rows does
    # list every value — see OneRowSaysWhereTheValuesGoTests below, which is
    # where those two shapes are now asserted.

    def test_positional_rows_stay_available_when_asked_for(self):
        # The authoring paths keep the row-per-gap convention; only the bulk
        # backfill declines it. Atomic, distinct rows still map.
        got, reason = self._derive(
            'A triangle has ___ sides and ___ angles.',
            ['3', '4'], positional_rows=True)
        self.assertEqual(got, '3, 4')
        self.assertEqual(reason, '')

    def test_identical_rows_still_map_per_gap(self):
        # "3" and "3" for a two-gap sentence: whether they were meant as one
        # value per gap or as one answer written twice, both gaps take 3 — so
        # there is nothing the mapping can get wrong, and refusing it would lose
        # a perfectly good question.
        got, reason = self._derive(
            'A triangle has ___ sides and ___ angles.',
            ['3', '3'], positional_rows=True)
        self.assertEqual(got, '3, 3')
        self.assertEqual(reason, '')

    def test_positional_rows_are_screened_even_when_allowed(self):
        got, _ = self._derive(
            'Complete the pattern: 30, ___, 60, 75, ___, ___.',
            ['+15', 'add 15', '+ 15'], positional_rows=True)
        self.assertIsNone(got)

    # ── rows that each list every value ──────────────────────────────────

    def test_every_row_listing_all_values_becomes_alternatives(self):
        got, _ = self._derive(
            'Fill in the missing numbers of this sequence: 14, 17, 20, 23, ___, ___',
            ['26, 29', '26 and 29'])
        self.assertEqual(got, '26, 29')

    def test_and_separates_values_like_a_comma(self):
        got, _ = self._derive('___ and ___ are the two.', ['26 and 29'])
        self.assertEqual(got, '26, 29')

    def test_a_split_may_not_cut_across_an_earlier_separator(self):
        # "+4; 26, 30, 34" splits into three parts on "," — but the first still
        # holds the ";" that should have divided rule from values, so the split
        # is a coincidence and taking it would mark "26" wrong.
        got, _ = self._derive(
            'Complete the pattern: 14, 18, 22, __, __, __.', ['+4; 26, 30, 34'])
        self.assertIsNone(got)

    # ── a unit already printed after the gap ─────────────────────────────

    def test_refuses_an_answer_that_repeats_the_following_unit(self):
        got, reason = self._derive(
            'Convert to millilitres: 5.3 L = _____ mL', ['5300 mL'])
        self.assertIsNone(got)
        self.assertIn('repeat the unit', reason)

    def test_allows_it_when_the_bare_value_is_also_stored(self):
        got, _ = self._derive(
            'The total weight is ___ pounds.', ['27.445', '27.445 pounds'])
        self.assertEqual(got, '27.445 or 27.445 pounds')

    def test_a_unit_that_is_not_repeated_is_fine(self):
        got, _ = self._derive(
            'Convert the following length to centimetres: 1.3 m = ___ cm.', ['130'])
        self.assertEqual(got, '130')

    def test_an_operator_after_the_gap_is_not_a_unit(self):
        got, _ = self._derive('Fill in the missing number: 8 + 8 = ____ x 8', ['2'])
        self.assertEqual(got, '2')

    # ── the single-gap rule, which cannot land on the wrong blank ────────

    def test_single_gap_rows_are_always_alternatives(self):
        got, _ = self._derive(
            'The product of any fraction and its reciprocal is _______.',
            ['1', 'one'])
        self.assertEqual(got, '1 or one')


class OneRowSaysWhereTheValuesGoTests(SimpleTestCase):
    """A row that lists all N values decides the gaps, even beside prose rows.

    The importer routinely wrote a question's answer twice — once with a
    separator, once as prose ("up, 2" beside "up by 2"). Only the separated one
    says where the halves go. Requiring EVERY row to split refused these; the
    row-per-gap rule would have handed gap 1 the whole string "up by 2".
    """

    def _derive(self, text, rows):
        spec, reason = derive_blank_spec(text, rows, positional_rows=False)
        return (describe_blank_spec(spec) if spec else None), reason

    def test_prose_row_beside_a_separated_row(self):
        got, _ = self._derive('This pattern is going ______ by ______.',
                              ['up by 2', 'up, 2'])
        self.assertEqual(got, 'up, 2')

    def test_the_prose_row_is_dropped_not_merged(self):
        # "up by 2" must not become an accepted answer for either gap.
        spec, _ = derive_blank_spec('This pattern is going ______ by ______.',
                                    ['up by 2', 'up, 2'], positional_rows=False)
        self.assertEqual(spec['blanks'][0]['answers'], ['up'])
        self.assertEqual(spec['blanks'][1]['answers'], ['2'])

    def test_comma_row_beside_a_spaceless_row(self):
        got, _ = self._derive('…one event ______ affect the ______ of the other.',
                              ['does, occurrence', 'does occurrence'])
        self.assertEqual(got, 'does, occurrence')

    def test_a_rule_prefixed_row_beside_a_clean_one(self):
        # The "+4; 26, 30, 34" rows cannot split (the ";" survives a "," split),
        # but "26, 30, 34" can — and it is the one that names the gaps.
        got, _ = self._derive('Complete the pattern: 14, 18, 22, __, __, __.',
                              ['+4; 26, 30, 34', 'add 4; 26, 30, 34', '26, 30, 34'])
        self.assertEqual(got, '26, 30, 34')

    def test_still_refused_when_no_row_lists_the_values(self):
        got, reason = self._derive('30, ___, 60, 75, ___, ___. What is the rule?',
                                   ['+15', 'add 15', '+ 15'])
        self.assertIsNone(got)
        self.assertTrue(reason)


class ThousandsSeparatorTests(SimpleTestCase):
    """A comma inside one number is not a list separator."""

    def test_a_thousands_number_is_never_split(self):
        spec, reason = derive_blank_spec('___ and ___ are the two.', ['1,000'],
                                         positional_rows=False)
        self.assertIsNone(spec, 'split "1,000" into "1" and "000"')
        self.assertIn('does not split', reason)

    def test_thousands_numbers_still_split_on_a_real_separator(self):
        spec, _ = derive_blank_spec('___ then ___', ['1,000; 2,000'],
                                    positional_rows=False)
        self.assertEqual(
            spec, {'blanks': [{'answers': ['1,000']}, {'answers': ['2,000']}]})

    def test_a_spaced_pair_is_still_a_pair(self):
        # "122, 121" has a space, so it is two values, not one number.
        spec, _ = derive_blank_spec('100, 132, 116, 124, 120, ___, ___',
                                    ['122, 121'], positional_rows=False)
        self.assertEqual(
            spec, {'blanks': [{'answers': ['122']}, {'answers': ['121']}]})


class GradeByAnswerFormatTests(SimpleTestCase):
    """Each gap is judged by the question's answer_format, not by string equality.

    Converting a question used to drop its answer_format silently: the gap
    grader compared folded strings, so an algebra question stopped accepting
    "2ba" for "2ab".
    """

    SPEC = {'blanks': [{'answers': ['2ab']}, {'answers': ['81/4']}]}

    def _grade(self, typed, answer_format):
        return grade_fill_blank(self.SPEC, json.dumps({'blanks': typed}), answer_format)

    def test_algebra_accepts_a_commuted_product(self):
        self.assertTrue(self._grade(['2ba', '81/4'], 'algebra'))

    def test_algebra_accepts_an_equal_value_written_differently(self):
        self.assertTrue(self._grade(['2ab', '20.25'], 'algebra'))

    def test_algebra_still_rejects_a_wrong_value(self):
        self.assertFalse(self._grade(['3ab', '81/4'], 'algebra'))

    def test_text_stays_literal(self):
        self.assertFalse(self._grade(['2ba', '20.25'], 'text'))
        self.assertTrue(self._grade(['2ab', '81/4'], 'text'))

    def test_default_is_text(self):
        self.assertFalse(self._grade(['2ba', '81/4'], 'text'))
        self.assertFalse(grade_fill_blank(
            self.SPEC, json.dumps({'blanks': ['2ba', '81/4']})))

    def test_a_commuted_expression_is_accepted_without_algebra_format(self):
        # The allowance a plain typed answer already has, kept per gap.
        spec = {'blanks': [{'answers': ['12p + 110']}]}
        self.assertTrue(grade_fill_blank(spec, json.dumps({'blanks': ['110 + 12p']})))


class UnitRepeatTests(SimpleTestCase):
    def test_finds_the_repeating_blank(self):
        spec = {'blanks': [{'answers': ['5300 mL']}]}
        self.assertEqual(
            unit_repeat_blanks('5.3 L = _____ mL', spec), [0])

    def test_ignores_a_blank_with_a_bare_alternative(self):
        spec = {'blanks': [{'answers': ['5300', '5300 mL']}]}
        self.assertEqual(unit_repeat_blanks('5.3 L = _____ mL', spec), [])

    def test_a_unit_inside_a_longer_word_is_not_a_repeat(self):
        spec = {'blanks': [{'answers': ['warm']}]}
        self.assertEqual(unit_repeat_blanks('It feels ___ m', spec), [])

    def test_unusable_input_never_raises(self):
        self.assertEqual(unit_repeat_blanks('no gaps', {'blanks': []}), [])
        self.assertEqual(unit_repeat_blanks('___', None), [])


class BareUnitAnswerTests(SimpleTestCase):
    """The repair for the refusal ``UnitRepeatTests`` covers.

    The production shape: fourteen metric-conversion questions whose only
    stored answer repeated the unit already printed after the gap.
    """

    def test_offers_the_bare_value(self):
        self.assertEqual(
            bare_unit_answers('Convert to millilitres: 5.3 L = _____ mL',
                              ['5300 mL']),
            ['5300'])

    def test_a_unit_written_against_the_number_still_strips(self):
        self.assertEqual(
            bare_unit_answers('5.3 L = _____ mL', ['5300mL']), ['5300'])

    def test_offers_nothing_when_a_bare_value_is_already_stored(self):
        # Nothing to repair — the student can already answer "5300".
        self.assertEqual(
            bare_unit_answers('5.3 L = _____ mL', ['5300', '5300 mL']), [])

    def test_offers_nothing_when_no_unit_follows_the_gap(self):
        self.assertEqual(
            bare_unit_answers('An _______ is a whole number.', ['integer']), [])

    def test_a_unit_inside_a_longer_word_is_not_stripped(self):
        self.assertEqual(bare_unit_answers('It feels ___ m', ['warm']), [])

    def test_alternatives_are_stripped_separately(self):
        self.assertEqual(
            bare_unit_answers('5.3 L = _____ mL', ['5300 mL|5300.0 mL']),
            ['5300', '5300.0'])

    def test_refuses_a_multi_gap_question(self):
        # Which row feeds which gap is the ambiguity derive_blank_spec refuses
        # to guess at; stripping the wrong row would corrupt the answer.
        self.assertEqual(
            bare_unit_answers('___ L = ___ mL', ['5.3 mL', '5300 mL']), [])

    def test_the_repair_makes_the_question_convertible(self):
        # The whole point: what it returns must satisfy derive_blank_spec.
        text = 'Convert to millilitres: 5.3 L = _____ mL'
        self.assertIsNone(derive_blank_spec(text, ['5300 mL'])[0])
        extra = bare_unit_answers(text, ['5300 mL'])
        spec, reason = derive_blank_spec(text, ['5300 mL'] + extra)
        self.assertEqual(reason, '')
        self.assertEqual(spec, {'blanks': [{'answers': ['5300 mL', '5300']}]})
        self.assertTrue(grade_fill_blank(spec, _payload('5300')))
        self.assertTrue(grade_fill_blank(spec, _payload('5300 mL')))

    def test_unusable_input_never_raises(self):
        self.assertEqual(bare_unit_answers('', ['5300 mL']), [])
        self.assertEqual(bare_unit_answers('5.3 L = ___ mL', []), [])
        self.assertEqual(bare_unit_answers('5.3 L = ___ mL', ['   ']), [])


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
