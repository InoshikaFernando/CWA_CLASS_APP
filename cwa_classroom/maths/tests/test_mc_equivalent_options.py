"""Tests for ``maths.answer_values`` — detecting multiple-choice distractors
that are mathematically equal to the correct answer (CPP-377).

These are *logic* tests of the parser and detector. For an audit of the current
state of production data run

    python manage.py audit_mc_equivalent_options

against the prod DB instead; passing fixtures prove the rule works, not that
the content is clean.
"""
from fractions import Fraction

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level
from maths.answer_values import find_equivalent_options, parse_answer_value
from maths.models import Answer, Question


class ParseAnswerValueTests(TestCase):
    """The parser reads a single number, or reports that it cannot."""

    def test_plain_fraction(self):
        self.assertEqual(parse_answer_value('15/4'), Fraction(15, 4))

    def test_mixed_number(self):
        self.assertEqual(parse_answer_value('3 3/4'), Fraction(15, 4))

    def test_mixed_number_is_not_read_as_bare_fraction(self):
        # "3 3/4" must be 15/4, never 3/4 — the whole part is significant.
        self.assertEqual(parse_answer_value('3 3/4'), Fraction(15, 4))
        self.assertNotEqual(parse_answer_value('3 3/4'), Fraction(3, 4))

    def test_negative_mixed_number_signs_the_whole_quantity(self):
        # -(2 + 1/2), not (-2 + 1/2).
        self.assertEqual(parse_answer_value('-2 1/2'), Fraction(-5, 2))

    def test_units_are_stripped(self):
        self.assertEqual(parse_answer_value('3 kg'), Fraction(3))
        self.assertEqual(parse_answer_value('4 litres'), Fraction(4))
        self.assertEqual(parse_answer_value('3 3/4 teaspoons'), Fraction(15, 4))

    def test_currency_is_stripped(self):
        self.assertEqual(parse_answer_value('$60'), Fraction(60))

    def test_decimal(self):
        self.assertEqual(parse_answer_value('0.75'), Fraction(3, 4))

    def test_negative_fraction(self):
        self.assertEqual(parse_answer_value('-6/15'), Fraction(-2, 5))

    def test_compound_answer_is_not_comparable(self):
        # "6/30 and 2/30" is two values — no single number to compare.
        self.assertIsNone(parse_answer_value('6/30 and 2/30'))

    def test_free_text_is_not_comparable(self):
        self.assertIsNone(parse_answer_value('C = 8, D = 3'))
        self.assertIsNone(parse_answer_value('>'))
        self.assertIsNone(parse_answer_value(''))
        self.assertIsNone(parse_answer_value(None))

    def test_zero_denominator_is_not_comparable(self):
        self.assertIsNone(parse_answer_value('1/0'))


class FindEquivalentOptionsTests(TestCase):
    """The real CPP-377 shapes, reconstructed from the production rows."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994,
            defaults={'display_name': 'equivalent-option fixture'},
        )

    def _question(self, text, options):
        """options: [(answer_text, is_correct), ...]"""
        q = Question.objects.create(
            level=self.level,
            question_text=text,
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1,
        )
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(
                question=q, answer_text=answer_text,
                is_correct=is_correct, order=order,
            )
        return q

    def test_unsimplified_distractor_is_flagged(self):
        # Production Q6017: '2 3/3 kg' and '9/3 kg' both equal the correct '3 kg'.
        q = self._question('A baker uses 1/3 kg per cake. 9 cakes?', [
            ('3 1/3 kg', False),
            ('3 kg', True),
            ('2 3/3 kg', False),
            ('9/3 kg', False),
        ])
        clashes = find_equivalent_options(q)
        flagged = sorted(d.answer_text for d, _ in clashes)
        self.assertEqual(flagged, ['2 3/3 kg', '9/3 kg'])

    def test_improper_form_of_mixed_answer_is_flagged(self):
        # Production Q6013: '15/4' == correct '3 3/4 teaspoons'.
        q = self._question('3/4 teaspoon, 5 times?', [
            ('3 3/4 teaspoons', True),
            ('15/4', False),
            ('4', False),
            ('3 1/2', False),
        ])
        clashes = find_equivalent_options(q)
        self.assertEqual([d.answer_text for d, _ in clashes], ['15/4'])

    def test_unreduced_fraction_distractor_is_flagged(self):
        # Production Q6009: '2/6' == correct '1/3'.
        q = self._question('5/6 kg less 1/2 kg?', [
            ('1/2', False), ('1/6', False), ('2/6', False), ('1/3', True),
        ])
        clashes = find_equivalent_options(q)
        self.assertEqual([d.answer_text for d, _ in clashes], ['2/6'])

    def test_clean_question_is_not_flagged(self):
        # Production Q5990 — every option a genuinely different value.
        q = self._question('Calculate: 9/10 - 3/5', [
            ('2/5', False), ('6/10', False), ('3/10', True), ('1/2', False),
        ])
        self.assertEqual(find_equivalent_options(q), [])

    def test_sign_difference_is_not_equivalence(self):
        # Production Q6029: '-6/15' == -2/5, which is NOT the correct '2/5'.
        # This question is sloppy (two identical distractors) but nobody is
        # ever marked wrong for right work, so it must not be flagged.
        q = self._question('Calculate: (-3/5) x (-2/3)', [
            ('-2/5', False), ('2/5', True), ('-6/15', False), ('3/5', False),
        ])
        self.assertEqual(find_equivalent_options(q), [])

    def test_non_numeric_options_are_not_compared(self):
        # Two unparseable options must not be treated as equal to each other.
        q = self._question('Write 2/10 and 1/15 with a common denominator.', [
            ('6/30 and 2/30', True),
            ('4/25 and 1/25', False),
            ('2/150 and 1/150', False),
            ('3/20 and 2/20', False),
        ])
        self.assertEqual(find_equivalent_options(q), [])

    def test_question_with_no_correct_option_is_skipped(self):
        q = self._question('Broken question', [('1/3', False), ('2/6', False)])
        self.assertEqual(find_equivalent_options(q), [])


class AuditCommandTests(TestCase):
    """The command exits non-zero on violations — the CI/cron contract."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993,
            defaults={'display_name': 'audit-command fixture'},
        )

    def _question(self, options):
        q = Question.objects.create(
            level=self.level, question_text='fixture',
            question_type=Question.MULTIPLE_CHOICE, difficulty=1,
        )
        for order, (text, correct) in enumerate(options):
            Answer.objects.create(
                question=q, answer_text=text, is_correct=correct, order=order,
            )
        return q

    def test_exits_non_zero_when_violations_exist(self):
        self._question([('3 kg', True), ('9/3 kg', False)])
        with self.assertRaises(SystemExit) as exit_ctx:
            call_command('audit_mc_equivalent_options', '--level', 993)
        self.assertEqual(exit_ctx.exception.code, 1)

    def test_exits_zero_when_clean(self):
        self._question([('3 kg', True), ('4 kg', False)])
        # No SystemExit — a clean audit returns normally.
        call_command('audit_mc_equivalent_options', '--level', 993)
