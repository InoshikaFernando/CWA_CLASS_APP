"""
DB-backed tests for Question.grade_text_answer() — the single routing point
both grading surfaces (worksheets + maths plugin) call.

Pure-notation correctness lives in test_algebra_grading.py; here we prove the
model wiring: answer_format flips between exact-match and algebra grading, and
multiple correct Answer rows are honoured.
"""
from django.test import TestCase

from classroom.models import Level
from maths.models import Answer, Question


class GradeTextAnswerRoutingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=994,
            defaults={'display_name': 'grade_text_answer fixture'},
        )

    def _question(self, answer_format, correct, question_type=Question.SHORT_ANSWER):
        q = Question.objects.create(
            level=self.level,
            question_text='Expand and simplify (2x + 3)(x - 5)',
            question_type=question_type,
            answer_format=answer_format,
            difficulty=1,
            points=1,
        )
        for text in correct:
            Answer.objects.create(question=q, answer_text=text, is_correct=True)
        # a distractor that must never count as correct
        Answer.objects.create(question=q, answer_text='wrong', is_correct=False)
        return q

    # ── Algebra format: the headline behaviour ──────────────────────────────
    def test_algebra_accepts_reordered_and_respaced(self):
        q = self._question('algebra', ['2x^2 - 7x - 15'])
        self.assertTrue(q.grade_text_answer('2x^2 - 7x - 15'))
        self.assertTrue(q.grade_text_answer('2x^2-7x-15'))
        self.assertTrue(q.grade_text_answer('-7x + 2x^2 - 15'))
        self.assertTrue(q.grade_text_answer('2x² - 7x - 15'))

    def test_algebra_rejects_unsimplified_and_unexpanded(self):
        q = self._question('algebra', ['2x^2 - 7x - 15'])
        self.assertFalse(q.grade_text_answer('2x^2 - 3x - 4x - 15'))  # like terms
        self.assertFalse(q.grade_text_answer('(2x + 3)(x - 5)'))      # not expanded
        self.assertFalse(q.grade_text_answer('2x^2 - 7x - 14'))       # wrong value

    def test_algebra_honours_multiple_correct_rows(self):
        # Either sign convention accepted via separate Answer rows.
        q = self._question('algebra', ['x^2 - y^2', 'y^2 - x^2'])
        self.assertTrue(q.grade_text_answer('x^2 - y^2'))
        self.assertTrue(q.grade_text_answer('-x^2 + y^2'))

    def test_text_format_honours_multiple_correct_rows(self):
        # A short-answer question may tick several distinct answers as correct
        # (e.g. equivalent forms "9/4" and "2 1/4"). Typing ANY one of them is
        # graded correct; an unticked value is not.
        q = self._question(
            'text', ['9/4', '2 1/4'], question_type=Question.SHORT_ANSWER,
        )
        self.assertTrue(q.grade_text_answer('9/4'))
        self.assertTrue(q.grade_text_answer('2 1/4'))
        # Whitespace folding still applies per-row.
        self.assertTrue(q.grade_text_answer('2  1/4'))
        # A value matching neither accepted answer is wrong.
        self.assertFalse(q.grade_text_answer('1/4'))
        self.assertFalse(q.grade_text_answer('wrong'))

    # ── Text format: legacy behaviour is preserved ──────────────────────────
    def test_text_format_is_exact_match(self):
        q = self._question('text', ['Paris'])
        self.assertTrue(q.grade_text_answer('paris'))     # case-insensitive
        self.assertTrue(q.grade_text_answer('  PARIS '))  # space-insensitive
        self.assertFalse(q.grade_text_answer('London'))
        # Text mode does NOT understand algebra: reordering is just a wrong string.
        q2 = self._question('text', ['2x^2 - 7x - 15'])
        self.assertFalse(q2.grade_text_answer('-7x + 2x^2 - 15'))

    def test_text_format_is_exponent_insensitive(self):
        # The x² button is available on all typed maths answers, so a unit answer
        # must match however the power is typed (cm^2 / cm² / cm2).
        q = self._question('text', ['12 cm²'], question_type=Question.CALCULATION)
        for ans in ['12 cm^2', '12cm2', '12 cm 2', '12CM²', '12 cm**2']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('12 cm'))   # missing the power
        self.assertFalse(q.grade_text_answer('13 cm^2'))  # wrong value

    def test_text_format_is_inequality_insensitive(self):
        # A stored inequality must match however the student spells the operator
        # (unicode ≥, ASCII >=, or the reversed-typo =>).
        q = self._question('text', ['x ≥ 2'], question_type=Question.CALCULATION)
        for ans in ['x ≥ 2', 'x>=2', 'x => 2', 'X >= 2']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        # Strict inequality is a different statement — not accepted for ≥.
        self.assertFalse(q.grade_text_answer('x > 2'))
        self.assertFalse(q.grade_text_answer('x ≤ 2'))  # wrong direction

    def test_text_format_is_degree_insensitive(self):
        # The ° button is available on all typed maths answers, so an angle
        # answer must grade correct with or without the degree sign — a stored
        # "50" accepts "50" and "50°", and a stored "50°" accepts both too.
        q = self._question('text', ['50'], question_type=Question.CALCULATION)
        for ans in ['50', '50°', '50 °']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('60'))    # wrong value
        self.assertFalse(q.grade_text_answer('60°'))   # wrong value, with unit

        q2 = self._question('text', ['50°'], question_type=Question.CALCULATION)
        for ans in ['50', '50°']:
            self.assertTrue(q2.grade_text_answer(ans), ans)

    def test_text_format_folds_hyphen_and_filler_word(self):
        # "Express $9.53 in words" — one stored answer must accept every natural
        # phrasing: hyphenated or not, with or without the filler word "and".
        q = self._question(
            'text', ['nine dollars fifty three cents'],
            question_type=Question.SHORT_ANSWER,
        )
        for ans in [
            'nine dollars fifty three cents',
            'nine dollars and fifty three cents',
            'nine dollars fifty-three cents',
            'nine dollars and fifty-three cents',
            'Nine Dollars and Fifty-Three Cents',  # casing too
        ]:
            self.assertTrue(q.grade_text_answer(ans), ans)
        # A genuinely different amount is still wrong.
        self.assertFalse(q.grade_text_answer('nine dollars fifteen cents'))

    def test_text_format_ignores_commas(self):
        # Commas are insignificant for short answers: digit-grouping or list
        # commas must not change the match, and spacing around them is folded too.
        q = self._question('text', ['1,000'], question_type=Question.CALCULATION)
        for ans in ['1000', '1,000', '1, 000', '1 000']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('100'))  # genuinely different value

        q2 = self._question('text', ['red, green'], question_type=Question.SHORT_ANSWER)
        for ans in ['red green', 'red,green', 'red, green']:
            self.assertTrue(q2.grade_text_answer(ans), ans)

    def test_text_format_folds_multiplication_marks(self):
        # Scientific-notation / "a × b" answers must accept whichever times sign
        # the student types: the × keypad symbol, a typed "*", a middle dot, or
        # a bare "x" between two numbers. The stored answer keeps the × symbol.
        q = self._question(
            'text', ['3 × 10^4'], question_type=Question.CALCULATION,
        )
        for ans in ['3 × 10^4', '3 * 10^4', '3*10^4', '3·10^4',
                    '3 x 10^4', '3x10^4', '3 × 10⁴']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        # A genuinely different value is still wrong.
        self.assertFalse(q.grade_text_answer('3 × 10^5'))
        self.assertFalse(q.grade_text_answer('30000'))  # expanded form is a
        #                                                  separate stored answer

    def test_text_format_multiplication_fold_spares_words(self):
        # The "x" fold is bounded to between-digits so word answers with an "x"
        # ("box", "six") are never mangled into a "*".
        q = self._question('text', ['box'], question_type=Question.SHORT_ANSWER)
        self.assertTrue(q.grade_text_answer('box'))
        self.assertFalse(q.grade_text_answer('bo*'))

    def test_text_format_keeps_negative_sign_significant(self):
        # The hyphen fold must NOT strip a leading minus — "-5" != "5".
        q = self._question('text', ['-5'], question_type=Question.CALCULATION)
        self.assertTrue(q.grade_text_answer('-5'))
        self.assertFalse(q.grade_text_answer('5'))

    # ── "Select all that apply": option labels grade as a set (CPP-374) ─────
    def test_option_labels_accepted_in_any_order(self):
        # A "which of these are correct?" question is authored as a typed answer
        # listing the option labels. The student picks the same two options but
        # types them in their own order / with their own separator.
        q = self._question(
            'text', ['D and E'], question_type=Question.SHORT_ANSWER,
        )
        for ans in ['D and E', 'E and D', 'D,E', 'E,D', 'E, D', 'D E', 'e d',
                    'D & E']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_option_label_set_spares_single_letter_operators(self):
        # "/" and "-" are operators, not separators: "x/y" must not be satisfied
        # by "y/x", and "a-b" must not be satisfied by "b-a".
        q = self._question('text', ['x/y'], question_type=Question.CALCULATION)
        self.assertTrue(q.grade_text_answer('x/y'))
        self.assertFalse(q.grade_text_answer('y/x'))
        q2 = self._question('text', ['a-b'], question_type=Question.CALCULATION)
        self.assertTrue(q2.grade_text_answer('a-b'))
        self.assertFalse(q2.grade_text_answer('b-a'))

    def test_option_labels_require_the_whole_selection(self):
        # Order-insensitive, not lenient: a partial or wrong selection is wrong.
        q = self._question(
            'text', ['D and E'], question_type=Question.SHORT_ANSWER,
        )
        self.assertFalse(q.grade_text_answer('D'))        # only half of it
        self.assertFalse(q.grade_text_answer('E'))
        self.assertFalse(q.grade_text_answer('D, F'))     # one wrong label
        self.assertFalse(q.grade_text_answer('A, B'))
        self.assertFalse(q.grade_text_answer('D, E, F'))  # an extra label

    def test_option_label_set_does_not_reorder_worded_answers(self):
        # The set rule is bounded to lists of single letters, so a worded answer
        # keeps its exact match and can't be satisfied by reordering.
        q = self._question(
            'text', ['red, green'], question_type=Question.SHORT_ANSWER,
        )
        self.assertTrue(q.grade_text_answer('red green'))
        self.assertFalse(q.grade_text_answer('green red'))

    def test_option_label_set_does_not_reorder_a_sequence(self):
        # "Write these numbers in order" — reversing the answer must stay wrong.
        q = self._question(
            'text', ['3, 5, 7'], question_type=Question.SHORT_ANSWER,
        )
        self.assertTrue(q.grade_text_answer('3, 5, 7'))
        self.assertFalse(q.grade_text_answer('7, 5, 3'))

    # ── Defensive ───────────────────────────────────────────────────────────
    def test_empty_and_missing(self):
        q = self._question('algebra', ['2x^2 - 7x - 15'])
        self.assertFalse(q.grade_text_answer(''))
        self.assertFalse(q.grade_text_answer('   '))

    def test_no_correct_rows_is_false(self):
        q = Question.objects.create(
            level=self.level, question_text='?', question_type=Question.SHORT_ANSWER,
            answer_format='algebra', difficulty=1, points=1,
        )
        self.assertFalse(q.grade_text_answer('2x^2 - 7x - 15'))


class SetAnswerGradingTests(TestCase):
    """CPP-376 — answer_format='set' grades a "list every value" answer.

    "What are the multiples of 9 between 50 and 70?" has two correct values.
    Whichever order the student lists them in, and whichever way the content
    stores them (one comma-separated row, or one row per value), the answer is
    the same answer and must grade the same.

    The format is opt-in per question: a comma alone does not mean "set", so an
    ordered answer ("write these numbers in order") keeps its exact match — see
    GradeTextAnswerRoutingTests for that side of the contract (CPP-374).
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=993,
            defaults={'display_name': 'list answer fixture'},
        )

    def _question(self, correct, text='What are the multiples of 9 between 50 and 70?'):
        q = Question.objects.create(
            level=self.level,
            question_text=text,
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_SET,
            difficulty=1,
            points=1,
        )
        for value in correct:
            Answer.objects.create(question=q, answer_text=value, is_correct=True)
        return q

    def test_single_row_list_accepts_any_order_and_phrasing(self):
        q = self._question(['54, 63'])
        for ans in ['54, 63', '63, 54', '54 and 63', '63 and 54',
                    '54,63', '63,54', '54 63', '63 54', '63; 54']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_single_row_list_rejects_partial_and_wrong_values(self):
        q = self._question(['54, 63'])
        # Half the answer is not the answer — this is what the old quiz
        # comma-splitting accepted.
        self.assertFalse(q.grade_text_answer('54'))
        self.assertFalse(q.grade_text_answer('63'))
        # Extra / wrong values are wrong.
        self.assertFalse(q.grade_text_answer('54, 63, 72'))
        self.assertFalse(q.grade_text_answer('54, 62'))
        self.assertFalse(q.grade_text_answer('45, 36'))

    def test_one_row_per_value_accepts_the_full_set(self):
        # Content that entered each value as its own correct Answer row.
        q = self._question(['54', '63'])
        for ans in ['54, 63', '63, 54', '54 and 63']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('54, 72'))

    def test_set_grading_is_opt_in(self):
        # The same stored answer on a plain text question keeps its exact
        # match: a comma alone must never be read as "these are a set", or
        # "write these numbers in order" would accept them reversed (CPP-374).
        q = Question.objects.create(
            level=self.level,
            question_text='Write these numbers in order: 63, 54',
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_TEXT,
            difficulty=1, points=1,
        )
        Answer.objects.create(question=q, answer_text='54, 63', is_correct=True)
        self.assertTrue(q.grade_text_answer('54, 63'))
        self.assertFalse(q.grade_text_answer('63, 54'))

    def test_digit_grouping_comma_is_not_a_list_separator(self):
        # "1,000" is one number, so it must still match "1000" — and must not
        # be satisfied by its digit groups in the wrong order.
        q = self._question(['1,000'], text='Write one thousand in numerals')
        self.assertTrue(q.grade_text_answer('1000'))
        self.assertTrue(q.grade_text_answer('1,000'))
        self.assertFalse(q.grade_text_answer('100'))

    def test_space_separated_numbers_are_a_list_but_words_are_not(self):
        # A space only separates *values* when every token is a plain number.
        q = self._question(['54, 63'])
        self.assertTrue(q.grade_text_answer('63 54'))
        # A word answer is one value — its words must not be reorderable, even
        # inside a set question.
        words = self._question(
            ['nine dollars fifty three cents'],
            text='Write $9.53 in words',
        )
        self.assertTrue(words.grade_text_answer('nine dollars and fifty-three cents'))
        self.assertFalse(words.grade_text_answer('cents fifty three dollars nine'))

    def test_mixed_number_is_not_split_on_its_space(self):
        # "2 1/4" is one value, not the list [2, 1/4].
        q = self._question(['2 1/4'], text='Write 9/4 as a mixed number')
        self.assertTrue(q.grade_text_answer('2 1/4'))
        self.assertFalse(q.grade_text_answer('1/4 2'))

    def test_word_list_answers_accept_any_order(self):
        q = self._question(['red, green'], text='Name two primary colours')
        self.assertTrue(q.grade_text_answer('red, green'))
        self.assertTrue(q.grade_text_answer('green, red'))
        self.assertTrue(q.grade_text_answer('green and red'))
        self.assertFalse(q.grade_text_answer('red'))
        self.assertFalse(q.grade_text_answer('red, blue'))


class CorrectAnswerDisplayTests(TestCase):
    """CPP-376 — the answer shown to the student must be the whole answer."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992,
            defaults={'display_name': 'answer display fixture'},
        )

    def _question(self, correct, wrong=()):
        q = Question.objects.create(
            level=self.level, question_text='?',
            question_type=Question.SHORT_ANSWER, answer_format='text',
            difficulty=1, points=1,
        )
        for value in correct:
            Answer.objects.create(question=q, answer_text=value, is_correct=True)
        for value in wrong:
            Answer.objects.create(question=q, answer_text=value, is_correct=False)
        return q

    def test_single_row_shown_verbatim(self):
        q = self._question(['54, 63'])
        self.assertEqual(q.correct_answer_display(), '54, 63')

    def test_every_correct_row_is_shown(self):
        # The reported bug: only the first row was shown, so a student was told
        # the answer was "54" when it is 54 and 63.
        q = self._question(['54', '63'], wrong=['45'])
        self.assertEqual(q.correct_answer_display(), '54 or 63')

    def test_no_correct_row_is_blank(self):
        q = self._question([], wrong=['45'])
        self.assertEqual(q.correct_answer_display(), '')


class PositionalNumberListTests(TestCase):
    """CPP-378 — a list of numbers is compared value-by-value, not as one blob.

    The fold that makes punctuation insignificant deletes the comma, which also
    deletes the boundary between one value and the next: "(3,11)" and "(31,1)"
    both fold to "(311)". A transposed coordinate therefore graded as correct.

    Comparing the values in order keeps the boundary. It applies only when BOTH
    sides are lists of plain numbers — a word list ("red, green") or an
    assignment list ("x = 4, y = 2") stays on the flat comparison, so nothing
    that graded correct before grades wrong now.
    """

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992,
            defaults={'display_name': 'positional list fixture'},
        )

    def _question(self, correct, text='Write the coordinates of the ship.',
                  answer_format=Question.ANSWER_FORMAT_TEXT):
        q = Question.objects.create(
            level=self.level, question_text=text,
            question_type=Question.SHORT_ANSWER, answer_format=answer_format,
            difficulty=1, points=1,
        )
        for value in correct:
            Answer.objects.create(question=q, answer_text=value, is_correct=True)
        return q

    # ── the defect ──────────────────────────────────────────────────────────
    def test_transposed_coordinate_is_wrong(self):
        """'(31,1)' folds to the same blob as '(3,11)' but is a different point."""
        q = self._question(['(3,11)'])
        self.assertFalse(q.grade_text_answer('(31,1)'))
        self.assertFalse(q.grade_text_answer('(1,31)'))

    def test_regrouped_values_are_wrong(self):
        """Same defect without brackets: '3,22' is not '32, 2'."""
        q = self._question(['32, 2'], text='Missing terms')
        self.assertFalse(q.grade_text_answer('3,22'))
        q2 = self._question(['3, 5, 7, 9'], text='Missing terms')
        self.assertFalse(q2.grade_text_answer('35, 79'))

    # ── what must still be accepted ─────────────────────────────────────────
    def test_the_coordinate_itself_grades_however_it_is_punctuated(self):
        q = self._question(['(3,11)'])
        for ans in ['(3,11)', '(3, 11)', '(3 , 11)']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_brackets_are_optional(self):
        """Several coordinate questions already store a paren-less second row."""
        q = self._question(['(3,11)'])
        for ans in ['3,11', '3, 11']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_negative_and_decimal_coordinates(self):
        q = self._question(['(0, -2.5)'])
        self.assertTrue(q.grade_text_answer('(0,-2.5)'))
        self.assertTrue(q.grade_text_answer('0, -2.5'))
        self.assertFalse(q.grade_text_answer('(0, 2.5)'))
        self.assertFalse(q.grade_text_answer('(-2.5, 0)'))

    def test_a_wrong_point_is_still_wrong(self):
        q = self._question(['(3,11)'])
        for ans in ['(11,3)', '(3,12)', '(4,11)']:
            self.assertFalse(q.grade_text_answer(ans), ans)

    def test_multi_value_answers_keep_every_separator(self):
        q = self._question(['32, 2', '32 and 2'], text='Missing terms')
        for ans in ['32,2', '32, 2', '32 and 2', '32 2', '32;2']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_order_still_decides_a_positional_answer(self):
        q = self._question(['32, 2'], text='Missing terms')
        self.assertFalse(q.grade_text_answer('2, 32'))

    # ── everything else is untouched ────────────────────────────────────────
    def test_word_lists_stay_on_the_flat_comparison(self):
        """'red green' must keep matching 'red, green' — not a number list."""
        q = self._question(['red, green'], text='Name two colours')
        for ans in ['red, green', 'red green', 'red,green']:
            self.assertTrue(q.grade_text_answer(ans), ans)

    def test_assignment_lists_stay_on_the_flat_comparison(self):
        q = self._question(['x = 4, y = 2'], text='Solve the system')
        for ans in ['x = 4, y = 2', 'x=4, y=2', 'x=4 y=2']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('x = 2, y = 4'))

    def test_digit_grouping_is_not_a_list(self):
        q = self._question(['1,000'], text='How many people?')
        for ans in ['1000', '1,000', '1 000']:
            self.assertTrue(q.grade_text_answer(ans), ans)
        self.assertFalse(q.grade_text_answer('1, 000, 0'))

    def test_a_single_blob_is_unchanged(self):
        """No answer that graded correct before grades wrong now."""
        q = self._question(['32, 2'], text='Missing terms')
        self.assertTrue(q.grade_text_answer('322'))

    def test_set_answers_are_unaffected(self):
        q = self._question(['54, 63'], text='Multiples of 9 between 50 and 70',
                           answer_format=Question.ANSWER_FORMAT_SET)
        self.assertTrue(q.grade_text_answer('63, 54'))
        self.assertTrue(q.grade_text_answer('54, 63'))
        self.assertFalse(q.grade_text_answer('54'))
