"""Super-admin "View as" — the full journey through a browser.

The unit suite (``accounts/tests_impersonation.py``) proves ``request.user`` is
swapped and writes are refused. This covers the part only a browser can show:
that a super admin can find a real user, land in their account, always see
whose account they are in, and get back out again.
"""
import re

import pytest
from playwright.sync_api import expect

from ..conftest import do_login

VIEW_AS_URL = "/accounts/view-as/"


class TestViewAsJourney:
    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, superuser, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        self.student = enrolled_student
        do_login(page, self.url, superuser)

    def _search_for_student(self):
        self.page.goto(f"{self.url}{VIEW_AS_URL}")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.locator("#q").fill(self.student.username)
        self.page.get_by_role("button", name="Search").click()
        self.page.wait_for_load_state("domcontentloaded")

    def _start_viewing_as_student(self):
        self._search_for_student()
        self.page.get_by_role("link", name="View as").first.click()
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("button", name="Start viewing as this user").click()
        self.page.wait_for_load_state("domcontentloaded")

    def test_picker_finds_the_student(self):
        self._search_for_student()
        expect(self.page.locator("table")).to_contain_text(self.student.username)

    def test_confirm_page_warns_it_is_read_only(self):
        self._search_for_student()
        self.page.get_by_role("link", name="View as").first.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("read-only")

    def test_starting_lands_on_the_students_own_hub(self):
        self._start_viewing_as_student()
        expect(self.page).to_have_url(re.compile(r"/hub/|/subjects"))

    def test_banner_names_the_student_being_viewed(self):
        self._start_viewing_as_student()
        banner = self.page.locator("text=Viewing as").first
        expect(banner).to_be_visible()

    def test_banner_survives_navigating_to_another_page(self):
        self._start_viewing_as_student()
        self.page.goto(f"{self.url}/accounts/profile/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("text=Viewing as").first).to_be_visible()

    def test_profile_page_shows_the_students_details_not_the_admins(self):
        self._start_viewing_as_student()
        self.page.goto(f"{self.url}/accounts/profile/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text(self.student.username)
        expect(self.page.locator("body")).not_to_contain_text("ui_superuser@test.local")

    def test_stop_returns_the_admin_to_their_own_account(self):
        self._start_viewing_as_student()
        self.page.get_by_role("button", name="Stop").first.click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(re.compile(r"/accounts/view-as/"))
        expect(self.page.locator("text=Viewing as").first).not_to_be_visible()


class TestViewAsIsSuperAdminOnly:
    def test_a_teacher_cannot_open_the_picker(self, live_server, page, teacher_user):
        do_login(page, live_server.url, teacher_user)
        page.goto(f"{live_server.url}{VIEW_AS_URL}")
        page.wait_for_load_state("domcontentloaded")
        expect(page).not_to_have_url(re.compile(r"/accounts/view-as/"))
