"""Tests for ``manage.py verify_quiz_grading`` — the full-coverage weekly sweep
that answers every question through the real grading endpoint (CPP-377).

Two properties matter and are both asserted here:

  1. It detects a mismark that only shows up through real behaviour.
  2. It writes nothing — no StudentAnswer rows, no leftover user account.

Property 2 is what makes it safe to point at a live database weekly.
"""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question, StudentAnswer

User = get_user_model()


class VerifyQuizGradingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=989, display_name='Sweep')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Sweep Fractions',
            slug='sweep-fractions', is_active=True,
        )
        cls.topic.levels.add(cls.level)

    def _question(self, text, options, question_type=Question.MULTIPLE_CHOICE):
        q = Question.objects.create(
            question_text=text, question_type=question_type,
            topic=self.topic, level=self.level,
        )
        for order, (answer_text, is_correct) in enumerate(options):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=is_correct, order=order)
        return q

    # ---------------------------------------------------------------- detect

    def test_detects_equivalent_option_mismark(self):
        """The CPP-377 shape: '2/6' equals '1/3' but is scored wrong."""
        self._question('5/6 kg less 1/2 kg?', [
            ('1/2', False), ('1/6', False), ('2/6', False), ('1/3', True),
        ])
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_quiz_grading', '--level', 989)
        self.assertEqual(ctx.exception.code, 1)

    def test_detects_question_with_no_correct_option(self):
        self._question('Unanswerable', [('1/2', False), ('1/6', False)])
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_quiz_grading', '--level', 989)
        self.assertEqual(ctx.exception.code, 1)

    def test_clean_question_passes(self):
        self._question('Calculate: 9/10 - 3/5', [
            ('2/5', False), ('6/10', False), ('3/10', True), ('1/2', False),
        ])
        call_command('verify_quiz_grading', '--level', 989)   # no SystemExit

    def test_typed_answer_question_passes(self):
        self._question(
            'Write 2.25 as a fraction.',
            [('9/4', True), ('2 1/4', True), ('4/9', False)],
            question_type='short_answer',
        )
        call_command('verify_quiz_grading', '--level', 989)

    # --------------------------------------------------------------- no writes

    def test_sweep_writes_nothing(self):
        """Everything the sweep touches is rolled back.

        This is the property that makes it safe to run weekly against a real
        database rather than only a disposable one.
        """
        self._question('Calculate: 9/10 - 3/5', [
            ('3/10', True), ('1/2', False),
        ])
        answers_before = StudentAnswer.objects.count()
        users_before = User.objects.count()

        call_command('verify_quiz_grading', '--level', 989)

        self.assertEqual(StudentAnswer.objects.count(), answers_before,
                         'the sweep left StudentAnswer rows behind')
        self.assertEqual(User.objects.count(), users_before,
                         'the sweep left its throwaway account behind')

    def test_rolls_back_even_when_it_fails(self):
        # A failing sweep exits non-zero; it must still leave no trace.
        self._question('5/6 kg less 1/2 kg?', [
            ('2/6', False), ('1/3', True),
        ])
        answers_before = StudentAnswer.objects.count()
        users_before = User.objects.count()

        with self.assertRaises(SystemExit):
            call_command('verify_quiz_grading', '--level', 989)

        self.assertEqual(StudentAnswer.objects.count(), answers_before)
        self.assertEqual(User.objects.count(), users_before)


class HostHeaderTests(TestCase):
    """The sweep must talk to the app, or say plainly that it could not.

    Pointed at production it sent Django's default ``Host: testserver``, which
    is not in prod's ALLOWED_HOSTS, so every submission was rejected with a 400
    before reaching the grader — and the sweep reported "FAILED — 280
    question(s) mismark a correct answer" about questions it had never graded.
    A tool that blames the content for its own transport failure is worse than
    one that stops.
    """

    def test_a_configured_host_is_used(self):
        from quiz.management.commands.verify_quiz_grading import _allowed_host

        with self.settings(ALLOWED_HOSTS=['www.example.co.nz', 'example.co.nz']):
            self.assertEqual(_allowed_host(), 'www.example.co.nz')

    def test_a_subdomain_wildcard_yields_the_bare_domain(self):
        from quiz.management.commands.verify_quiz_grading import _allowed_host

        with self.settings(ALLOWED_HOSTS=['.example.co.nz']):
            self.assertEqual(_allowed_host(), 'example.co.nz')

    def test_an_open_or_empty_allowed_hosts_keeps_the_default(self):
        from quiz.management.commands.verify_quiz_grading import _allowed_host

        with self.settings(ALLOWED_HOSTS=['*']):
            self.assertEqual(_allowed_host(), 'testserver')
        with self.settings(ALLOWED_HOSTS=[]):
            self.assertEqual(_allowed_host(), 'testserver')

    def test_an_unreachable_endpoint_stops_the_sweep(self):
        """It must refuse to run rather than blame every question it meets.

        Reproduces production exactly: the client sends a Host the site does
        not allow, so the app rejects every request with a 400. Before, that
        produced a per-question "endpoint error" and a final line accusing 280
        questions of mismarking. Now it stops on the first probe.
        """
        from django.core.management.base import CommandError

        with self.settings(ALLOWED_HOSTS=['www.example.co.nz']), \
                patch('quiz.management.commands.verify_quiz_grading.'
                      '_allowed_host', return_value='testserver'):
            with self.assertRaises(CommandError) as caught:
                call_command('verify_quiz_grading', stdout=StringIO(),
                             stderr=StringIO())
        message = str(caught.exception)
        self.assertIn('not reachable', message)
        self.assertIn('Nothing was graded', message)
        # The operator is told what to change, not just that it broke.
        self.assertIn('ALLOWED_HOSTS', message)
