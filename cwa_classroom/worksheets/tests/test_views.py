"""
Unit tests for WorksheetConfirmView — PR #255 regression guard.

Tests the confirm POST flow end-to-end using Django's test client so that
any reintroduction of the _TempSession AttributeError is caught in CI
without needing a Playwright browser.

Run with:
    pytest worksheets/tests/test_views.py -v
"""
import pytest
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import Level, School, SchoolTeacher, Subject, Topic
from worksheets.models import Worksheet, WorksheetUploadSession


class WorksheetConfirmViewTestBase(TestCase):
    """Shared fixtures: owner user + school + maths Level + upload session."""

    @classmethod
    def setUpTestData(cls):
        # User with INSTITUTE_OWNER role (passes RoleRequiredMixin)
        # and is school admin (get_school_for_user returns the school via admin FK)
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER,
            defaults={'display_name': 'Institute Owner'},
        )
        cls.owner = CustomUser.objects.create_user(
            'cv_owner', 'cv_owner@example.com', 'pass1!',
            profile_completed=True,
            must_change_password=False,
        )
        cls.owner.roles.add(owner_role)

        cls.school = School.objects.create(
            name='CV Test School', slug='cv-test-school', admin=cls.owner,
        )
        # _get_question_scope resolves school_id via SchoolTeacher.
        # Use get_or_create — a post_save signal may already have created this row.
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)

        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=6,
            defaults={'display_name': 'Year 6'},
        )[0]

    def setUp(self):
        self.client.force_login(self.owner)

    def _make_session(self, questions=None):
        """Create a WorksheetUploadSession with the given question list."""
        if questions is None:
            questions = [
                {
                    'include': True,
                    'question_text': 'What is 4 + 4?',
                    'question_type': 'short_answer',
                    'difficulty': 1,
                    'points': 1,
                    'year_level': 6,
                    'topic': 'cv-test-addition',
                    'subject': 'Mathematics',
                    'explanation': '',
                    'answers': [],
                }
            ]
        return WorksheetUploadSession.objects.create(
            user=self.owner,
            school=self.school,
            pdf_filename='cv_test.pdf',
            worksheet_name='CV Test Worksheet',
            extracted_data={'year_level': 6, 'subject': 'Mathematics', 'questions': questions},
            is_confirmed=False,
        )


# ---------------------------------------------------------------------------
# Happy path — confirm POST creates worksheet and marks session confirmed
# ---------------------------------------------------------------------------

class TestWorksheetConfirmPostHappyPath(WorksheetConfirmViewTestBase):

    def test_confirm_post_returns_redirect_not_500(self):
        """
        PR #255 regression: _TempSession lacked save() and is_confirmed,
        causing AttributeError on every confirm POST.  The fix adds a no-op
        save() so the response is a redirect, not a 500.
        """
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        # Any redirect is fine — what we must NOT see is a 500
        self.assertIn(
            response.status_code, [301, 302],
            f"Expected redirect after confirm POST, got {response.status_code}. "
            "_TempSession.save() fix may have been reverted.",
        )

    def test_confirm_post_marks_session_confirmed(self):
        """WorksheetUploadSession.is_confirmed should be True after POST."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        self.client.post(url)

        session.refresh_from_db()
        self.assertTrue(
            session.is_confirmed,
            "WorksheetUploadSession.is_confirmed should be True after confirm POST.",
        )

    def test_confirm_post_creates_worksheet(self):
        """A Worksheet row should be created for the school after confirm POST."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})
        worksheets_before = Worksheet.objects.filter(school=self.school).count()

        self.client.post(url)

        worksheets_after = Worksheet.objects.filter(school=self.school).count()
        self.assertEqual(
            worksheets_after, worksheets_before + 1,
            "Expected one new Worksheet row after confirm POST.",
        )

    def test_confirm_post_redirects_to_detail(self):
        """Successful confirm redirects to the worksheet detail page."""
        session = self._make_session()
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url, follow=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/worksheets/', response['Location'])


# ---------------------------------------------------------------------------
# Guard rails — bad / edge-case requests
# ---------------------------------------------------------------------------

class TestWorksheetConfirmPostEdgeCases(WorksheetConfirmViewTestBase):

    def test_confirm_already_confirmed_session_returns_404(self):
        """Confirming an already-confirmed session should 404, not error."""
        session = self._make_session()
        session.is_confirmed = True
        session.save(update_fields=['is_confirmed'])
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)

    def test_confirm_session_owned_by_other_user_returns_404(self):
        """A teacher should not be able to confirm another user's session."""
        other_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'},
        )
        other = CustomUser.objects.create_user(
            'cv_other', 'cv_other@example.com', 'pass1!',
            profile_completed=True, must_change_password=False,
        )
        other.roles.add(other_role)
        session = self._make_session()          # owned by self.owner
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        self.client.force_login(other)
        response = self.client.post(url)

        self.assertEqual(response.status_code, 404)

    def test_confirm_all_excluded_questions_redirects_to_preview(self):
        """If every question has include=False, redirect back to preview."""
        session = self._make_session(questions=[
            {
                'include': False,
                'question_text': 'Excluded question',
                'question_type': 'short_answer',
                'difficulty': 1, 'points': 1, 'year_level': 6,
                'topic': 'cv-test-addition', 'subject': 'Mathematics',
                'explanation': '', 'answers': [],
            }
        ])
        url = reverse('worksheets:confirm', kwargs={'session_id': session.pk})

        response = self.client.post(url)

        self.assertEqual(response.status_code, 302)
        self.assertIn('/preview/', response['Location'])
