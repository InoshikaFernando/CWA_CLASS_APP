"""What a Student Basic quiz looks like, and what it says about the missing half.

``test_ungradable_hidden.py`` pins WHO the quiz hides AI-graded questions from.
This pins the other end of the same promotion: a student the owner put on the
free Student Basic edition gets the self-marked questions and a note about the
ones they are not seeing — and a student who cannot buy their own way out of it
gets no such note, because pointing a child at a purchase only their school can
make is worse than saying nothing.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.entitlements import grant_student_module
from billing.models import Package, StudentModule, Subscription
from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question
from quiz.views import ai_upsell_for, gradable_for

User = get_user_model()


class StudentBasicSeesOnlySelfMarkedQuestionsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        subject = Subject.objects.create(name='Mathematics', slug='maths-basic')
        cls.level = Level.objects.create(level_number=9, display_name='Year 9')
        cls.topic = Topic.objects.create(
            subject=subject, name='Angles', slug='angles-basic')

        cls.self_marked = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='What is the size of angle x?',
            question_type=Question.SHORT_ANSWER)
        Answer.objects.create(question=cls.self_marked, answer_text='40',
                              is_correct=True)

        cls.written = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Explain why the angles on a straight line sum to 180°.',
            question_type=Question.EXTENDED_ANSWER,
            validation_type=Question.VALIDATION_AI,
            grading_rubric='Full marks: names the half-turn.')
        cls.flagged = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Justify your working.',
            question_type=Question.SHORT_ANSWER,
            validation_type=Question.VALIDATION_AI)

    def setUp(self):
        self.user = User.objects.create_user(
            username='basic-quizzer', password='pass1234',
            email='basic-quizzer@test.com')
        package, _ = Package.objects.get_or_create(
            name='Free', defaults={'price': 0, 'class_limit': 0})
        Subscription.objects.create(user=self.user, package=package,
                                    status=Subscription.STATUS_ACTIVE)

    def _served(self):
        return set(gradable_for(
            self.user, Question.objects.filter(topic=self.topic),
        ).values_list('id', flat=True))

    def test_before_the_promotion_they_get_everything(self):
        self.assertEqual(
            self._served(),
            {self.self_marked.id, self.written.id, self.flagged.id})

    def test_on_student_basic_the_ai_graded_half_is_gone(self):
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        self.assertEqual(self._served(), {self.self_marked.id})

    def test_the_add_on_brings_it_back(self):
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        grant_student_module(self.user, StudentModule.MODULE_AI_GRADING)
        self.assertEqual(
            self._served(),
            {self.self_marked.id, self.written.id, self.flagged.id})

    def test_the_two_halves_of_the_bank_agree_with_the_filter(self):
        """``ai_graded_q`` and ``is_ai_graded`` are the same rule, both ways."""
        by_query = set(Question.objects.filter(topic=self.topic)
                       .ai_graded().values_list('id', flat=True))
        by_row = {q.id for q in Question.objects.filter(topic=self.topic)
                  if q.is_ai_graded}
        self.assertEqual(by_query, by_row)
        self.assertEqual(by_query, {self.written.id, self.flagged.id})

    def test_not_ai_graded_is_the_exact_complement(self):
        topic_qs = Question.objects.filter(topic=self.topic)
        self.assertEqual(
            set(topic_qs.not_ai_graded().values_list('id', flat=True)),
            {self.self_marked.id})


class TheUpsellIsShownOnlyToPeopleWhoCanTakeItTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='upsell-target', password='pass1234',
            email='upsell-target@test.com')
        package, _ = Package.objects.get_or_create(
            name='Free', defaults={'price': 0, 'class_limit': 0})
        Subscription.objects.create(user=self.user, package=package,
                                    status=Subscription.STATUS_ACTIVE)

    def test_a_student_basic_student_short_of_questions_is_offered_it(self):
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        context = ai_upsell_for(self.user, 7)
        self.assertEqual(context['ai_upsell']['hidden_count'], 7)

    def test_nothing_is_shown_when_no_question_was_hidden(self):
        grant_student_module(self.user, StudentModule.MODULE_BASIC)
        self.assertEqual(ai_upsell_for(self.user, 0), {})

    def test_nothing_is_shown_to_a_student_who_already_has_ai_grading(self):
        self.assertEqual(ai_upsell_for(self.user, 5), {})

    def test_nothing_is_shown_to_a_school_student_who_cannot_buy_it(self):
        unpaid = School.objects.create(name='Unpaid Q', slug='unpaid-quiz')
        with patch('billing.entitlements.get_all_schools_for_user',
                   return_value=[unpaid]), \
             patch('worksheets.grading_service.get_ai_grading_tier',
                   return_value=None):
            self.assertEqual(ai_upsell_for(self.user, 12), {})
