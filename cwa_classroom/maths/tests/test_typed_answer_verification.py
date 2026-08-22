"""Tests for ``verify_typed_answer_question`` — the typed-answer health checks.

Every fixture here is a real stored answer from the live bank, taken from the
``scripts/audit_comma_answers.py`` run that motivated CPP-378.

The two codes exist precisely because code cannot fix them: whether a list
answer is order-free, and whether a duplicate row was deliberate, are both
questions about what the author meant.
"""
from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.answer_verification import (
    FRAGMENT_ROW, UNMARKED_SET, verify_typed_answer_question)
from maths.models import Answer, Question, QuestionHealthSnapshot


class TypedAnswerVerificationTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=977, display_name='V')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Verify', slug='verify-typed',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)

    def _question(self, text, answers, answer_format=Question.ANSWER_FORMAT_TEXT,
                  question_type='short_answer'):
        q = Question.objects.create(
            question_text=text, question_type=question_type,
            answer_format=answer_format, topic=self.topic, level=self.level,
        )
        for order, answer_text in enumerate(answers):
            Answer.objects.create(question=q, answer_text=answer_text,
                                  is_correct=True, order=order)
        return q

    def _codes(self, question):
        return sorted(i.code for i in verify_typed_answer_question(question))

    # ------------------------------------------------------- UNMARKED-SET

    def test_collection_questions_are_flagged(self):
        for text, stored in (
            ('Find all the factors of 360.',
             '1, 2, 3, 4, 5, 6, 8, 9, 10, 12, 15, 18, 20, 24, 30, 36'),
            ('Write down the factors of 30.', '1, 2, 3, 5, 6, 10, 15, 30'),
            ('Write down the prime factors of 30.', '2, 3, 5'),
            ('List all possible outcomes for tossing a coin 3 times.',
             'HHH, HHT, HTH, HTT, THH, THT, TTH, TTT'),
        ):
            with self.subTest(text=text):
                self.assertIn(UNMARKED_SET, self._codes(self._question(text, [stored])))

    def test_ordered_questions_are_not_flagged(self):
        """The order IS the answer here — flagging these would be noise."""
        for text, stored in (
            ('Arrange the following fractions in ascending order.',
             '1/20, 1/5, 1/4, 3/10, 3/2'),
            ('Write down the missing terms in the sequence: ___, 16, 8, 4, ___, 1',
             '32, 2'),
            ('Order these decimal numbers from smallest to largest.',
             '0.2, 0.23, 0.51'),
            ('Write the next three numbers in this sequence: 20, 17, 14',
             '11, 8, 5'),
        ):
            with self.subTest(text=text):
                self.assertNotIn(UNMARKED_SET, self._codes(self._question(text, [stored])))

    def test_a_question_already_marked_as_a_set_is_not_flagged(self):
        q = self._question('Find all the factors of 12.', ['1, 2, 3, 4, 6, 12'],
                           answer_format=Question.ANSWER_FORMAT_SET)
        self.assertNotIn(UNMARKED_SET, self._codes(q))

    def test_single_value_answers_are_not_flagged(self):
        q = self._question('Find all the factors of 7.', ['7'])
        self.assertNotIn(UNMARKED_SET, self._codes(q))

    # ------------------------------------------------------- FRAGMENT-ROW

    def test_a_row_holding_one_value_of_another_row_is_flagged(self):
        """Q23478's shape: the list, plus a bare row for its last value."""
        q = self._question('Write the number of squares in each pattern.',
                           ['3, 5, 7, 9', '9'])
        self.assertIn(FRAGMENT_ROW, self._codes(q))

    def test_genuine_alternative_spellings_are_not_flagged(self):
        """Q18846/Q24783: two spellings of the SAME whole answer."""
        for stored in (
            ['6/25 and 0.24', '6/25, 0.24'],
            ['(4,4)', '4,4'],
            ['32, 2', '32 and 2'],
        ):
            with self.subTest(stored=stored):
                self.assertNotIn(FRAGMENT_ROW, self._codes(self._question('Q', stored)))

    # ------------------------------------------------------------- scope

    def test_choice_questions_are_left_to_verify_question(self):
        q = self._question('Find all the factors of 360.', ['1, 2, 3'],
                           question_type=Question.MULTIPLE_CHOICE)
        self.assertEqual(self._codes(q), [])

    def test_a_clean_typed_question_reports_nothing(self):
        self.assertEqual(self._codes(self._question('What is 5 + 5?', ['10'])), [])


class TypedAnswersReachTheHealthSnapshotTests(TestCase):
    """The checks are only worth having if the dashboard actually runs them.

    Typed answers were excluded from both ``verify_question_answers`` and
    ``record_question_health``, so the whole 11k-question typed population was
    invisible to the health number (CPP-378).
    """

    @classmethod
    def setUpTestData(cls):
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )
        cls.level = Level.objects.create(level_number=976, display_name='H')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Health', slug='health-typed',
            is_active=True,
        )
        cls.topic.levels.add(cls.level)
        for text, answers in (
            ('Find all the factors of 360.', ['1, 2, 3, 4, 5, 6']),
            ('Write the number of squares in each pattern.', ['3, 5, 7, 9', '9']),
            ('What is 5 + 5?', ['10']),
        ):
            q = Question.objects.create(
                question_text=text, question_type='short_answer',
                answer_format=Question.ANSWER_FORMAT_TEXT,
                topic=cls.topic, level=cls.level,
            )
            for order, answer_text in enumerate(answers):
                Answer.objects.create(question=q, answer_text=answer_text,
                                      is_correct=True, order=order)

    def test_snapshot_counts_typed_questions_and_their_issues(self):
        call_command('record_question_health', '--level', 976)
        snapshot = QuestionHealthSnapshot.objects.latest('created_at')
        self.assertEqual(snapshot.typed_questions, 3)
        self.assertEqual(snapshot.questions_blocking, 2)
        self.assertEqual(snapshot.issue_counts,
                         {UNMARKED_SET: 1, FRAGMENT_ROW: 1})

    def test_health_percent_counts_the_typed_population(self):
        """Two broken typed answers out of three is not a 100% healthy bank."""
        call_command('record_question_health', '--level', 976)
        snapshot = QuestionHealthSnapshot.objects.latest('created_at')
        self.assertEqual(snapshot.choice_questions, 0)
        self.assertEqual(snapshot.health_percent, 33.3)

    def test_the_audit_command_fails_on_a_typed_issue(self):
        with self.assertRaises(SystemExit) as ctx:
            call_command('verify_question_answers', '--level', 976)
        self.assertEqual(ctx.exception.code, 1)
