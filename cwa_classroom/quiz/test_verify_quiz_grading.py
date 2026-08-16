"""Tests for ``manage.py verify_quiz_grading`` — the full-coverage weekly sweep
that answers every question through the real grading endpoint (CPP-377).

Two properties matter and are both asserted here:

  1. It detects a mismark that only shows up through real behaviour.
  2. It writes nothing — no StudentAnswer rows, no leftover user account.

Property 2 is what makes it safe to point at a live database weekly.
"""
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
