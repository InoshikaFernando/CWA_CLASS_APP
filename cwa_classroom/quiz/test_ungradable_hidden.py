"""The quiz must not serve a question it cannot mark FOR THIS STUDENT.

483 questions site-wide are ``extended_answer`` or ``validation_type`` of
``ai_graded`` / ``human_graded`` — written answers a person or a model has to
judge. The quiz served them to everyone and then graded them by exact match
against a stored answer that, by definition, does not exist, so every student
who met one lost the mark whatever they wrote. Year 10 Inequalities is 19 of
its 25 questions; Year 9 Angles is 34 of 59.

Who now sees them is in ``test_ai_graded_quiz.py``. What this file pins is the
other half: a student the quiz CANNOT AI-grade — one at a school without the
module — is not shown those questions at all, and the shorter quiz that leaves
is visible in the log rather than looking like thin content.
"""
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question
from quiz.views import gradable_for

User = get_user_model()


def no_ai_grading():
    """Stand in for a student at a school that has not bought the module."""
    return patch('worksheets.grading_service.student_can_be_ai_graded',
                 return_value=False)


class GradableForTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='gradable-student', password='pass1234',
            email='gradable@test.com')
        subject = Subject.objects.create(name='Mathematics', slug='maths-grad')
        cls.level = Level.objects.create(level_number=10, display_name='Year 10')
        cls.topic = Topic.objects.create(
            subject=subject, name='Inequalities', slug='inequalities-grad')

        def make(text, **kwargs):
            question = Question.objects.create(
                level=cls.level, topic=cls.topic, question_text=text,
                question_type=kwargs.pop('question_type', Question.SHORT_ANSWER),
                **kwargs)
            Answer.objects.create(question=question, answer_text='x',
                                  is_correct=True)
            return question

        cls.markable = make('Solve 2x + 1 > 7')
        cls.choice = make('Which is true?',
                          question_type=Question.MULTIPLE_CHOICE)
        cls.pattern = make('Make up your own number pattern.',
                           answer_format=Question.ANSWER_FORMAT_PATTERN)
        # The real shape of the hidden ones: written answer, rubric, no key.
        cls.written = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text=('For the inequality y ≤ 2, describe the region: '
                           'which side of the line should be shaded?'),
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI,
            grading_rubric='Full marks: boundary solid, everything below shaded.')
        cls.teacher_marked = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Explain your reasoning.',
            question_type=Question.SHORT_ANSWER,
            validation_type=Question.VALIDATION_HUMAN)

    def _kept(self, ai_graded=False):
        if ai_graded:
            return set(gradable_for(
                self.student, Question.objects.filter(topic=self.topic),
            ).values_list('id', flat=True))
        with no_ai_grading():
            return set(gradable_for(
                self.student, Question.objects.filter(topic=self.topic),
            ).values_list('id', flat=True))

    def test_questions_the_quiz_can_mark_are_kept(self):
        kept = self._kept()
        self.assertIn(self.markable.id, kept)
        self.assertIn(self.choice.id, kept)

    def test_a_created_pattern_question_is_kept(self):
        # It has no stored answer either, but the quiz CAN mark it.
        self.assertIn(self.pattern.id, self._kept())

    def test_an_ai_graded_written_question_is_hidden_without_the_module(self):
        self.assertNotIn(self.written.id, self._kept())

    def test_the_same_question_is_offered_when_ai_grading_is_available(self):
        self.assertIn(self.written.id, self._kept(ai_graded=True))

    def test_a_human_graded_question_is_hidden_from_everyone(self):
        # No quiz can wait for a teacher, whatever the school pays for.
        self.assertNotIn(self.teacher_marked.id, self._kept())
        self.assertNotIn(self.teacher_marked.id, self._kept(ai_graded=True))


class TopicQuizHidesUngradableTests(TestCase):
    """Through the real quiz page, not the helper."""

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='quiz-hidden-student', password='pass1234',
            email='quizhidden@test.com')
        subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=9, display_name='Year 9')
        cls.topic = Topic.objects.create(
            subject=subject, name='Angles', slug='angles-hidden', is_active=True)
        cls.topic.levels.add(cls.level)

        cls.markable = Question.objects.create(
            level=cls.level, topic=cls.topic, question_text='Find angle a.',
            question_type=Question.SHORT_ANSWER)
        Answer.objects.create(question=cls.markable, answer_text='50',
                              is_correct=True)
        cls.written = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Explain why the angles are equal.',
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI)

    def setUp(self):
        self.client.login(username='quiz-hidden-student', password='pass1234')

    def _start_quiz(self):
        """Start the quiz as a student whose school has no AI grading."""
        with no_ai_grading():
            return self.client.get(
                f'/maths/level/{self.level.level_number}'
                f'/topic/{self.topic.id}/quiz/')

    def test_the_unmarkable_question_is_not_served(self):
        response = self._start_quiz()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_questions'], 1)
        self.assertEqual(response.context['question'].id, self.markable.id)
        session = [v for k, v in self.client.session.items()
                   if k.startswith('tq_')][0]
        self.assertEqual([q['id'] for q in session['questions']],
                         [self.markable.id])

    def test_shortening_a_quiz_is_logged_not_silent(self):
        with self.assertLogs('quiz.views', level='WARNING') as logs:
            self._start_quiz()
        self.assertIn('1 of 2 questions hidden', '\n'.join(logs.output))

    def test_a_topic_with_nothing_markable_says_so(self):
        """Better an honest "nothing here yet" than a quiz nobody can pass."""
        self.markable.delete()
        response = self._start_quiz()
        self.assertEqual(response.status_code, 302)
