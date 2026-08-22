"""Tests for the set_pattern_answer_format management command.

The command is the half of the fix that reaches the questions already in the
catalogue: the grader only runs on a question tagged ``answer_format='pattern'``,
and none of them were tagged, because the format did not exist when they were
written.
"""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import Level, Subject, Topic
from maths.models import Answer, Question


class SetPatternAnswerFormatTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.patterns = Topic.objects.create(
            name='Patterns', slug='patterns', subject=subject)
        cls.other = Topic.objects.create(
            name='Number', slug='number', subject=subject)

        def make(topic, text, qtype=Question.SHORT_ANSWER, answer=None):
            question = Question.objects.create(
                level=cls.level, topic=topic, question_type=qtype,
                question_text=text,
            )
            if answer:
                Answer.objects.create(question=question, answer_text=answer,
                                      is_correct=True)
            return question

        cls.open_question = make(cls.patterns, (
            'Create your own tricky subtraction number pattern of six numbers '
            'and write down the rule you used.'))
        cls.also_open = make(cls.patterns,
                             'Make up your own multiplication pattern.')
        cls.continue_it = make(cls.patterns, (
            'Write down the next three numbers in this pattern: 3, 6, 9.'),
            answer='12, 15, 18')
        cls.arithmetic = make(cls.other, 'What is 5531 - 4414?', answer='1117')
        # An invent-your-own question that someone gave a worked example to —
        # tagging it would stop that example being accepted, so it is skipped
        # unless the operator asks for it.
        cls.answered = make(cls.patterns,
                            'Make up your own addition pattern of four numbers.',
                            answer='2, 4, 6, 8')
        # Choice questions ignore answer_format entirely.
        cls.choice = make(cls.patterns, 'Create your own number pattern.',
                          qtype=Question.MULTIPLE_CHOICE)

    def _run(self, *args):
        out = StringIO()
        call_command('set_pattern_answer_format', *args, stdout=out, stderr=out)
        return out.getvalue()

    def _format(self, question):
        question.refresh_from_db()
        return question.answer_format

    def test_dry_run_reports_but_writes_nothing(self):
        output = self._run()
        self.assertIn(f'Q{self.open_question.id}', output)
        self.assertIn('Dry run', output)
        self.assertEqual(self._format(self.open_question), 'text')

    def test_apply_tags_only_the_invent_your_own_questions(self):
        self._run('--apply')
        self.assertEqual(self._format(self.open_question), 'pattern')
        self.assertEqual(self._format(self.also_open), 'pattern')
        # "Continue this pattern" has a real answer and must keep matching it.
        self.assertEqual(self._format(self.continue_it), 'text')
        self.assertEqual(self._format(self.arithmetic), 'text')
        self.assertEqual(self._format(self.choice), 'text')

    def test_a_question_with_a_stored_answer_is_listed_but_left_alone(self):
        output = self._run('--apply')
        self.assertEqual(self._format(self.answered), 'text')
        self.assertIn(f'Q{self.answered.id}', output)
        self.assertIn('2, 4, 6, 8', output)

    def test_include_answered_tags_it_when_the_operator_asks(self):
        self._run('--apply', '--include-answered')
        self.assertEqual(self._format(self.answered), 'pattern')

    def test_the_run_is_idempotent(self):
        self._run('--apply')
        output = self._run('--apply')
        self.assertIn('Questions to tag as pattern-graded: 0', output)

    def test_scope_can_be_narrowed_to_one_topic(self):
        self._run('--apply', '--topic', str(self.other.id))
        self.assertEqual(self._format(self.open_question), 'text')

    def test_tagging_makes_the_question_gradable(self):
        """The point of the whole command: before it, the student's answer is
        wrong whatever they write; after it, it is graded on its merits."""
        self.assertFalse(
            self.open_question.grade_text_answer('20, 18, 16, 14, 12, 10'))
        self._run('--apply')
        self.open_question.refresh_from_db()
        self.assertTrue(
            self.open_question.grade_text_answer('20, 18, 16, 14, 12, 10'))
        self.assertFalse(
            self.open_question.grade_text_answer('2, 4, 6, 8, 10, 12'))
