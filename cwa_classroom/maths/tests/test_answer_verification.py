"""Tests for ``maths.answer_verification`` — verifying that stored answers are
correct, not merely present (CPP-377 follow-up).

Logic tests only. To verify the *current state of production content* run

    python manage.py verify_question_answers
"""
from fractions import Fraction

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level
from maths.answer_verification import (
    BLANK_OPTION,
    DUPLICATE_VALUE,
    EQUIVALENT_OPTION,
    MULTI_CORRECT,
    NO_CORRECT,
    TOO_FEW_OPTIONS,
    TOO_MANY_OPTIONS,
    WRONG_ANSWER_KEY,
    evaluate_expression,
    extract_expression,
    verify_question,
)
from maths.models import Answer, Question


class ExpressionEvaluationTests(TestCase):
    """Exact fraction arithmetic, and a hard refusal on anything ambiguous."""

    def test_real_production_expressions(self):
        # Every 'Calculate:' question from the topic in the CPP-377 report.
        cases = [
            ('Calculate: 2 3/5 + 3/10', Fraction(29, 10)),
            ('Calculate: 9/10 - 3/5', Fraction(3, 10)),
            ('Calculate: (-3/5) × (-2/3)', Fraction(2, 5)),
            ('Calculate: 4/5 × 1/3', Fraction(4, 15)),
            ('Calculate: 4/5 - 2/10', Fraction(3, 5)),
            ('Calculate: 1 1/2 + 3/4', Fraction(9, 4)),
            ('Calculate: 1/6 × 2/5', Fraction(1, 15)),
            ('Calculate: 1/2 × 3/8', Fraction(3, 16)),
            ('Calculate: 11/12 - 2/3', Fraction(1, 4)),
        ]
        for text, expected in cases:
            with self.subTest(text):
                self.assertEqual(
                    evaluate_expression(extract_expression(text)), expected)

    def test_operator_precedence(self):
        self.assertEqual(evaluate_expression('1/2 + 1/2 * 4'), Fraction(5, 2))

    def test_parentheses_override_precedence(self):
        self.assertEqual(evaluate_expression('(1/2 + 1/2) * 4'), Fraction(4))

    def test_division_operator(self):
        self.assertEqual(evaluate_expression('1/2 ÷ 1/4'), Fraction(2))

    def test_division_by_zero_is_refused(self):
        self.assertIsNone(evaluate_expression('1/2 ÷ 0'))
        self.assertIsNone(evaluate_expression('3/0'))

    def test_word_problems_are_refused(self):
        for text in [
            'A bag contains 5/6 kg of apples. If 1/2 kg is removed, how much is left?',
            'Compare: 8/6 and 4/6',
            'Write 3/5 and 2/4 as equivalent fractions with a common denominator.',
        ]:
            with self.subTest(text):
                self.assertIsNone(extract_expression(text))

    def test_algebra_is_refused(self):
        # Regression: '3x + 2' once parsed as 3 * (+2) = 6, which would have
        # reported a correct algebra key as wrong. A times-'x' must be
        # whitespace-delimited to count as multiplication.
        for text in ['Calculate: 3x + 2', 'Calculate: 2x', 'Calculate: x + 1']:
            with self.subTest(text):
                self.assertIsNone(extract_expression(text))

    def test_spaced_x_is_still_multiplication(self):
        self.assertEqual(
            evaluate_expression(extract_expression('Calculate: 4/5 x 1/3')),
            Fraction(4, 15))

    def test_trailing_junk_is_refused(self):
        self.assertIsNone(evaluate_expression('1/2 + )'))
        self.assertIsNone(evaluate_expression('(1/2 + 1/4'))


class VerifyQuestionTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992,
            defaults={'display_name': 'verification fixture'},
        )

    def _question(self, text, options):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1,
        )
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def _codes(self, question):
        issues, _ = verify_question(question)
        return sorted(i.code for i in issues)

    def test_wrong_answer_key_is_caught(self):
        # 9/10 - 3/5 = 3/10, but the key says 2/5.
        q = self._question('Calculate: 9/10 - 3/5', [
            ('2/5', True), ('3/10', False), ('1/2', False),
        ])
        self.assertIn(WRONG_ANSWER_KEY, self._codes(q))

    def test_right_answer_key_passes(self):
        q = self._question('Calculate: 9/10 - 3/5', [
            ('2/5', False), ('3/10', True), ('1/2', False),
        ])
        issues, verified = verify_question(q)
        self.assertEqual(issues, [])
        self.assertTrue(verified)

    def test_equivalent_distractor_still_caught(self):
        q = self._question('Calculate: 11/12 - 2/3', [
            ('1/4', True), ('3/12', False), ('1/3', False),
        ])
        self.assertIn(EQUIVALENT_OPTION, self._codes(q))

    def test_two_distractors_with_the_same_value_are_flagged(self):
        """Production Q6009 after the content fix: '1/2' and '3/6' co-exist.

        Nobody is mismarked — both are wrong — so this is not the CPP-377
        defect. But the question offers three real choices while appearing to
        offer four, and neither EQUIVALENT-OPTION (compares against the correct
        answer) nor DUPLICATE-OPTION (compares text) sees it.
        """
        q = self._question('5/6 kg less 1/2 kg?', [
            ('1/2', False), ('1/6', False), ('3/6', False), ('1/3', True),
        ])
        self.assertIn(DUPLICATE_VALUE, self._codes(q))

    def test_duplicate_value_flagged_for_mixed_and_improper_forms(self):
        # Production Q6017 after the fix: '3 1/3 kg' and '10/3 kg' are both 10/3.
        q = self._question('1/3 kg per cake, 9 cakes?', [
            ('3 1/3 kg', False), ('3 kg', True),
            ('2 2/3 kg', False), ('10/3 kg', False),
        ])
        self.assertIn(DUPLICATE_VALUE, self._codes(q))

    def test_distinct_distractors_are_not_flagged(self):
        # Production Q6019 after the fix — every option a different number.
        q = self._question('2/7 litre a day for 14 days?', [
            ('2 litres', False), ('3 6/7 litres', False),
            ('26/7 litres', False), ('4 litres', True),
        ])
        self.assertNotIn(DUPLICATE_VALUE, self._codes(q))

    def test_equal_to_correct_reports_only_the_mismark(self):
        # An option equal to the CORRECT answer is EQUIVALENT-OPTION, the real
        # defect — it must not also be reported as a duplicate distractor.
        q = self._question('5/6 kg less 1/2 kg?', [
            ('2/6', False), ('1/3', True),
        ])
        codes = self._codes(q)
        self.assertIn(EQUIVALENT_OPTION, codes)
        self.assertNotIn(DUPLICATE_VALUE, codes)

    def test_no_correct_option(self):
        q = self._question('Calculate: 1/2 + 1/2', [('1', False), ('2', False)])
        self.assertIn(NO_CORRECT, self._codes(q))

    def test_multiple_correct_options(self):
        q = self._question('Calculate: 1/2 + 1/2', [
            ('1', True), ('2', True), ('3', False),
        ])
        self.assertIn(MULTI_CORRECT, self._codes(q))

    def test_word_problem_reports_unverified_not_clean(self):
        # A word problem with a sound structure has no issues, but must NOT be
        # reported as arithmetically verified — that distinction is the whole
        # point of the coverage number.
        q = self._question(
            'A bag contains 5/6 kg of apples. If 1/2 kg is removed, how much is left?',
            [('1/3', True), ('1/2', False), ('1/6', False)])
        issues, verified = verify_question(q)
        self.assertEqual(issues, [])
        self.assertFalse(verified)


class VerifyCommandTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=991,
            defaults={'display_name': 'verify-command fixture'},
        )

    def _question(self, text, options):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1,
        )
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def test_exits_non_zero_on_wrong_key(self):
        self._question('Calculate: 1/2 + 1/4', [('1/2', True), ('1/4', False)])
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_question_answers', '--level', 991)
        self.assertEqual(ctx.exception.code, 1)

    def test_exits_zero_when_clean(self):
        self._question('Calculate: 1/2 + 1/4', [('3/4', True), ('1/4', False)])
        call_command('verify_question_answers', '--level', 991)

    def test_duplicate_value_alone_does_not_fail_the_run(self):
        # Two wrong options worth the same number mismark nobody, so the
        # weekly job must not go red over it.
        self._question('5/6 kg less 1/2 kg?', [
            ('1/2', False), ('3/6', False), ('1/3', True),
        ])
        call_command('verify_question_answers', '--level', 991)   # no SystemExit

    def test_duplicate_value_fails_under_strict(self):
        self._question('5/6 kg less 1/2 kg?', [
            ('1/2', False), ('3/6', False), ('1/3', True),
        ])
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_question_answers', '--level', 991, '--strict')
        self.assertEqual(ctx.exception.code, 1)

    def test_check_filter_narrows_reporting(self):
        # A question with only an EQUIVALENT-OPTION issue passes a run
        # filtered to WRONG-ANSWER-KEY.
        self._question('Calculate: 11/12 - 2/3',
                       [('1/4', True), ('3/12', False)])
        call_command('verify_question_answers', '--level', 991,
                     '--check', WRONG_ANSWER_KEY)


class NonChoiceQuestionTypeTests(TestCase):
    """Short-answer questions are not multiple choice, and must not be judged
    as if they were.

    Their ``Answer`` rows are the ACCEPTED answers for typed input, so one row
    is the normal case and several are alternative spellings of the same
    answer. Reporting a converted question as "too few options" told a
    super-admin their repair had not worked, and made the bulk fixer answer
    "nothing to change" on a row the page itself was still flagging.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993,
            defaults={'display_name': 'non-choice fixture'},
        )

    def _question(self, question_type, options, text='1 + 2 = ?'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=question_type, difficulty=1,
        )
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def _codes(self, question):
        issues, _ = verify_question(question)
        return sorted(i.code for i in issues)

    def test_short_answer_with_one_accepted_answer_is_clean(self):
        q = self._question(Question.SHORT_ANSWER, [('3', True)])
        self.assertNotIn(TOO_FEW_OPTIONS, self._codes(q))

    def test_multiple_choice_with_one_option_is_still_flagged(self):
        # The rule is not deleted, only scoped — a one-option MCQ is broken.
        q = self._question(Question.MULTIPLE_CHOICE, [('3', True)])
        self.assertIn(TOO_FEW_OPTIONS, self._codes(q))

    def test_short_answer_accepted_spellings_are_not_too_many_options(self):
        q = self._question(Question.SHORT_ANSWER, [
            ('3', True), ('three', True), ('3.0', True),
            ('03', True), ('+3', True),
        ])
        codes = self._codes(q)
        self.assertNotIn(TOO_MANY_OPTIONS, codes)
        self.assertNotIn(MULTI_CORRECT, codes)

    def test_short_answer_alternative_spellings_are_not_duplicates(self):
        # Two rows worth the same number is exactly what alternative accepted
        # answers look like; on a choice question it would be a real finding.
        q = self._question(Question.SHORT_ANSWER, [('1/2', True), ('0.5', True)],
                           text='What fraction of the shape is shaded?')
        self.assertEqual(self._codes(q), [])

    def test_short_answer_with_no_correct_row_is_still_flagged(self):
        # Scoping the OPTION rules does not excuse a question nobody can pass.
        q = self._question(Question.SHORT_ANSWER, [('3', False)])
        self.assertIn(NO_CORRECT, self._codes(q))

    def test_short_answer_with_a_blank_row_is_still_flagged(self):
        q = self._question(Question.SHORT_ANSWER, [('3', True), ('   ', True)])
        self.assertIn(BLANK_OPTION, self._codes(q))

    def test_short_answer_answer_key_is_still_checked(self):
        # The arithmetic check is type-independent: a wrong key mismarks a
        # student whether they typed the answer or picked it.
        q = self._question(Question.SHORT_ANSWER, [('2/5', True)],
                           text='Calculate: 9/10 - 3/5')
        self.assertIn(WRONG_ANSWER_KEY, self._codes(q))


class UnitBearingOptionTests(TestCase):
    """Options whose units differ are not the same answer.

    Production: "The mass of a pet cat would most likely be about: 4 t / 4 kg /
    400 g / 4 g", with 4 kg correct. Units were stripped before comparing, so
    '4 g' read as the number 4 — equal to the correct answer — and the question
    was reported as mismarking students. In an estimation question the unit is
    the entire point: the numbers repeat deliberately so the student has to
    think about scale.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=987, defaults={'display_name': 'units fixture'})

    def _question(self, options, text='The mass of a pet cat would be about:'):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def _codes(self, question):
        issues, _ = verify_question(question)
        return sorted(i.code for i in issues)

    def test_the_pet_cat_question_is_clean(self):
        q = self._question([('4 t', False), ('4 kg', True),
                            ('400 g', False), ('4 g', False)])
        self.assertEqual([], self._codes(q))

    def test_the_same_number_in_different_units_is_not_an_equivalent_option(self):
        q = self._question([('4 kg', True), ('4 g', False),
                            ('40 g', False), ('400 g', False)])
        self.assertNotIn(EQUIVALENT_OPTION, self._codes(q))

    def test_two_distractors_in_different_units_are_not_duplicate_values(self):
        q = self._question([('5 kg', True), ('4 g', False),
                            ('4 kg', False), ('400 g', False)])
        self.assertNotIn(DUPLICATE_VALUE, self._codes(q))

    def test_the_same_number_in_the_SAME_unit_is_still_caught(self):
        # Scoping units must not blunt the real check.
        q = self._question([('3 kg', True), ('9/3 kg', False),
                            ('4 kg', False), ('5 kg', False)])
        self.assertIn(EQUIVALENT_OPTION, self._codes(q))

    def test_an_unstated_unit_still_compares_against_a_stated_one(self):
        # Production Q6013: '15/4' is the same quantity as '3 3/4 teaspoons',
        # the unit being implied by the question. A student picking it is
        # mismarked, so a blank unit must stay compatible with a stated one.
        q = self._question([('3 3/4 teaspoons', True), ('15/4', False),
                            ('4', False), ('3 1/2', False)],
                           text='3/4 teaspoon, 5 times?')
        self.assertIn(EQUIVALENT_OPTION, self._codes(q))

    def test_an_unrecognised_unit_is_not_read_as_no_unit(self):
        # 't' for tonnes is not in the unit table; it must still count as a
        # unit rather than silently comparing equal to a bare number.
        from maths.answer_values import parse_answer_unit
        self.assertNotEqual('', parse_answer_unit('4 t'))


class NegativeFirstTermTests(TestCase):
    """A negative first term must survive the prompt.

    Production, Year 8 Number › Integers: "What is -7 + 12?" was reported as
    "7 + 12 = 19 but the flagged answer is '5'". The stored answer was right —
    the separator in the prompt pattern allowed '-' as well as ':', so the
    minus sign was eaten before the expression was ever parsed. Every correct
    negative-number question in the topic was flagged as a wrong answer key.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=985, defaults={'display_name': 'negatives fixture'})

    def _question(self, text, options):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.MULTIPLE_CHOICE, difficulty=1)
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    def test_the_four_reported_questions_are_clean(self):
        cases = [
            ('What is -7 + 12?', '5'),
            ('What is -15 + (-8)?', '-23'),
            ('What is -18 + 18?', '0'),
            ('What is -33 + 14?', '-19'),
        ]
        for text, answer in cases:
            with self.subTest(text):
                q = self._question(text, [(answer, True), ('99', False),
                                          ('98', False), ('97', False)])
                issues, verified = verify_question(q)
                self.assertEqual([], [i.code for i in issues])
                self.assertTrue(verified)

    def test_a_genuinely_wrong_negative_key_is_still_caught(self):
        # Scoping the separator must not blunt the check it exists for.
        q = self._question('What is -7 + 12?', [('19', True), ('1', False),
                                                ('2', False), ('3', False)])
        issues, _ = verify_question(q)
        self.assertIn(WRONG_ANSWER_KEY, [i.code for i in issues])

    def test_a_colon_separator_still_works(self):
        self.assertEqual('-3/5 + 1', extract_expression('Calculate: -3/5 + 1'))
