"""Tests for ``quiz.views._grade_short_answer`` — the typed-answer grading the
topic quiz runs (CPP-378).

The reported bug: a sequence question storing the correct answers "32, 2" and
"32 and 2" marked a student's "32,2" **Incorrect**, on the very screen that
then told them the correct answer was "32, 2 or 32 and 2". The quiz surface had
its own copy of the exact-match rules that split each stored answer on "," and
treated the pieces as alternatives, so the complete answer never matched — while
a bare "32", half the answer, did.

Grading now starts from ``Question.grade_text_answer``, the same rules every
other surface uses, and keeps the comma-as-alternatives rule only as a fallback
for legacy authoring ("1/2, 0.5" meaning either form).
"""
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question
from quiz.views import _correct_answer_texts, _grade_short_answer


class ShortAnswerGradingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=978, display_name='Grading')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Grading Sequences',
            slug='grading-sequences', is_active=True,
        )
        cls.topic.levels.add(cls.level)

    def _question(self, text, correct_texts, answer_format=Question.ANSWER_FORMAT_TEXT):
        q = Question.objects.create(
            question_text=text, question_type='short_answer',
            answer_format=answer_format, topic=self.topic, level=self.level,
        )
        for order, answer_text in enumerate(correct_texts):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=True, order=order)
        return q

    def _grade(self, question, raw):
        return _grade_short_answer(question, raw, _correct_answer_texts(question))

    # ------------------------------------------------- the reported regression

    def test_two_part_answer_accepts_every_punctuation(self):
        """"___, 16, 8, 4, ___, 1" — the answer is 32 and 2, however it's typed."""
        q = self._question(
            'Write down the missing terms in the sequence: ___, 16, 8, 4, ___, 1',
            ['32, 2', '32 and 2'],
        )
        for typed in ('32,2', '32, 2', '32 and 2', '32 , 2', '32 2'):
            with self.subTest(typed=typed):
                self.assertTrue(self._grade(q, typed))

    def test_two_part_answer_stays_order_sensitive(self):
        """The terms fill named gaps, so "2, 32" is a different answer."""
        q = self._question('Missing terms', ['32, 2', '32 and 2'])
        self.assertFalse(self._grade(q, '2, 32'))

    def test_wrong_answer_is_still_wrong(self):
        q = self._question('Missing terms', ['32, 2', '32 and 2'])
        for typed in ('64, 2', '16, 2', 'thirty'):
            with self.subTest(typed=typed):
                self.assertFalse(self._grade(q, typed))

    def test_blank_answer_is_wrong(self):
        q = self._question('Missing terms', ['32, 2'])
        self.assertFalse(self._grade(q, ''))

    # ------------------------------------------------- rules kept from before

    def test_legacy_comma_separated_alternatives_still_grade(self):
        """One row listing accepted *forms* predates one row per alternative."""
        q = self._question('Write 0.5 as a fraction or decimal', ['1/2, 0.5'])
        self.assertTrue(self._grade(q, '1/2'))
        self.assertTrue(self._grade(q, '0.5'))

    def test_option_labels_grade_in_any_order(self):
        """CPP-374: "select all that apply" is a set of labels."""
        q = self._question('Which are prime?', ['D and E'])
        for typed in ('D and E', 'E,D', 'E D'):
            with self.subTest(typed=typed):
                self.assertTrue(self._grade(q, typed))
        self.assertFalse(self._grade(q, 'D'))

    def test_set_answers_still_route_to_the_model(self):
        """CPP-376: a set answer takes any order but needs every value."""
        q = self._question('List the factors of 63 over 50', ['54, 63'],
                           answer_format=Question.ANSWER_FORMAT_SET)
        self.assertTrue(self._grade(q, '63, 54'))
        self.assertFalse(self._grade(q, '54'))

    def test_keypad_folding_reaches_the_quiz(self):
        """The model's folds (degrees, exponents) now apply here too."""
        angle = self._question('Find the angle', ['50°'])
        self.assertTrue(self._grade(angle, '50'))
        self.assertTrue(self._grade(angle, '50°'))

        area = self._question('Find the area', ['12 cm²'])
        self.assertTrue(self._grade(area, '12 cm^2'))
        self.assertTrue(self._grade(area, '12cm2'))
