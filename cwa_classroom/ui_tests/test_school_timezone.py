"""Tests for per-school timezone setting."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login

pytestmark = pytest.mark.sidebar


class TestSchoolTimezoneSettings:
    """Timezone field appears on school settings and saves correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, admin_user, school):
        self.url = live_server.url
        self.page = page
        self.school = school
        do_login(page, self.url, admin_user)

    def test_timezone_dropdown_visible(self):
        """Timezone select exists on school settings page."""
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/")
        self.page.wait_for_load_state("networkidle")
        tz_select = self.page.locator("select[name='timezone']")
        expect(tz_select).to_be_visible()

    def test_timezone_has_options(self):
        """Timezone dropdown contains expected timezone options."""
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/")
        self.page.wait_for_load_state("networkidle")
        tz_select = self.page.locator("select[name='timezone']")
        expect(tz_select.locator("option[value='America/New_York']")).to_have_count(1)
        expect(tz_select.locator("option[value='Pacific/Auckland']")).to_have_count(1)
        expect(tz_select.locator("option[value='UTC']")).to_have_count(1)

    def test_timezone_saves(self):
        """Saving a timezone persists to the database."""
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/")
        self.page.wait_for_load_state("networkidle")
        self.page.locator("select[name='timezone']").select_option("America/New_York")
        self.page.locator("button:has-text('Save')").first.click()
        self.page.wait_for_load_state("networkidle")
        # Reload and verify it stuck
        self.page.goto(f"{self.url}/admin-dashboard/schools/{self.school.id}/settings/")
        self.page.wait_for_load_state("networkidle")
        tz_select = self.page.locator("select[name='timezone']")
        expect(tz_select.locator("option[value='America/New_York']")).to_have_attribute("selected", "")

    def test_model_get_local_date(self):
        """School.get_local_date() returns a date object."""
        from classroom.models import School
        school = School.objects.get(id=self.school.id)
        school.timezone = "UTC"
        school.save(update_fields=["timezone"])
        local_date = school.get_local_date()
        assert local_date is not None
        assert hasattr(local_date, "year")
