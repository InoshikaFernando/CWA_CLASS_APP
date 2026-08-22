"""Tests for the typed-answer grading the topic quiz runs (CPP-378).

The reported bug: a sequence question storing the correct answers "32, 2" and
"32 and 2" marked a student's "32,2" **Incorrect**, on the very screen that
then told them the correct answer was "32, 2 or 32 and 2". The quiz surface had
its own copy of the exact-match rules that split each stored answer on "," and
treated the pieces as alternatives, so the complete answer never matched — while
a bare "32", half the answer, did.

An audit of the live bank (``scripts/audit_comma_answers.py``) found 559
questions leaking that way and *none* relying on comma-as-alternatives, so the
divergent copy is gone: the quiz grades on ``Question.grade_text_answer`` like
every other surface, and a fragment of a multi-value answer is now wrong.
"""
import json
import time
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question

User = get_user_model()


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
        return question.grade_text_answer(raw)

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

    def test_a_fragment_of_a_list_answer_is_wrong(self):
        """The 559-question leak: one value out of many scored full marks.

        Each of these is a real stored answer from the live bank.
        """
        for question_text, stored, fragment in (
            ('Find all the factors of 360', '1, 2, 3, 4, 5, 6, 8, 9, 10', '1'),
            ('Count in 5s', '5, 10, 15, 20, 25, 30', '5'),
            ('Write the coordinates of the red ship', '(3,11)', '(3'),
            ('Write 30% as a fraction and a decimal', '3/10, 0.3', '3/10'),
            ('List all outcomes of 3 coin tosses',
             'HHH, HHT, HTH, HTT, THH, THT, TTH, TTT', 'HHH'),
        ):
            with self.subTest(stored=stored):
                q = self._question(question_text, [stored])
                self.assertFalse(self._grade(q, fragment))
                self.assertTrue(self._grade(q, stored))

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


class SubmitTopicAnswerGradingTests(TestCase):
    """The same rules through the real endpoint the quiz page posts to.

    The model tests above cannot reach the numeric-tolerance fallback, which
    lives in the view — and that fallback had its own copy of the partial-answer
    hole: it compared the typed value against ``text.split(',')[0]``, so "32"
    graded correct for a stored "32, 2" even once the comma rule was gone.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='cpp378student', password='pass1234',
            email='cpp378@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Number Patterns',
            slug='number-patterns-cpp378', is_active=True,
        )
        cls.topic.levels.add(cls.level)
        cls.question = Question.objects.create(
            question_text='Write down the missing terms: ___, 16, 8, 4, ___, 1',
            question_type='short_answer', answer_format='text',
            topic=cls.topic, level=cls.level,
        )
        for order, text in enumerate(['32, 2', '32 and 2']):
            Answer.objects.create(question=cls.question, answer_text=text,
                                  is_correct=True, order=order)

    def setUp(self):
        self.client = Client()
        self.client.login(username='cpp378student', password='pass1234')

    def _submit(self, typed):
        session_id = str(uuid.uuid4())
        session = self.client.session
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': [{'id': self.question.id}, {'id': self.question.id}],
            'correct': 0,
            'start_time': time.time(),
            'topic_id': self.topic.id,
            'level_number': 7,
            'subject': 'mathematics',
        }
        session.save()
        resp = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({
                'session_id': session_id,
                'question_id': self.question.id,
                'text_answer': typed,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_the_screenshot(self):
        """"32,2" is the answer the feedback panel itself prints."""
        result = self._submit('32,2')
        self.assertTrue(result['is_correct'])
        self.assertEqual(result['correct_answer_text'], '32, 2 or 32 and 2')

    def test_every_punctuation_of_the_full_answer(self):
        for typed in ('32,2', '32, 2', '32 and 2'):
            with self.subTest(typed=typed):
                self.assertTrue(self._submit(typed)['is_correct'])

    def test_half_the_answer_is_wrong_even_within_tolerance(self):
        """'32' is numerically within tolerance of the first stored value."""
        self.assertFalse(self._submit('32')['is_correct'])
        self.assertFalse(self._submit('2')['is_correct'])

    def test_tolerance_still_applies_to_a_single_value_answer(self):
        q = Question.objects.create(
            question_text='Measure the line in cm', question_type='short_answer',
            answer_format='text', topic=self.topic, level=self.level,
        )
        Answer.objects.create(question=q, answer_text='7.5', is_correct=True, order=0)
        self.question, keep = q, self.question
        try:
            self.assertTrue(self._submit('7.52')['is_correct'])   # within 0.05
            self.assertFalse(self._submit('9')['is_correct'])
        finally:
            self.question = keep

    def test_digit_grouped_answer_still_grades(self):
        q = Question.objects.create(
            question_text='How many people?', question_type='short_answer',
            answer_format='text', topic=self.topic, level=self.level,
        )
        Answer.objects.create(question=q, answer_text='1,000', is_correct=True, order=0)
        self.question, keep = q, self.question
        try:
            self.assertTrue(self._submit('1000')['is_correct'])
            self.assertTrue(self._submit('1,000')['is_correct'])
        finally:
            self.question = keep
