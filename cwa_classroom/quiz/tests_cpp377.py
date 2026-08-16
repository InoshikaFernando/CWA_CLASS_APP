"""End-to-end demonstration of the CPP-377 defect through the real grading
endpoint (``SubmitTopicAnswerView``), using the actual production question
data from Year 7 topic 75.

These tests do not exercise a detector or a helper — they POST to the same
view the quiz page posts to, so what they assert is what a student experiences.

Two of them encode behaviour that is currently broken and are marked
``xfail(strict=True)``: they document the defect without turning CI red, and
the moment either is fixed the suite fails with XPASS, forcing the marker to
be removed. The bug cannot be quietly re-broken or quietly fixed.
"""
import json
import time
import uuid

import pytest

from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from django.contrib.auth import get_user_model
from maths.models import Answer, Question

User = get_user_model()


class EquivalentDistractorGradingTests(TestCase):
    """Production Q6009: 'A bag contains 5/6 kg of apples. If 1/2 kg is
    removed, how much is left?'

        [correct] '1/3'      '1/2'      '1/6'      '2/6'

    5/6 - 1/2 = 2/6 = 1/3. A student who works it correctly and picks '2/6'
    — their own answer, unsimplified — is marked wrong.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='cpp377student', password='pass1234',
            email='cpp377@test.com',
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=7, display_name='Year 7')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Fractions', slug='fractions-cpp377',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)

        cls.question = Question.objects.create(
            question_text=(
                'A bag contains 5/6 kg of apples. If 1/2 kg is removed, '
                'how much is left?'
            ),
            question_type=Question.MULTIPLE_CHOICE,
            topic=cls.topic, level=cls.level,
        )
        cls.opt_half = Answer.objects.create(
            question=cls.question, answer_text='1/2', is_correct=False, order=0)
        cls.opt_sixth = Answer.objects.create(
            question=cls.question, answer_text='1/6', is_correct=False, order=1)
        cls.opt_two_sixths = Answer.objects.create(
            question=cls.question, answer_text='2/6', is_correct=False, order=2)
        cls.opt_third = Answer.objects.create(
            question=cls.question, answer_text='1/3', is_correct=True, order=3)

    def setUp(self):
        self.client = Client()
        self.client.login(username='cpp377student', password='pass1234')

    def _pick(self, answer):
        """Inject a topic-quiz session and POST one selected option.

        The question appears twice so the submission is never 'last' — keeps
        the quiz-completion machinery out of the way.
        """
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
                'answer_id': answer.id,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    # ---------------------------------------------------------- baseline

    def test_simplified_answer_is_marked_correct(self):
        """The control: picking '1/3' works. Proves the harness is sound."""
        self.assertTrue(self._pick(self.opt_third)['is_correct'])

    def test_genuinely_wrong_answer_is_marked_wrong(self):
        """The other control: '1/6' is not the answer and is marked wrong."""
        self.assertFalse(self._pick(self.opt_sixth)['is_correct'])

    # ------------------------------------------------------------- the bug

    @pytest.mark.xfail(strict=True, reason='CPP-377: 2/6 == 1/3 but is marked wrong')
    def test_unsimplified_correct_answer_is_marked_correct(self):
        """THE DEFECT. '2/6' == '1/3'. The student did the maths right.

        This assertion encodes the CORRECT behaviour, so it fails on current
        code — that failure is the reproduction of CPP-377.
        """
        self.assertTrue(
            self._pick(self.opt_two_sixths)['is_correct'],
            "'2/6' equals the correct answer '1/3' but was marked wrong",
        )

    @pytest.mark.xfail(strict=True, reason='CPP-377: selected_answer is never saved')
    def test_selected_answer_is_recorded(self):
        """Second defect: quiz/views.py saves only is_correct, never
        selected_answer, so there is no record of what the student clicked.

        This is why CPP-377 could not be diagnosed from the data — we know
        which questions were marked wrong, but not which option was chosen.
        """
        from maths.models import StudentAnswer

        self._pick(self.opt_two_sixths)
        row = StudentAnswer.objects.filter(
            student=self.student, question=self.question,
        ).latest('answered_at')
        self.assertIsNotNone(
            row.selected_answer,
            'StudentAnswer.selected_answer was not recorded — the chosen '
            'option is unrecoverable',
        )
