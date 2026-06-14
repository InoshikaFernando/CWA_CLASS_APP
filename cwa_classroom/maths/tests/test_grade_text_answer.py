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
