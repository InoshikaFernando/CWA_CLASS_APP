"""Partial credit on the topic-quiz surface.

A fill-in-the-blank sentence is several answers in one question. The quiz used
to mark it all-or-nothing: nine gaps right out of ten scored the same as none,
and the feedback panel said "Incorrect" with no hint of which gap was wrong.

These drive the real answer endpoint and assert on what it sends back to the
page (the breakdown the feedback panel renders) and on what it accumulates in
the session (the credit the final points are calculated from). ``correct``
stays a count of fully-right questions — the two numbers answer different
questions and must not be conflated.
"""
import json
import time
import uuid

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.models import Question

User = get_user_model()

SENTENCE = 'Ten cents is $___, fifty cents is $___ and one dollar is $___.'
SPEC = {'blanks': [
    {'answers': ['0.10']},
    {'answers': ['0.50']},
    {'answers': ['1.00']},
]}


class TopicQuizPartialCreditTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='pcstudent', password='pass1234', email='pc@test.com')
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=977, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Money', slug='money-partial-credit',
            is_active=True)
        cls.topic.levels.add(cls.level)
        cls.question = Question.objects.create(
            question_text=SENTENCE, question_type=Question.FILL_BLANK,
            blank_spec=SPEC, topic=cls.topic, level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='pcstudent', password='pass1234')

    def _answer(self, blanks, session_extra=None):
        """Inject a topic-quiz session and post one blanks payload.

        The question appears twice so the submission is never the last one —
        that keeps the end-of-quiz save out of the way.
        """
        session_id = str(uuid.uuid4())
        session = self.client.session
        data = {
            'current': 0,
            'questions': [{'id': self.question.id}, {'id': self.question.id}],
            'correct': 0,
            'start_time': time.time(),
            'topic_id': self.topic.id,
            'level_number': 977,
            'subject': 'mathematics',
        }
        data.update(session_extra or {})
        session[f'tq_{session_id}'] = data
        session.save()
        resp = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({
                'session_id': session_id,
                'question_id': self.question.id,
                'text_answer': json.dumps({'blanks': blanks}),
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json(), self.client.session[f'tq_{session_id}']

    def test_two_gaps_of_three_are_worth_two_thirds(self):
        payload, session = self._answer(['0.10', '0.05', '1.00'])
        self.assertFalse(payload['is_correct'])
        self.assertEqual(payload['parts_correct'], 2)
        self.assertEqual(payload['parts_total'], 3)
        self.assertAlmostEqual(session['credit'], 2 / 3)
        # ...but the question was not answered correctly, so the count of
        # correct answers does not move.
        self.assertEqual(session['correct'], 0)

    def test_the_response_names_the_gap_that_was_wrong(self):
        payload, _ = self._answer(['0.10', '0.05', '1.00'])
        wrong = [p for p in payload['parts'] if not p['is_correct']]
        self.assertEqual(len(wrong), 1)
        self.assertEqual(wrong[0]['label'], 'Blank 2')
        self.assertEqual(wrong[0]['typed'], '0.05')
        self.assertEqual(wrong[0]['expected'], '0.50')
        self.assertEqual(payload['what_was_correct'],
                         '2 of the 3 blanks are right.')

    def test_every_gap_right_counts_and_scores_in_full(self):
        payload, session = self._answer(['0.10', '0.50', '1.00'])
        self.assertTrue(payload['is_correct'])
        self.assertEqual(session['correct'], 1)
        self.assertEqual(session['credit'], 1.0)

    def test_every_gap_wrong_earns_nothing(self):
        payload, session = self._answer(['9', '9', '9'])
        self.assertFalse(payload['is_correct'])
        self.assertEqual(payload['parts_correct'], 0)
        self.assertEqual(session['credit'], 0.0)

    def test_a_quiz_already_in_flight_keeps_the_marks_it_had(self):
        # A session started before partial credit shipped carries no 'credit'
        # key. It is seeded from the count so far, so the questions already
        # answered are not silently dropped from the total.
        _, session = self._answer(['0.10', '0.50', '1.00'],
                                  session_extra={'correct': 4})
        self.assertEqual(session['credit'], 5.0)
        self.assertEqual(session['correct'], 5)

    def test_the_attempt_review_records_the_breakdown(self):
        _, session = self._answer(['0.10', '0.05', '1.00'])
        entry = session['review'][0]
        self.assertEqual(entry['parts_correct'], 2)
        self.assertEqual(len(entry['parts']), 3)
