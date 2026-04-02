"""Tests for the student edit modal (CPP-93)."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.student_edit


class TestStudentEditButton:
    """Edit button appears on the students page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student, guardian):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.student = enrolled_student
        do_login(page, self.url, admin_user)
        page.goto(f"{self.url}/admin-dashboard/schools/{school.id}/students/")
        page.wait_for_load_state("networkidle")

    def test_edit_button_visible(self):
        """Each student row has an edit button."""
        edit_btn = self.page.locator("button[title='Edit student']").first
        expect(edit_btn).to_be_visible()


class TestStudentEditModalEndpoint:
    """Test the modal endpoint directly (no HTMX/CDN dependency)."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, enrolled_student, guardian):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.student = enrolled_student
        do_login(page, self.url, admin_user)

    def test_modal_endpoint_returns_form(self):
        """The edit-modal endpoint returns HTML with a form."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("h2", has_text="Edit Student")).to_be_visible()
        expect(self.page.locator("#edit_username")).to_have_value(self.student.username)

    def test_modal_endpoint_shows_guardian(self):
        """The edit-modal endpoint shows linked guardian."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Jane Guardian")).to_be_visible()

    def test_modal_has_save_button(self):
        """The edit-modal has a Save Changes button."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("button[type='submit']", has_text="Save Changes")).to_be_visible()

    def test_modal_has_cancel_button(self):
        """The edit-modal has a Cancel button."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("button", has_text="Cancel")).to_be_visible()

    def test_modal_shows_student_id(self):
        """The edit-modal shows the student ID code."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Student ID")).to_be_visible()

    def test_modal_shows_parents_section(self):
        """The edit-modal has a Parents / Guardians section."""
        self.page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/students/{self.student.id}/edit-modal/"
        )
        self.page.wait_for_load_state("networkidle")
        expect(self.page.locator("text=Parents / Guardians")).to_be_visible()
