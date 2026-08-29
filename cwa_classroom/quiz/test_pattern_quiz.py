"""A student answering a "create your own pattern" question, end to end.

The bug as reported: on /maths/level/4/topic/147/quiz/, question 2 of 16 asks
"Create your own tricky subtraction number pattern of six numbers and write
down the rule you used". A student typed ``20,18, 16, 14, 12, 10`` — six
numbers, two off each time — and the quiz answered "❌ Incorrect" with no
correct answer beside it, because the question stores no correct Answer row for
the grader to match against. Nobody could ever get it right.

These tests POST to the same endpoint the quiz page posts to, so what they
assert is what the student experiences.
"""
import json
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Question, StudentAnswer

User = get_user_model()


class CreateYourOwnPatternGradingTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='cpp388student', password='pass1234',
            email='cpp388@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Patterns', slug='patterns-cpp388',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)

        # Authored exactly as the live question is: an open instruction, an
        # explanation to read afterwards, and NO answer rows.
        cls.question = Question.objects.create(
            question_text=(
                'Create your own tricky subtraction number pattern of six '
                'numbers and write down the rule you used.'
            ),
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_PATTERN,
            explanation=(
                'A subtraction pattern takes away the same amount each time, '
                'e.g. rule -7 gives 60, 53, 46, 39, 32, 25.'
            ),
            topic=cls.topic, level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='cpp388student', password='pass1234')

    def _answer(self, text, question=None):
        """Inject a topic-quiz session and POST one typed answer.

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
            'level_number': 4,
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

    # ---------------------------------------------------------------- the bug

    def test_the_reported_answer_is_now_marked_correct(self):
        result = self._answer('20,18, 16, 14, 12, 10')
        self.assertTrue(result['is_correct'])

    def test_the_mark_comes_with_a_reason(self):
        """A question with no printable answer has nothing else to show for
        itself — a bare ❌ told the student nothing at all."""
        result = self._answer('20,18, 16, 14, 12, 10')
        self.assertIn('goes down by 2', result['feedback'])

    def test_a_pattern_that_is_not_a_pattern_is_still_wrong(self):
        result = self._answer('20, 18, 15, 14, 12, 10')
        self.assertFalse(result['is_correct'])
        self.assertIn('18 to 15', result['feedback'])

    def test_a_wrong_answer_is_shown_a_worked_example(self):
        result = self._answer('7')
        self.assertFalse(result['is_correct'])
        # The "Correct answer:" line the quiz card renders when it got it wrong.
        self.assertIn('for example', result['correct_answer_text'].lower())

    def test_the_answer_is_recorded_as_typed(self):
        """CPP-377's rule — a mark must be checkable against what was typed."""
        self._answer('20, 18, 16, 14, 12, 10')
        row = StudentAnswer.objects.get(
            student=self.student, question=self.question)
        self.assertTrue(row.is_correct)
        self.assertEqual(row.text_answer, '20, 18, 16, 14, 12, 10')

    # -------------------------------------------------- never sent to the AI

    def test_a_pattern_question_is_never_sent_to_the_ai_grader(self):
        """These are authored as written answers, so the AI branch used to
        claim them first — and Claude marked a pattern running the wrong way
        ✅ Correct above its own feedback saying it was not. The arithmetic
        decides them outright; no model is asked."""
        ai_question = Question.objects.create(
            question_text=(
                'Create your own tricky subtraction number pattern of six '
                'numbers and write down the rule you used.'
            ),
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_PATTERN,
            validation_type=Question.VALIDATION_AI,
            topic=self.topic, level=self.level,
        )
        with patch('worksheets.grading_service.grade_extended_answer') as grader:
            wrong = self._answer('5, 8, 11, 14, 17, 20', question=ai_question)
            right = self._answer('20, 18, 16, 14, 12, 10', question=ai_question)
        grader.assert_not_called()
        # An ADDITION pattern for a SUBTRACTION question is wrong, and the mark
        # says why rather than praising it.
        self.assertFalse(wrong['is_correct'])
        self.assertIn('subtraction', wrong['feedback'].lower())
        self.assertTrue(right['is_correct'])

    # ------------------------------------------------------------- the guard

    def test_an_untagged_question_with_no_answer_is_still_marked_wrong(self):
        """Only questions tagged ``answer_format='pattern'`` are graded this
        way. A question missing its answer by mistake must keep failing loudly
        rather than start accepting anything typed at it."""
        untagged = Question.objects.create(
            question_text='What is 5531 - 4414?',
            question_type=Question.SHORT_ANSWER,
            topic=self.topic, level=self.level,
        )
        with self.assertLogs('quiz.views', level='WARNING') as logs:
            result = self._answer('1117', question=untagged)
        self.assertFalse(result['is_correct'])
        self.assertIn('no stored correct answer', '\n'.join(logs.output))


class PatternQuestionsInTheMixedQuizTests(TestCase):
    """The mixed quiz grades through a different code path (one POST for the
    whole paper), so it gets the same fix or it keeps the same bug."""

    @classmethod
    def setUpTestData(cls):
        cls.level, _ = Level.objects.get_or_create(
            level_number=992, defaults={'display_name': 'mixed fixture'})
        cls.question = Question.objects.create(
            question_text=('Make up your own addition number pattern of four '
                           'numbers.'),
            question_type=Question.SHORT_ANSWER,
            answer_format=Question.ANSWER_FORMAT_PATTERN,
            level=cls.level,
        )

    def test_the_shared_short_answer_grader_accepts_a_valid_pattern(self):
        from quiz.views import _correct_answer_texts

        # Nothing stored, by design — which is what used to make it unanswerable.
        self.assertEqual(_correct_answer_texts(self.question), [])
        self.assertTrue(self.question.grade_text_answer('5, 8, 11, 14'))
        self.assertFalse(self.question.grade_text_answer('14, 11, 8, 5'))
