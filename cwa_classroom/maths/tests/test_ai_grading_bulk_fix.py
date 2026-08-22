"""Converting a question to AI grading from the question-health check page.

Some questions have no answer key that exact matching can hold. "160 can be
written as 100 + 60 — write two other ways 160 could be split" has infinitely
many right answers; "What does area mean?" has as many as there are ways to say
it. Stored as a plain text answer they mark every good student wrong, and until
now the only route out was Django admin — ``answer_format`` and
``validation_type`` appear in no teacher-facing editor at all.

What this pins is the route AND its guard rails. An AI-graded question is
hidden from students whose school has not bought the module
(``quiz.views.gradable_for``), so converting one that already grades correctly
costs those students the question and buys nothing. The conversion therefore
refuses the questions that do not need it, and says so per question rather than
skipping them quietly.
"""
from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from classroom.models import Level, Subject, Topic
from maths.duplicate_repair import Skipped, plan_ai_grading
from maths.models import Answer, Question
from maths.views_admin import BULK_ACTIONS, FIXES_FOR_CODE, auto_fix_sequence

User = get_user_model()


class AiGradingTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.superuser = User.objects.create_superuser(
            username='aigradeadmin', email='aig@test.com', password='pass1234')
        cls.subject, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.level = Level.objects.create(level_number=971, display_name='AI grade')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Place Value', slug='ai-place-value')

    def _question(self, text='160 can be written as 100 + 60. Write two other '
                             'ways 160 could be split.',
                  qtype=Question.SHORT_ANSWER, options=(('100 + 60', True),),
                  **kwargs):
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text=text,
            question_type=qtype, **kwargs)
        for order, (label, correct) in enumerate(options):
            Answer.objects.create(question=question, answer_text=label,
                                  is_correct=correct, order=order)
        return question


class PlanAiGradingTests(AiGradingTestBase):
    """What the planner will and will not hand to the AI grader."""

    def test_a_short_answer_with_many_right_answers_converts(self):
        self.assertTrue(plan_ai_grading(self._question()))

    def test_an_extended_answer_converts(self):
        question = self._question(
            text='Explain why the angles in a triangle sum to 180°.',
            qtype=Question.EXTENDED_ANSWER, options=())
        self.assertTrue(plan_ai_grading(question))

    def test_a_multiple_choice_question_is_refused(self):
        # Graded on Answer.is_correct, so it already marks everyone correctly.
        # Converting would only hide it from schools without the module.
        question = self._question(
            qtype=Question.MULTIPLE_CHOICE,
            options=(('160', True), ('150', False)))
        with self.assertRaises(Skipped) as caught:
            plan_ai_grading(question)
        self.assertIn('choice question', str(caught.exception))

    def test_a_true_false_question_is_refused(self):
        question = self._question(
            qtype=Question.TRUE_FALSE,
            options=(('True', True), ('False', False)))
        with self.assertRaises(Skipped):
            plan_ai_grading(question)

    def test_a_question_that_already_grades_itself_is_refused(self):
        # 'pattern' marks the answer the student invented, for free, for
        # everyone. Spending a token on it would be a straight downgrade.
        question = self._question(
            text='Make up your own number pattern.',
            answer_format=Question.ANSWER_FORMAT_PATTERN, options=())
        with self.assertRaises(Skipped) as caught:
            plan_ai_grading(question)
        self.assertIn('already grades itself', str(caught.exception))

    def test_a_teacher_graded_question_is_refused(self):
        # A standing decision by a teacher that this one needs a person. A bulk
        # sweep must not quietly overturn it.
        question = self._question(validation_type=Question.VALIDATION_HUMAN)
        with self.assertRaises(Skipped) as caught:
            plan_ai_grading(question)
        self.assertIn('teacher', str(caught.exception))

    def test_an_already_converted_question_is_a_no_op(self):
        question = self._question(validation_type=Question.VALIDATION_AI)
        self.assertFalse(plan_ai_grading(question))


class BulkConvertTests(AiGradingTestBase):
    """The fix as a reviewer runs it: tick the rows, pick it, apply."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='aigradeadmin', password='pass1234')
        self.url = reverse('question_bulk_fix_admin_dashboard')

    def _post(self, ids, action='to_ai_graded'):
        return self.client.post(
            self.url, {'action': action, 'question_id': [str(i) for i in ids]},
            follow=True)

    def _notes(self, response):
        return [m.message for m in response.context['messages']]

    def test_the_option_is_offered_on_the_page(self):
        self.assertIn('to_ai_graded', [value for value, _label in BULK_ACTIONS])

    def test_converting_sets_the_validation_type(self):
        question = self._question()
        self._post([question.id])
        question.refresh_from_db()
        self.assertEqual(Question.VALIDATION_AI, question.validation_type)

    def test_several_questions_convert_in_one_go(self):
        a = self._question()
        b = self._question(text='What does area mean?')
        self._post([a.id, b.id])
        for question in (a, b):
            question.refresh_from_db()
            self.assertEqual(Question.VALIDATION_AI, question.validation_type,
                             f'Q{question.id} was not converted')

    def test_a_refused_question_is_named_not_silently_skipped(self):
        question = self._question(
            qtype=Question.MULTIPLE_CHOICE,
            options=(('160', True), ('150', False)))
        response = self._post([question.id])
        question.refresh_from_db()
        self.assertEqual(Question.VALIDATION_AUTO, question.validation_type)
        self.assertTrue(
            any(f'Q{question.id}' in note and 'choice question' in note
                for note in self._notes(response)),
            f'no reason given for Q{question.id}: {self._notes(response)}')

    def test_one_refusal_does_not_block_the_rest_of_the_selection(self):
        good = self._question()
        refused = self._question(
            qtype=Question.MULTIPLE_CHOICE,
            options=(('160', True), ('150', False)))
        self._post([good.id, refused.id])
        good.refresh_from_db()
        refused.refresh_from_db()
        self.assertEqual(Question.VALIDATION_AI, good.validation_type)
        self.assertEqual(Question.VALIDATION_AUTO, refused.validation_type)

    def test_converting_without_a_rubric_warns(self):
        # The rubric is what the grader marks AGAINST. Without one the mark
        # drifts between two students who wrote the same thing, so a run that
        # reported a clean success here would be reporting a job half done.
        question = self._question()
        response = self._post([question.id])
        self.assertTrue(
            any('marking guide' in note and f'Q{question.id}' in note
                for note in self._notes(response)),
            f'no rubric warning: {self._notes(response)}')

    def test_converting_with_a_rubric_does_not_warn(self):
        question = self._question(
            grading_rubric='Accept any two distinct pairs summing to 160.')
        response = self._post([question.id])
        self.assertFalse(
            any('marking guide' in note for note in self._notes(response)),
            f'warned about a rubric that is present: {self._notes(response)}')

    def test_the_conversion_is_recorded_in_the_audit_log(self):
        from audit.models import AuditLog

        question = self._question()
        self._post([question.id])

        event = AuditLog.objects.filter(action='bulk_fix_to_ai_graded').first()
        self.assertIsNotNone(event)
        self.assertEqual(question.id, event.detail['question_id'])
        # The previous state is recorded, so a bad run is traceable without a
        # database restore.
        self.assertEqual(Question.VALIDATION_AUTO,
                         event.detail['validation_type_was'])

    def test_a_non_superuser_cannot_convert(self):
        student = User.objects.create_user(
            username='aigradestudent', email='ags@test.com', password='pass1234')
        question = self._question()
        self.client.force_login(student)

        self.client.post(self.url, {'action': 'to_ai_graded',
                                    'question_id': [str(question.id)]})

        question.refresh_from_db()
        self.assertEqual(Question.VALIDATION_AUTO, question.validation_type)


class AutomaticSweepTests(AiGradingTestBase):
    """"Fix automatically" must never spend money or hide a question.

    Converting to AI grading costs tokens and, for a school without the module,
    removes the question from quizzes altogether. Neither is a consequence an
    automatic sweep may choose on a reviewer's behalf.
    """

    def test_no_finding_routes_to_ai_grading(self):
        for code, fixes in FIXES_FOR_CODE.items():
            self.assertNotIn('to_ai_graded', fixes,
                             f'{code} would let "auto" convert to AI grading')

    def test_the_automatic_sequence_never_includes_it(self):
        sequence = auto_fix_sequence(set(FIXES_FOR_CODE))
        self.assertNotIn('to_ai_graded', sequence)

    def test_an_automatic_run_leaves_the_validation_type_alone(self):
        client = Client()
        client.login(username='aigradeadmin', password='pass1234')
        # A question with a real, auto-fixable fault: no correct option ticked.
        question = self._question(
            qtype=Question.MULTIPLE_CHOICE,
            text='Calculate: 1 + 2',
            options=(('3', False), ('4', False)))

        client.post(reverse('question_bulk_fix_admin_dashboard'),
                    {'action': 'auto', 'question_id': [str(question.id)]},
                    follow=True)

        question.refresh_from_db()
        self.assertEqual(Question.VALIDATION_AUTO, question.validation_type)
