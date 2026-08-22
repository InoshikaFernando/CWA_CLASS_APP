"""AI-graded questions in the quiz — who sees them, and how they are marked.

483 questions site-wide are written answers a model has to judge: Year 10
Inequalities is 19 of its 25. They carry the diagram and a full marking rubric,
but the quiz never called the AI grading service that homework and worksheets
use — it exact-matched them against an answer that does not exist, so every
student who met one lost the mark.

The rules these pin:

* **Individual students** (no school) are AI-graded, free and unmetered.
* **School students** are AI-graded when their school buys the module; when it
  does not, the questions are not shown to them at all — better a shorter quiz
  than a question that cannot be passed.
* **Teacher-graded questions** are shown to nobody: no quiz can wait for a
  teacher.
* An answer the grader could not reach a verdict on (API down, quota spent) is
  **not counted wrong** — it is dropped from the score.
"""
import json
import time
import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Question, StudentFinalAnswer
from quiz.views import gradable_for

User = get_user_model()

RUBRIC = ('Full marks: the boundary line y = 2 is solid because ≤ includes '
          'equality, and everything below it is shaded.')


def _ai_result(**overrides):
    """What grade_extended_answer returns, in the shape callers rely on."""
    result = {
        'is_correct': True,
        'score_fraction': 1.0,
        'feedback': 'Yes — solid line, shaded below.',
        'what_to_add': '',
        'cache_hit': False,
        'input_tokens': 400,
        'output_tokens': 120,
    }
    result.update(overrides)
    return result


class QuestionVisibilityTests(TestCase):
    """Who is offered an AI-graded question."""

    @classmethod
    def setUpTestData(cls):
        subject = Subject.objects.create(name='Mathematics', slug='maths-ai')
        cls.level = Level.objects.create(level_number=10, display_name='Year 10')
        cls.topic = Topic.objects.create(
            subject=subject, name='Inequalities', slug='inequalities-ai')

        cls.written = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='For y ≤ 2, describe the region.',
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI, grading_rubric=RUBRIC)
        cls.teacher_marked = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Explain your reasoning in your own words.',
            question_type=Question.SHORT_ANSWER,
            validation_type=Question.VALIDATION_HUMAN)
        cls.ordinary = Question.objects.create(
            level=cls.level, topic=cls.topic, question_text='Solve 2x + 1 > 7',
            question_type=Question.SHORT_ANSWER)

        cls.individual = User.objects.create_user(
            username='ai-individual', password='pass1234',
            email='individual@test.com')
        cls.school_student = User.objects.create_user(
            username='ai-school', password='pass1234', email='school@test.com')

    def _offered(self, user):
        return set(gradable_for(
            user, Question.objects.filter(topic=self.topic),
        ).values_list('id', flat=True))

    def test_an_individual_student_is_offered_ai_graded_questions(self):
        """No school behind them — they pay for the app, so it is included."""
        self.assertIn(self.written.id, self._offered(self.individual))

    def test_a_school_student_with_the_module_is_offered_them(self):
        with patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value='ai_grading_professional'), \
             patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[object()]):
            self.assertIn(self.written.id, self._offered(self.school_student))

    def test_a_school_student_without_the_module_is_not_shown_them(self):
        """Not marked wrong — not shown. The school did not buy this."""
        with patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None), \
             patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[object()]):
            offered = self._offered(self.school_student)
        self.assertNotIn(self.written.id, offered)
        self.assertIn(self.ordinary.id, offered)

    def test_teacher_graded_questions_are_shown_to_nobody(self):
        self.assertNotIn(self.teacher_marked.id, self._offered(self.individual))


class AIGradingThroughTheEndpointTests(TestCase):
    """Marking a written answer through the real submit endpoint."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='ai-quiz-student', password='pass1234',
            email='aiquiz@test.com')
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=10, display_name='Year 10')
        cls.topic = Topic.objects.create(
            subject=subject, name='Inequalities', slug='inequalities-endpoint',
            is_active=True)
        cls.topic.levels.add(cls.level)
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text=('For the inequality y ≤ 2, describe the region: '
                           'which side of the line should be shaded, and is '
                           'the boundary included?'),
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI, grading_rubric=RUBRIC)

    def setUp(self):
        self.client = Client()
        self.client.login(username='ai-quiz-student', password='pass1234')

    def _answer(self, text, last=False):
        session_id = str(uuid.uuid4())
        session = self.client.session
        listed = [{'id': self.question.id}]
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': listed if last else listed * 2,
            'correct': 0,
            'start_time': time.time(),
            'topic_id': self.topic.id,
            'level_number': 10,
            'subject': 'mathematics',
        }
        session.save()
        response = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({'session_id': session_id,
                             'question_id': self.question.id,
                             'text_answer': text}),
            content_type='application/json')
        self.assertEqual(response.status_code, 200)
        return response.json()

    def test_a_good_written_answer_is_marked_correct(self):
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result()) as grader:
            result = self._answer('Shade below, and the line is solid.')
        self.assertTrue(result['is_correct'])
        self.assertIn('solid line', result['feedback'])
        self.assertTrue(grader.called)

    def test_a_wrong_written_answer_is_marked_wrong_with_the_reason(self):
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result(
                       is_correct=False, score_fraction=0.0,
                       feedback='Not quite — you shaded above.',
                       what_to_add='Say whether the boundary is included.')):
            result = self._answer('Shade above the line.')
        self.assertFalse(result['is_correct'])
        self.assertIn('shaded above', result['feedback'])
        # what_to_add is appended so the student knows what was missing.
        self.assertIn('boundary is included', result['feedback'])

    def test_the_question_is_graded_by_ai_not_by_exact_match(self):
        """The bug: no stored answer, so exact match scored every answer zero."""
        self.assertFalse(self.question.answers.exists())
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result()):
            self.assertTrue(self._answer('below, solid')['is_correct'])

    # ---- the grader could not answer ------------------------------------

    def test_an_exhausted_quota_does_not_mark_the_student_wrong(self):
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result(
                       is_correct=False, quota_exceeded=True,
                       feedback='AI grading quota reached (1000/1000).')):
            result = self._answer('Shade below, and the line is solid.')
        self.assertFalse(result['is_correct'])
        self.assertTrue(result['ungraded'])
        # The billing message is never shown to the child.
        self.assertNotIn('quota', result['feedback'].lower())

    def test_a_grader_outage_does_not_mark_the_student_wrong(self):
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result(
                       is_correct=False, error='connection reset',
                       feedback='Automatic grading failed.')):
            result = self._answer('Shade below, and the line is solid.')
        self.assertTrue(result['ungraded'])

    def test_an_ungraded_answer_is_dropped_from_the_score(self):
        """Not right, not wrong, not counted — 0/1 would be a mark they did
        not lose."""
        with patch('worksheets.grading_service.grade_extended_answer',
                   return_value=_ai_result(is_correct=False,
                                           error='connection reset')):
            self._answer('Shade below, and the line is solid.', last=True)
        result = StudentFinalAnswer.objects.get(student=self.student)
        self.assertEqual(result.score, 0)
        self.assertEqual(result.total_questions, 1)  # floored, never zero
        self.assertGreaterEqual(result.points, 0)

    def test_an_empty_answer_is_not_sent_to_the_grader(self):
        """No point paying for an API call to mark a blank box."""
        with patch('worksheets.grading_service.grade_extended_answer') as grader:
            result = self._answer('')
        grader.assert_not_called()
        self.assertFalse(result['is_correct'])
        self.assertFalse(result['ungraded'])
