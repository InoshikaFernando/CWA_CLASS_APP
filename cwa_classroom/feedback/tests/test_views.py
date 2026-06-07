"""Unit tests for the feedback capture view (CPP-322).

Run with:
    pytest feedback/tests/test_views.py -v
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolStudent
from feedback.models import Feedback


class SubmitFeedbackViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = CustomUser.objects.create_superuser(
            'sf_owner', 'sf_owner@example.com', 'pass1!',
        )
        cls.student_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        cls.student = CustomUser.objects.create_user(
            'sf_student', 'sf_student@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        cls.student.roles.add(cls.student_role)
        cls.school = School.objects.create(
            name='SF School', slug='sf-school', admin=cls.owner,
        )
        SchoolStudent.objects.get_or_create(school=cls.school, student=cls.student)

    def setUp(self):
        self.url = reverse('feedback:submit')

    def test_submit_feedback_view_creates_record(self):
        self.client.force_login(self.student)
        resp = self.client.post(
            self.url,
            {
                'category': Feedback.CATEGORY_BUG,
                'title': 'Login button broken',
                'description': 'Clicking login does nothing.',
                'page_url': 'https://app.example.com/dashboard/',
            },
            HTTP_REFERER='https://app.example.com/dashboard/',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Thanks for your feedback')

        feedback = Feedback.objects.get()
        self.assertEqual(feedback.submitted_by, self.student)
        self.assertEqual(feedback.category, Feedback.CATEGORY_BUG)
        self.assertEqual(feedback.role, Role.STUDENT)
        self.assertEqual(feedback.school, self.school)
        self.assertEqual(feedback.status, Feedback.STATUS_NEW)
        self.assertEqual(feedback.assignee, self.owner)
        self.assertEqual(feedback.page_url, 'https://app.example.com/dashboard/')

    def test_submit_feedback_rejects_blank(self):
        self.client.force_login(self.student)
        resp = self.client.post(self.url, {'category': '', 'description': ''})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(Feedback.objects.count(), 0)
        # Inline errors rendered in the re-displayed form.
        self.assertContains(resp, 'This field is required', status_code=400)

    def test_submit_requires_login(self):
        resp = self.client.post(self.url, {
            'category': Feedback.CATEGORY_BUG, 'description': 'x',
        })
        self.assertIn(resp.status_code, (302, 403))
        self.assertEqual(Feedback.objects.count(), 0)

    def test_get_returns_form_partial(self):
        self.client.force_login(self.student)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'id="feedback-form"')
