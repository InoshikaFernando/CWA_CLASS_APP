"""A student answering a column-arithmetic question in a quiz, end to end.

The bug as reported: on the Year 4 multiplication quiz, question 2 of 16 stacks
867 × 8 and the student wrote 6 9 3 6 in the blue answer boxes — the right
answer, and the one the question's own explanation works out. The quiz answered
"❌ Incorrect" with no correct answer beside it.

The cause was that the quiz had no branch for ``column_operation``: a column
question is graded from its operands (that is the whole point of the type, and
what ``SELF_GRADED_ANSWER_FIELDS`` promises importers), so it carries no Answer
rows — and the typed-answer fallback the quiz dropped it into has nothing to
match against, so every submission scored zero. Worksheets and homework both
grade the type from ``column_result``; only the quiz did not. Long division
is the same contract and had the same hole, so it is covered here too.

These tests POST to the same endpoint the quiz page posts to, so what they
assert is what the student experiences.
"""
import json
import time
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Question, StudentAnswer

User = get_user_model()


class QuizAnswerMixin:
    """POST one typed answer through the endpoint the quiz page posts to."""

    def _answer(self, text, question=None):
        """Inject a topic-quiz session and submit *text* for *question*.

        The question is listed twice so the submission is never 'last', which
        keeps the quiz-completion machinery out of a pure grading check.
        """
        question = question or self.question
        session_id = str(uuid.uuid4())
        session = self.client.session
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': [{'id': question.id}, {'id': question.id}],
            'correct': 0,
            'start_time': time.time(),
            'topic_id': self.topic.id,
            'level_number': self.level.level_number,
            'subject': 'mathematics',
        }
        session.save()
        response = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({
                'session_id': session_id,
                'question_id': question.id,
                'text_answer': text,
            }),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 200)
        return response.json()


class ColumnOperationQuizGradingTests(QuizAnswerMixin, TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='columnstudent', password='pass1234',
            email='column@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Multiplication',
            slug='multiplication-column', is_active=True,
        )
        cls.topic.levels.add(cls.level)

        # Authored exactly as the live question is: the numbers to stack, the
        # operator, an explanation to read afterwards, and NO answer rows —
        # the answer is worked out from the operands.
        cls.question = Question.objects.create(
            question_text='Work out 867 × 8 using column multiplication.',
            question_type=Question.COLUMN_OPERATION,
            operands=[867, 8],
            operator='*',
            explanation=(
                '7 × 8 = 56 - write 6, carry 5. 6 × 8 = 48, plus the 5 carried '
                '= 53 - write 3, carry 5. 8 × 8 = 64, plus the 5 carried = 69. '
                'So 867 × 8 = 6936.'
            ),
            topic=cls.topic, level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='columnstudent', password='pass1234')

    # ---------------------------------------------------------------- the bug

    def test_the_reported_answer_is_now_marked_correct(self):
        """867 × 8 = 6936, typed into the four blue boxes."""
        self.assertTrue(self._answer('6936')['is_correct'])

    def test_a_wrong_product_is_still_wrong(self):
        self.assertFalse(self._answer('6836')['is_correct'])

    def test_a_wrong_answer_is_shown_the_right_one(self):
        """The reported ❌ came with nothing beside it, because there is no
        Answer row to print. The computed result stands in for it."""
        result = self._answer('6836')
        self.assertFalse(result['is_correct'])
        self.assertEqual(result['correct_answer_text'], '6936')

    def test_addition_and_subtraction_grade_the_same_way(self):
        for operands, operator, right, wrong in (
            ([347, 268], '+', '615', '515'),
            ([503, 176], '-', '327', '337'),
        ):
            q = Question.objects.create(
                question_text=f'Work out {operands[0]} {operator} {operands[1]}.',
                question_type=Question.COLUMN_OPERATION,
                operands=operands, operator=operator,
                topic=self.topic, level=self.level,
            )
            with self.subTest(operator=operator):
                self.assertTrue(self._answer(right, question=q)['is_correct'])
                self.assertFalse(self._answer(wrong, question=q)['is_correct'])

    def test_leading_zeros_and_stray_spaces_grade_as_the_number(self):
        """The boxes are per-digit, so a student who starts one column late
        submits "06936" — the same number, written with a blank box."""
        self.assertTrue(self._answer(' 06936 ')['is_correct'])

    def test_a_blank_submission_is_wrong_not_zero(self):
        self.assertFalse(self._answer('')['is_correct'])

    def test_a_stored_answer_row_still_wins_nothing_and_loses_nothing(self):
        """Imported column questions DO carry an answer row (ai_import writes
        the computed result). Grading from the operands must agree with it."""
        self.question.answers.create(answer_text='6936', is_correct=True, order=1)
        self.assertTrue(self._answer('6936')['is_correct'])
        self.assertFalse(self._answer('6836')['is_correct'])

    def test_the_answer_is_recorded_as_typed(self):
        """CPP-377's rule — a mark must be checkable against what was typed."""
        self._answer('6936')
        row = StudentAnswer.objects.get(
            student=self.student, question=self.question)
        self.assertTrue(row.is_correct)
        self.assertEqual(row.text_answer, '6936')


class LongDivisionQuizGradingTests(QuizAnswerMixin, TestCase):
    """The sibling type with the same contract, and the same hole.

    A long division is graded from ``dividend``/``divisor``, so it too may be
    authored with no Answer row — and the quiz had no branch for it either.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='divisionstudent', password='pass1234',
            email='division@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=5, display_name='Year 5')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Division', slug='division-long',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)
        cls.question = Question.objects.create(
            question_text='Work out 872 ÷ 4 using long division.',
            question_type=Question.LONG_DIVISION,
            dividend=872, divisor=4,
            topic=cls.topic, level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='divisionstudent', password='pass1234')

    def test_the_quotient_is_marked_correct(self):
        self.assertTrue(self._answer('218')['is_correct'])

    def test_an_exact_division_is_right_with_or_without_r_0(self):
        self.assertTrue(self._answer('218 r 0')['is_correct'])

    def test_a_remainder_must_match(self):
        q = Question.objects.create(
            question_text='Work out 875 ÷ 4 using long division.',
            question_type=Question.LONG_DIVISION,
            dividend=875, divisor=4,
            topic=self.topic, level=self.level,
        )
        self.assertTrue(self._answer('218 r 3', question=q)['is_correct'])
        self.assertFalse(self._answer('218', question=q)['is_correct'])
        self.assertEqual(
            self._answer('218', question=q)['correct_answer_text'], '218 r 3')

    def test_a_wrong_quotient_is_still_wrong(self):
        self.assertFalse(self._answer('217')['is_correct'])


class ColumnOperationMixedQuizTests(TestCase):
    """The mixed quiz grades through a different code path — one POST for the
    whole paper, graded on the model — so it gets the same fix or it keeps the
    same bug. It shows a column question inline ("867 × 8 =") with a single box.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='mixedstudent', password='pass1234',
            email='mixed@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=6, display_name='Year 6')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Mixed Multiplication',
            slug='multiplication-mixed', is_active=True,
        )
        cls.topic.levels.add(cls.level)
        cls.question = Question.objects.create(
            question_text='Work out 867 × 8 using column multiplication.',
            question_type=Question.COLUMN_OPERATION,
            operands=[867, 8], operator='*',
            topic=cls.topic, level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='mixedstudent', password='pass1234')

    def _sit_the_paper(self, typed):
        url = reverse('mixed_quiz', kwargs={
            'subject': 'mathematics', 'level_number': self.level.level_number,
        })
        self.assertEqual(self.client.get(url).status_code, 200)
        session_key = next(
            k for k in self.client.session.keys()
            if k.startswith('mq_') and not k.startswith('mq_result_')
        )
        response = self.client.post(url, data={
            'session_id': session_key[3:],
            f'text_{self.question.id}': typed,
        })
        self.assertIn(response.status_code, (200, 302))
        return StudentAnswer.objects.filter(
            student=self.student, question=self.question).latest('id')

    def test_the_right_product_is_marked_correct(self):
        self.assertTrue(self._sit_the_paper('6936').is_correct)

    def test_a_wrong_product_is_still_wrong(self):
        self.assertFalse(self._sit_the_paper('6836').is_correct)

    def test_the_model_grader_is_what_every_other_surface_uses(self):
        """Homework and worksheets reach the same verdict through the same
        method, so a column question marks identically wherever it is set."""
        self.assertTrue(self.question.grade_text_answer('6936'))
        self.assertFalse(self.question.grade_text_answer('6836'))
        self.assertFalse(self.question.grade_text_answer(''))

    def test_a_column_question_missing_its_numbers_still_uses_its_answer_row(self):
        """Only a question that can work its own answer out is graded from it;
        a half-authored one keeps grading against whatever it does store."""
        broken = Question.objects.create(
            question_text='Work out the product.',
            question_type=Question.COLUMN_OPERATION,
            topic=self.topic, level=self.level,
        )
        broken.answers.create(answer_text='6936', is_correct=True, order=1)
        self.assertTrue(broken.grade_text_answer('6936'))
        self.assertFalse(broken.grade_text_answer('6836'))
