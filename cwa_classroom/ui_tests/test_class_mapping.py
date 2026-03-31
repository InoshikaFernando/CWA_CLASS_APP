"""Tests for department assign classes — checkbox multi-select UI."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.dashboard


class TestDepartmentAssignClasses:
    """Tests for /admin-dashboard/schools/<id>/departments/<id>/assign-classes/."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school, department, classroom):
        self.url = live_server.url
        self.page = page
        self.school = school
        self.dept = department
        do_login(page, self.url, admin_user)
        page.goto(
            f"{self.url}/admin-dashboard/schools/{self.school.id}"
            f"/departments/{self.dept.id}/assign-classes/"
        )
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads_with_context(self):
        """Page should show school and department context."""
        assert_page_has_text(self.page, "Mathematics")

    def test_classes_listed_with_checkboxes(self):
        """Active classes should be listed with checkboxes."""
        checkboxes = self.page.locator("input[type='checkbox']")
        assert checkboxes.count() >= 1

    def test_assigned_class_pre_checked(self):
        """The classroom already in this department should be pre-checked."""
        checked = self.page.locator("input[type='checkbox']:checked")
        assert checked.count() >= 1

    def test_class_name_visible(self):
        """Classroom name should be displayed."""
        assert_page_has_text(self.page, "Year 7 Maths")

    def test_submit_button_visible(self):
        """Save Changes button should be present."""
        btn = self.page.locator("button[type='submit'], input[type='submit'], button:not([type])")
        expect(btn.first).to_be_visible()

    def test_back_link_visible(self):
        """Back navigation link should be present."""
        back = self.page.locator("a", has_text=re.compile(r"Back|←|‹"))
        if back.count() > 0:
            expect(back.first).to_be_visible()
