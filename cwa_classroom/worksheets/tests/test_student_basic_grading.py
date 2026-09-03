"""The money guard: no model call on behalf of a student who is not entitled.

The quiz already never OFFERS an AI-graded question to a Student Basic student
(``quiz.views.gradable_for``). This pins the same rule one layer down, where the
money is actually spent — because a worksheet or a piece of homework is assigned
by a teacher, not chosen by the student, so it can put an AI-graded question in
front of somebody the quiz would have hidden it from.

The answer is left for the teacher, exactly as a quota-exhausted one is. It is
never recorded as wrong: a billing tier is not a reason to mark a child down.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.entitlements import grant_student_module
from billing.models import Package, StudentModule, Subscription
from classroom.models import Level, Subject, Topic
from maths.models import Question
from worksheets.grading_service import grade_extended_answer

User = get_user_model()


def no_claude():
    """A call that reaches Claude fails this test loudly rather than costing money."""
    return patch('worksheets.grading_service._call_claude_grade',
                 side_effect=AssertionError(
                     'the grader was called for a student who is not entitled'))


class GradeExtendedAnswerRespectsTheTierTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        subject = Subject.objects.create(name='Mathematics', slug='maths-guard')
        level = Level.objects.create(level_number=11, display_name='Year 11')
        topic = Topic.objects.create(subject=subject, name='Proof',
                                     slug='proof-guard')
        cls.question = Question.objects.create(
            level=level, topic=topic,
            question_text='Prove that the sum of two odd numbers is even.',
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI,
            grading_rubric='Full marks: 2a+1 + 2b+1 = 2(a+b+1).')

    def setUp(self):
        self.user = User.objects.create_user(
            username='guarded', password='pass1234', email='guarded@test.com')
        package, _ = Package.objects.get_or_create(
            name='Free', defaults={'price': 0, 'class_limit': 0})
        Subscription.objects.create(user=self.user, package=package,
                                    status=Subscription.STATUS_ACTIVE)

    def test_a_student_basic_student_is_never_sent_to_the_grader(self):
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        with no_claude():
            result = grade_extended_answer(
                self.question, '2a+1 + 2b+1 = 2(a+b+1), which is even.',
                student=self.user)
        self.assertTrue(result['not_entitled'])
        self.assertEqual(result['input_tokens'], 0)
        self.assertEqual(result['output_tokens'], 0)

    def test_the_answer_is_left_for_the_teacher_not_marked_wrong(self):
        """``is_correct: False`` here means "no verdict", and every caller
        reads ``not_entitled`` alongside it so it never becomes a nought."""
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        with no_claude():
            result = grade_extended_answer(
                self.question, 'A full and correct proof.', student=self.user)
        self.assertEqual(result['score_fraction'], 0.0)
        self.assertIn('teacher', result['feedback'].lower())

    def test_an_entitled_student_is_graded_as_before(self):
        with patch('worksheets.grading_service._call_claude_grade',
                   return_value={'is_correct': True, 'score_fraction': 1.0,
                                 'feedback': 'Correct.', 'cache_hit': False,
                                 'input_tokens': 10, 'output_tokens': 5}):
            result = grade_extended_answer(
                self.question, 'A full and correct proof.', student=self.user)
        self.assertTrue(result['is_correct'])
        self.assertNotIn('not_entitled', result)

    def test_omitting_the_student_grades_as_before(self):
        """Every existing caller that has no student to name is unaffected."""
        with patch('worksheets.grading_service._call_claude_grade',
                   return_value={'is_correct': True, 'score_fraction': 1.0,
                                 'feedback': 'Correct.', 'cache_hit': False,
                                 'input_tokens': 10, 'output_tokens': 5}):
            result = grade_extended_answer(self.question, 'Some proof.')
        self.assertTrue(result['is_correct'])

    def test_a_cached_verdict_is_still_returned(self):
        """A cache hit costs nothing and is a mark this question has already
        given, so withholding it would save no money and only lose a mark."""
        cached = {
            'is_correct': True, 'score_fraction': 1.0,
            'feedback': 'Correct.', 'what_was_correct': '', 'what_to_add': '',
        }
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        with no_claude(), \
             patch('worksheets.grading_service._lookup_cache',
                   return_value=cached):
            result = grade_extended_answer(
                self.question, 'A full and correct proof.', student=self.user)
        self.assertTrue(result['is_correct'])
        self.assertTrue(result['cache_hit'])
