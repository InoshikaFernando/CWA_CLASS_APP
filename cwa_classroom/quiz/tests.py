"""
quiz/tests.py — Audit logging tests for quiz views (CPP-270).
"""
import json
import time
import uuid
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from audit.models import AuditLog
from classroom.models import Level, School, SchoolStudent, Subject, Topic
from maths.models import Answer, BasicFactsResult, Question, StudentFinalAnswer

User = get_user_model()


class QuizAuditLoggingTestBase(TestCase):
    """Shared fixtures for quiz audit tests."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Test School')
        cls.student = User.objects.create_user(
            username='quizstudent', password='pass1234', email='qs@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )

        # Create a subject, topic, and level with questions for topic quiz
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Addition', slug='addition', is_active=True,
        )
        cls.topic.levels.add(cls.level)

        # Create questions with answers for the topic
        cls.questions = []
        for i in range(12):
            q = Question.objects.create(
                question_text=f'What is {i}+1?',
                question_type='multiple_choice',
                topic=cls.topic,
                level=cls.level,
            )
            Answer.objects.create(question=q, answer_text=str(i + 1), is_correct=True, order=1)
            Answer.objects.create(question=q, answer_text=str(i + 2), is_correct=False, order=2)
            cls.questions.append(q)

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()


class TestBasicFactsQuizAuditLog(QuizAuditLoggingTestBase):
    """BasicFactsQuizView.post logs maths_quiz_completed."""

    def test_basic_facts_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a basic facts quiz to get a session
        url = reverse('basic_facts_quiz', kwargs={
            'subtopic': 'Addition', 'level_number': 100,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Extract session_id from session
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('bf_') and not k.startswith('bf_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No basic facts session key found')
        session_id = session_key[3:]  # strip 'bf_'

        # Submit answers
        data = {'session_id': session_id}
        session_data = session[session_key]
        for q in session_data['questions']:
            data[f'answer_{q["id"]}'] = str(q['answer'])

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.category, 'data_change')
        self.assertEqual(log.detail['quiz_type'], 'basic_facts')
        self.assertIn('score', log.detail)
        self.assertIn('points', log.detail)


class TestTopicQuizAuditLog(QuizAuditLoggingTestBase):
    """SubmitTopicAnswerView logs maths_quiz_completed on last answer."""

    def test_topic_quiz_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a topic quiz
        url = reverse('topic_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
            'topic_id': self.topic.id,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Find session key
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('tq_') and not k.startswith('tq_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No topic quiz session key found')
        session_id = session_key[3:]

        # Submit all answers via the AJAX endpoint
        session_data = session[session_key]
        submit_url = reverse('api_submit_topic_answer')
        for q_data in session_data['questions']:
            q = Question.objects.get(pk=q_data['id'])
            correct = q.answers.filter(is_correct=True).first()
            resp = self.client.post(
                submit_url,
                data=json.dumps({
                    'session_id': session_id,
                    'question_id': q.id,
                    'answer_id': correct.id,
                }),
                content_type='application/json',
            )
            self.assertEqual(resp.status_code, 200)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.detail['quiz_type'], 'topic')
        self.assertEqual(log.detail['topic_name'], 'Addition')
        self.assertIn('result_id', log.detail)


class TestMixedQuizAuditLog(QuizAuditLoggingTestBase):
    """MixedQuizView.post logs maths_quiz_completed."""

    def test_mixed_quiz_completion_logs_event(self):
        self.client.login(username='quizstudent', password='pass1234')

        # Start a mixed quiz
        url = reverse('mixed_quiz', kwargs={
            'subject': 'mathematics',
            'level_number': 4,
        })
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

        # Find session key
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('mq_') and not k.startswith('mq_result_'):
                session_key = k
                break
        self.assertIsNotNone(session_key, 'No mixed quiz session key found')
        session_id = session_key[3:]
        session_data = session[session_key]

        # Submit answers
        data = {'session_id': session_id}
        for qid in session_data['question_ids']:
            q = Question.objects.get(pk=qid)
            correct = q.answers.filter(is_correct=True).first()
            if q.question_type in ('multiple_choice', 'true_false'):
                data[f'answer_{q.id}'] = str(correct.id)
            else:
                data[f'text_{q.id}'] = correct.answer_text

        resp = self.client.post(url, data)
        self.assertEqual(resp.status_code, 302)

        log = AuditLog.objects.filter(action='maths_quiz_completed').first()
        self.assertIsNotNone(log, 'No maths_quiz_completed audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.detail['quiz_type'], 'mixed')
        self.assertIn('score', log.detail)


class TestAuditLogResilience(QuizAuditLoggingTestBase):
    """log_event failure must not break quiz submission."""

    def test_log_event_failure_does_not_break_basic_facts(self):
        self.client.login(username='quizstudent', password='pass1234')

        url = reverse('basic_facts_quiz', kwargs={
            'subtopic': 'Addition', 'level_number': 100,
        })
        resp = self.client.get(url)
        session = self.client.session
        session_key = None
        for k in session.keys():
            if k.startswith('bf_') and not k.startswith('bf_result_'):
                session_key = k
                break
        session_id = session_key[3:]
        session_data = session[session_key]

        data = {'session_id': session_id}
        for q in session_data['questions']:
            data[f'answer_{q["id"]}'] = str(q['answer'])

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.post(url, data)

        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            BasicFactsResult.objects.filter(student=self.student).exists(),
            'BasicFactsResult not created when log_event failed',
        )


class TestTopicQuizMeasureGrading(TestCase):
    """SubmitTopicAnswerView grades a `measure` question by tolerance.

    Regression guard: `measure` stores its target in numeric_answer (not an
    Answer row), so without a dedicated grading branch it falls through to the
    Answer-row path, finds nothing, and is marked wrong every time.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Measure School')
        cls.student = User.objects.create_user(
            username='measurestudent', password='pass1234', email='ms@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Angles', slug='angles', is_active=True,
        )
        cls.topic.levels.add(cls.level)
        # 135° angle, accept ± 2°.
        cls.q = Question.objects.create(
            question_text='Measure angle a.',
            question_type='measure',
            numeric_answer=Decimal('135'),
            answer_tolerance=Decimal('2'),
            answer_unit='°',
            topic=cls.topic,
            level=cls.level,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='measurestudent', password='pass1234')

    def _submit(self, text_answer):
        """Inject a topic-quiz session and POST one measure answer.

        Two questions in the list so this submission is never 'last' — keeps the
        quiz-completion machinery (StudentFinalAnswer, stats) out of the way.
        """
        session_id = str(uuid.uuid4())
        session = self.client.session
        session[f'tq_{session_id}'] = {
            'current': 0,
            'questions': [{'id': self.q.id}, {'id': self.q.id}],
            'correct': 0,
            'start_time': time.time(),
            'level_number': 4,
            'subject': 'mathematics',
        }
        session.save()
        resp = self.client.post(
            reverse('api_submit_topic_answer'),
            data=json.dumps({
                'session_id': session_id,
                'question_id': self.q.id,
                'text_answer': text_answer,
            }),
            content_type='application/json',
        )
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def test_within_tolerance_is_correct(self):
        # 134 is within 135 ± 2.
        self.assertTrue(self._submit('134')['is_correct'])

    def test_on_tolerance_edge_is_correct(self):
        # 133 is exactly on the lower edge (135 - 2).
        self.assertTrue(self._submit('133')['is_correct'])

    def test_outside_tolerance_is_incorrect(self):
        # 120 is well outside the band.
        self.assertFalse(self._submit('120')['is_correct'])

    def test_unit_suffix_stripped_from_typed_value(self):
        # The grader strips the unit, so "135°" reads as 135.
        self.assertTrue(self._submit('135°')['is_correct'])

    def test_correct_answer_text_reports_value_and_unit(self):
        data = self._submit('120')
        self.assertEqual(data['correct_answer_text'], '135°')

    def test_topic_question_partial_renders_protractor_stage(self):
        """The quiz render branch mounts the shared measure tool (protractor for
        degrees) with the figure + numeric input."""
        from django.template.loader import render_to_string

        html = render_to_string('quiz/partials/topic_question.html', {
            'question': self.q,
            'answers': [],
            'session_id': 'abc',
            'question_number': 1,
            'total_questions': 2,
        })
        self.assertIn('data-measure-tool="protractor"', html)
        self.assertIn('measure-figure', html)          # generated angle figure
        self.assertIn('id="text-answer-input"', html)  # numeric box for the reading

    def test_topic_question_partial_renders_ruler_for_length(self):
        """A length-unit measure question gets a ruler instead of a protractor."""
        from django.template.loader import render_to_string

        self.q.answer_unit = 'cm'
        self.q.save(update_fields=['answer_unit'])
        html = render_to_string('quiz/partials/topic_question.html', {
            'question': self.q,
            'answers': [],
            'session_id': 'abc',
            'question_number': 1,
            'total_questions': 2,
        })
        self.assertIn('data-measure-tool="ruler"', html)


class TimesTablesSelectViewTest(TestCase):
    """CPP-304: 'Pick Another Table' was rendering a blank page because
    TimesTablesSelectView didn't pass all_tables or year to the template."""

    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Test School')
        cls.student = User.objects.create_user(
            username='ttstudent', password='pass1234', email='tt@test.com',
        )
        SchoolStudent.objects.create(
            school=cls.school, student=cls.student, is_active=True,
        )
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')

    def setUp(self):
        self.client = Client()
        self.client.login(username='ttstudent', password='pass1234')

    def test_multiplication_select_returns_200(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_division_select_returns_200(self):
        url = reverse('division_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_select_view_context_has_all_tables(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertIn('all_tables', resp.context)
        self.assertEqual(list(resp.context['all_tables']), list(range(1, 16)))

    def test_select_view_context_has_year(self):
        url = reverse('multiplication_select', kwargs={'level_number': 4})
        resp = self.client.get(url)
        self.assertIn('year', resp.context)
        self.assertEqual(resp.context['year'], 4)
