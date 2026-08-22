"""Who may be shown, and marked on, an AI-graded question.

Individual students get AI grading free — they pay for the app themselves, or
are on a discount the owner granted personally. School students get it when
their school buys the module, or when the owner has flagged the school as free.

``School.free_ai_grading`` is the escape hatch. The grading service has always
read it, but the field was never added to the model, so ``getattr(school,
'free_ai_grading', False)`` was permanently False and the hatch silently did
nothing. These pin it working.
"""
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from classroom.models import School
from worksheets.grading_service import (
    check_ai_grading_quota, student_can_be_ai_graded,
)

User = get_user_model()


class StudentCanBeAIGradedTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='entitlement-student', password='pass1234',
            email='entitlement@test.com')
        cls.school = School.objects.create(name='Test School', slug='test-ai')
        cls.free_school = School.objects.create(
            name='Free School', slug='free-ai', free_ai_grading=True)

    def _with_schools(self, schools, tier=None):
        return (patch('billing.entitlements.get_all_schools_for_user',
                      return_value=schools),
                patch('worksheets.grading_service.get_ai_grading_tier',
                      return_value=tier))

    def test_an_individual_student_is_always_included(self):
        schools, tier = self._with_schools([])
        with schools, tier:
            self.assertTrue(student_can_be_ai_graded(self.student))

    def test_a_school_student_needs_the_module(self):
        schools, tier = self._with_schools([self.school], tier=None)
        with schools, tier:
            self.assertFalse(student_can_be_ai_graded(self.student))

        schools, tier = self._with_schools(
            [self.school], tier='ai_grading_starter')
        with schools, tier:
            self.assertTrue(student_can_be_ai_graded(self.student))

    def test_the_free_flag_stands_in_for_the_module(self):
        """A school the owner granted free access to, with nothing bought."""
        schools, tier = self._with_schools([self.free_school], tier=None)
        with schools, tier:
            self.assertTrue(student_can_be_ai_graded(self.student))

    def test_any_one_of_a_students_schools_is_enough(self):
        schools, tier = self._with_schools([self.school, self.free_school],
                                           tier=None)
        with schools, tier:
            self.assertTrue(student_can_be_ai_graded(self.student))


class FreeAIGradingBypassesQuotaTests(TestCase):
    def test_a_free_school_is_never_capped(self):
        school = School.objects.create(
            name='Owner Free', slug='owner-free', free_ai_grading=True)
        allowed, used, limit = check_ai_grading_quota(school)
        self.assertTrue(allowed)
        self.assertIsNone(limit)   # None = uncapped

    def test_an_ordinary_school_without_the_module_is_not_allowed(self):
        school = School.objects.create(name='Paying', slug='paying-ai')
        allowed, _used, _limit = check_ai_grading_quota(school)
        self.assertFalse(allowed)

    def test_the_flag_defaults_to_off(self):
        self.assertFalse(School.objects.create(
            name='Default', slug='default-ai').free_ai_grading)
