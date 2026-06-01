"""
Playwright UI tests for CPP-305: Teacher-level password reset from class detail page.

Covers:
1. Reset Password button visible in class detail for teacher with enrolled student
2. Reset Password modal loads when button clicked (shows student name)
3. Cancel button closes modal without making changes
4. Submit (random mode) shows success/warning toast and redirects back to class detail
"""
import pytest
from django.urls import reverse
from playwright.sync_api import Page, expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD


pytestmark = pytest.mark.cpp305


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _class_detail_url(live_server_url, classroom_id):
    return f"{live_server_url}{reverse('class_detail', args=[classroom_id])}"


# ---------------------------------------------------------------------------
# Test: Reset Password button visible for teacher
# ---------------------------------------------------------------------------

class TestResetPasswordButtonVisible:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, enrolled_student, db):
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_reset_password_button_visible_for_teacher(self):
        self.page.goto(_class_detail_url(self.url, self.classroom.id))
        self.page.wait_for_load_state("networkidle")
        expect(
            self.page.locator("button:has-text('Reset Password')").first
        ).to_be_visible()


# ---------------------------------------------------------------------------
# Test: Modal loads with student info
# ---------------------------------------------------------------------------

class TestResetPasswordModalLoads:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, enrolled_student, db):
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_modal_loads_with_student_name(self):
        self.page.goto(_class_detail_url(self.url, self.classroom.id))
        self.page.wait_for_load_state("networkidle")

        self.page.locator("button:has-text('Reset Password')").first.click()
        # Modal should appear with heading and student info
        expect(
            self.page.locator("h2:has-text('Reset Password')").first
        ).to_be_visible(timeout=5000)
        expect(
            self.page.locator(f"text={self.student.username}").first
        ).to_be_visible(timeout=3000)


# ---------------------------------------------------------------------------
# Test: Cancel closes modal
# ---------------------------------------------------------------------------

class TestResetPasswordModalCancel:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, enrolled_student, db):
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_cancel_closes_modal(self):
        self.page.goto(_class_detail_url(self.url, self.classroom.id))
        self.page.wait_for_load_state("networkidle")

        self.page.locator("button:has-text('Reset Password')").first.click()
        expect(
            self.page.locator("h2:has-text('Reset Password')").first
        ).to_be_visible(timeout=5000)

        # Click Cancel button inside the modal
        self.page.locator("#class-edit-modal-content button:has-text('Cancel')").first.click()

        # Modal heading should no longer be visible
        expect(
            self.page.locator("h2:has-text('Reset Password')").first
        ).not_to_be_visible(timeout=5000)


# ---------------------------------------------------------------------------
# Test: Submit random mode → redirects back to class detail with toast
# ---------------------------------------------------------------------------

class TestResetPasswordSubmit:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, classroom, enrolled_student, db):
        self.url = live_server.url
        self.page = page
        self.classroom = classroom
        self.student = enrolled_student
        do_login(page, self.url, teacher_user)

    @pytest.mark.django_db(transaction=True)
    def test_submit_random_redirects_to_class_detail_with_message(self):
        class_url = _class_detail_url(self.url, self.classroom.id)
        self.page.goto(class_url)
        self.page.wait_for_load_state("networkidle")

        self.page.locator("button:has-text('Reset Password')").first.click()
        expect(
            self.page.locator("h2:has-text('Reset Password')").first
        ).to_be_visible(timeout=5000)

        # Submit form (default mode is random)
        self.page.locator("#class-edit-modal-content button[type='submit']").click()

        # Should redirect back to class detail page
        self.page.wait_for_url(
            lambda url: f"/class/{self.classroom.id}/" in url,
            timeout=10_000,
        )
        self.page.wait_for_load_state("networkidle")

        # A toast message should be present (success or warning if email failed)
        expect(self.page.locator(".toast-item").first).to_be_visible(timeout=5000)
