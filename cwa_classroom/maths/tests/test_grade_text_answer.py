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
