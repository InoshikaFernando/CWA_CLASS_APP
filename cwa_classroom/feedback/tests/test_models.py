"""Unit tests for the Feedback model (CPP-322).

Run with:
    pytest feedback/tests/test_models.py -v
"""
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role
from classroom.models import School
from feedback.forms import FeedbackForm
from feedback.models import Feedback
from feedback.owner import get_feedback_owner


class FeedbackModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'fb_owner', 'owner@example.com', 'pass1!',
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.student = CustomUser.objects.create_user(
            'fb_student', 'student@example.com', 'pass1!',
        )
        cls.student.roles.add(cls.student_role)
        cls.school = School.objects.create(
            name='FB Test School', slug='fb-test-school', admin=cls.owner,
        )

    def test_feedback_create_assigns_owner(self):
        """A new Feedback assigned to the resolved product owner."""
        owner = get_feedback_owner()
        self.assertEqual(owner, self.owner)

        feedback = Feedback.objects.create(
            submitted_by=self.student,
            school=self.school,
            role=Role.STUDENT,
            category=Feedback.CATEGORY_BUG,
            description='Something broke.',
            assignee=owner,
        )
        self.assertEqual(feedback.assignee, self.owner)
        self.assertEqual(feedback.status, Feedback.STATUS_NEW)
        self.assertIsNone(feedback.priority)
        self.assertIsNone(feedback.removed_at)

    def test_feedback_requires_category_and_description(self):
        """The capture form rejects blank category and description."""
        form = FeedbackForm(data={'category': '', 'title': 'x', 'description': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('category', form.errors)
        self.assertIn('description', form.errors)

        # Valid when both supplied.
        ok = FeedbackForm(data={
            'category': Feedback.CATEGORY_FEATURE,
            'description': 'Please add dark mode.',
        })
        self.assertTrue(ok.is_valid(), ok.errors)

    def test_soft_delete_hides_from_active_queryset(self):
        feedback = Feedback.objects.create(
            submitted_by=self.student,
            category=Feedback.CATEGORY_IMPROVEMENT,
            description='Could be faster.',
        )
        self.assertIn(feedback, Feedback.objects.active())
        feedback.soft_delete()
        self.assertIsNotNone(feedback.removed_at)
        self.assertNotIn(feedback, Feedback.objects.active())
        self.assertIn(feedback, Feedback.objects.removed())

    @override_settings(FEEDBACK_OWNER_EMAIL='owner@example.com')
    def test_owner_resolved_by_settings_email(self):
        self.assertEqual(get_feedback_owner(), self.owner)
