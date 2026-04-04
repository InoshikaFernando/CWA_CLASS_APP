"""
UI tests for the class join-request / enrollment-approval workflow.

Covers:
- Student submits a join request via the "Join Class" page
- Teacher sees the pending request on the Enrollment Requests page
- Teacher approves a request → student's notification has a "View Class" button
- Teacher rejects a request → student's notification has a "View Details" button
- Email button URLs resolve to the correct pages
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.enrollment


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_pending_enrollment(classroom, student_user, school):
    """Create a pending Enrollment (student has not yet been accepted)."""
    from classroom.models import Enrollment, SchoolStudent

    SchoolStudent.objects.get_or_create(school=school, student=student_user)
    enrollment, _ = Enrollment.objects.get_or_create(
        classroom=classroom,
        student=student_user,
        defaults={"status": "pending"},
    )
    return enrollment


# ===========================================================================
# Student: join-class page
# ===========================================================================

class TestStudentJoinClassPage:
    """Basic rendering and validation on /student/join/."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, student_user, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, student_user)
        page.goto(f"{self.url}/student/join/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        assert_page_has_text(self.page, "Join")

    def test_code_input_is_present(self):
        inp = self.page.locator("input[name='code'], input[placeholder*='ode']").first
        expect(inp).to_be_visible()

    def test_invalid_code_shows_error(self):
        self.page.locator("input[name='code']").fill("BADCODE9")
        self.page.get_by_role("button", name="Request to Join").click()
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body").inner_text()
        # View returns "No active class found with that code."
        assert "class" in body.lower() and (
            "no" in body.lower()
            or "not found" in body.lower()
            or "invalid" in body.lower()
        )

    def test_valid_code_creates_pending_enrollment(self, classroom):
        from classroom.models import Enrollment

        self.page.locator("input[name='code']").fill(classroom.code)
        self.page.get_by_role("button", name="Request to Join").click()
        self.page.wait_for_load_state("domcontentloaded")
        assert Enrollment.objects.filter(
            classroom=classroom, status="pending"
        ).exists()


# ===========================================================================
# Teacher: enrollment requests page
# ===========================================================================

class TestTeacherEnrollmentRequestsPage:
    """Teacher sees pending requests at /teacher/enrollment-requests/."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, student_user):
        self.url = live_server.url
        self.page = page
        self.enrollment = _make_pending_enrollment(classroom, student_user, school)
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/enrollment-requests/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        body = self.page.locator("body").inner_text()
        assert "enrollment" in body.lower() or "request" in body.lower()

    def test_pending_student_listed(self, student_user):
        assert_page_has_text(self.page, student_user.username)

    def test_approve_button_visible(self):
        btn = self.page.locator(
            "button:has-text('Approve'), a:has-text('Approve'), form button[value='approve']"
        ).first
        expect(btn).to_be_visible()

    def test_reject_button_visible(self):
        btn = self.page.locator(
            "button:has-text('Reject'), a:has-text('Reject'), form button[value='reject']"
        ).first
        expect(btn).to_be_visible()


# ===========================================================================
# Teacher: approve an enrollment request
# ===========================================================================

class TestTeacherApprovesEnrollment:
    """Approving a request marks it approved and creates a student notification."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, student_user):
        self.url = live_server.url
        self.page = page
        self.enrollment = _make_pending_enrollment(classroom, student_user, school)
        self.classroom = classroom
        self.student_user = student_user
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/enrollment-requests/")
        page.wait_for_load_state("domcontentloaded")

    def test_approve_changes_status(self):
        from classroom.models import Enrollment

        self.page.locator(
            f"form[action*='/enrollment/{self.enrollment.id}/approve/'] button, "
            f"button:has-text('Approve')"
        ).first.click()
        self.page.wait_for_load_state("domcontentloaded")
        self.enrollment.refresh_from_db()
        assert self.enrollment.status == "approved"

    def test_approve_creates_notification_with_class_link(self):
        from classroom.models import Enrollment, Notification
        from django.urls import reverse

        self.page.locator(
            f"form[action*='/enrollment/{self.enrollment.id}/approve/'] button, "
            f"button:has-text('Approve')"
        ).first.click()
        self.page.wait_for_load_state("domcontentloaded")

        notif = Notification.objects.filter(
            user=self.student_user,
            notification_type="enrollment_approved",
        ).last()
        assert notif is not None, "No approval notification created"
        expected = reverse("student_class_detail", kwargs={"class_id": self.classroom.id})
        assert notif.link == expected, (
            f"Approval notification link is '{notif.link}', expected '{expected}'"
        )

    def test_approve_redirects_back_to_requests_page(self):
        self.page.locator(
            f"form[action*='/enrollment/{self.enrollment.id}/approve/'] button, "
            f"button:has-text('Approve')"
        ).first.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/teacher/enrollment-requests/"))


# ===========================================================================
# Teacher: reject an enrollment request
# ===========================================================================

class TestTeacherRejectsEnrollment:
    """Rejecting a request marks it rejected and creates a student notification."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, student_user):
        self.url = live_server.url
        self.page = page
        self.enrollment = _make_pending_enrollment(classroom, student_user, school)
        self.student_user = student_user
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/enrollment-requests/")
        page.wait_for_load_state("domcontentloaded")

    def _click_reject(self):
        """Click Reject and accept the confirm() dialog."""
        self.page.once("dialog", lambda d: d.accept())
        self.page.locator(
            f"form[action*='/enrollment/{self.enrollment.id}/reject/'] button"
        ).click()
        self.page.wait_for_load_state("domcontentloaded")

    def test_reject_changes_status(self):
        from classroom.models import Enrollment

        self._click_reject()
        self.enrollment.refresh_from_db()
        assert self.enrollment.status == "rejected"

    def test_reject_creates_notification_with_join_class_link(self):
        from classroom.models import Notification
        from django.urls import reverse

        self._click_reject()

        notif = Notification.objects.filter(
            user=self.student_user,
            notification_type="enrollment_rejected",
        ).last()
        assert notif is not None, "No rejection notification created"
        expected = reverse("student_join_class")
        assert notif.link == expected, (
            f"Rejection notification link is '{notif.link}', expected '{expected}'"
        )

    def test_reject_redirects_back_to_requests_page(self):
        self._click_reject()
        expect(self.page).to_have_url(re.compile(r"/teacher/enrollment-requests/"))


# ===========================================================================
# Email button URL correctness (verified via Notification.link values)
# ===========================================================================

class TestEnrollmentEmailButtonUrls:
    """
    Verifies the exact URL stored in each notification's link field so that
    the email 'Review Requests' / 'View Class' / 'View Details' buttons
    resolve to the correct pages.
    """

    @pytest.fixture(autouse=True)
    def _setup(self, db, school, classroom, teacher_user, student_user):
        from classroom.models import SchoolStudent

        self.school = school
        self.classroom = classroom
        self.teacher_user = teacher_user
        self.student_user = student_user
        SchoolStudent.objects.get_or_create(school=school, student=student_user)

    def test_join_request_notification_link_is_enrollment_requests_url(self):
        """Teacher email 'Review Requests' button → /teacher/enrollment-requests/."""
        from django.test import Client
        from django.urls import reverse
        from classroom.models import Notification

        c = Client()
        c.force_login(self.student_user)
        c.post(reverse("student_join_class"), {"code": self.classroom.code})

        notif = Notification.objects.filter(
            user=self.teacher_user,
            notification_type="enrollment_request",
        ).last()
        assert notif is not None
        assert notif.link == reverse("enrollment_requests")

    def test_approval_notification_link_is_class_detail_url(self):
        """Student email 'View Class' button → /student/class/<id>/."""
        from django.test import Client
        from django.urls import reverse
        from classroom.models import Enrollment, Notification

        enrollment = Enrollment.objects.create(
            classroom=self.classroom,
            student=self.student_user,
            status="pending",
        )
        c = Client()
        c.force_login(self.teacher_user)
        c.post(reverse("enrollment_approve", args=[enrollment.id]))

        notif = Notification.objects.filter(
            user=self.student_user,
            notification_type="enrollment_approved",
        ).last()
        assert notif is not None
        expected = reverse("student_class_detail", kwargs={"class_id": self.classroom.id})
        assert notif.link == expected

    def test_rejection_notification_link_is_join_class_url(self):
        """Student email 'View Details' button → /student/join/."""
        from django.test import Client
        from django.urls import reverse
        from classroom.models import Enrollment, Notification

        enrollment = Enrollment.objects.create(
            classroom=self.classroom,
            student=self.student_user,
            status="pending",
        )
        c = Client()
        c.force_login(self.teacher_user)
        c.post(
            reverse("enrollment_reject", args=[enrollment.id]),
            {"rejection_reason": "No space"},
        )

        notif = Notification.objects.filter(
            user=self.student_user,
            notification_type="enrollment_rejected",
        ).last()
        assert notif is not None
        assert notif.link == reverse("student_join_class")
