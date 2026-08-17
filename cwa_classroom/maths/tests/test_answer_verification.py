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
    DUPLICATE_VALUE,
    EQUIVALENT_OPTION,
    MULTI_CORRECT,
    NO_CORRECT,
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
