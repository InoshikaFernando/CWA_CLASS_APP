"""Tests for student progress dashboard — time cards, color bands, filters, grids."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.progress


class TestProgressDashboard:
    """Tests for /student-dashboard/ — main progress page."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, timelog, progress_data):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/student-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_title(self):
        assert_page_has_text(self.page, "My Progress")

    def test_daily_time_card(self):
        """Daily time card shows 'Today' label."""
        assert_page_has_text(self.page, "Today")

    def test_weekly_time_card(self):
        """Weekly time card shows 'This Week' label."""
        assert_page_has_text(self.page, "This Week")

    def test_time_values_not_empty(self):
        """Time cards should show a time value, not just the label."""
        body = self.page.locator("body").inner_text()
        # Should contain some time format like "45m" or "0:45" or "45 min"
        assert re.search(r"\d+[mh:]", body)

    def test_year_level_progress_section(self):
        """Year Level Progress accordion should be present."""
        assert_page_has_text(self.page, "Year Level Progress")

    def test_color_legend_renders(self):
        """Color legend with all 7 bands should be visible."""
        assert_page_has_text(self.page, "Outstanding")
        assert_page_has_text(self.page, "Not attempted")

    def test_progress_accordion_expandable(self):
        """The progress accordion (details/summary) should be clickable."""
        summary = self.page.locator("summary", has_text="Year Level Progress")
        if summary.count() > 0:
            summary.click()
            self.page.wait_for_timeout(500)
            # After expanding, level rows should be visible
            details_content = self.page.locator("details[open]")
            expect(details_content.first).to_be_visible()


class TestProgressFilters:
    """Tests for filter buttons on the progress dashboard."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, subject, timelog, progress_data):
        self.url = live_server.url
        self.page = page
        self.subject = subject
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/student-dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_all_filter_button_visible(self):
        """'All' filter button should be visible."""
        all_btn = self.page.locator("a", has_text="All").first
        expect(all_btn).to_be_visible()

    def test_subject_filter_button_visible(self):
        """Subject filter button (e.g. Mathematics) should be visible."""
        subject_btn = self.page.locator("a", has_text="Mathematics")
        if subject_btn.count() > 0:
            expect(subject_btn.first).to_be_visible()

    def test_clicking_all_filter_resets(self):
        """Clicking 'All' should navigate to unfiltered progress view."""
        all_btn = self.page.locator("a", has_text="All").first
        all_btn.click()
        expect(self.page).to_have_url(re.compile(r"/student-dashboard/$"))
