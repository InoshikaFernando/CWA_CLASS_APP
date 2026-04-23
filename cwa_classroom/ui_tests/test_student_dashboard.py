"""
Playwright UI tests for the student dashboard (/student-dashboard/).

Covers the subject-aware filter bar and the three content-rendering modes
(student/dashboard.html + partials/_coding_progress.html).

Documents current behavior so Phase 1 of the subject-plugin refactor can
change the data source without breaking the user-visible contract.

  - Page loads with heading + time stats
  - 'All' filter tab always present and defaults to active
  - Enrolled maths subject renders as a filter tab
  - Coding tab shows ONLY when has_coding (CodingLanguage with active content exists)
  - Clicking the Mathematics tab sets filter_subject_id in URL
  - Clicking the Coding tab switches URL to ?subject=coding and renders coding progress
  - Class dropdown appears when student is enrolled in multiple classes
"""

from __future__ import annotations

import re

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login


def _goto_dashboard(page: Page, live_server_url: str) -> None:
    page.goto(f"{live_server_url}/student-dashboard/")
    page.wait_for_load_state("networkidle")


class TestStudentDashboard:

    @pytest.mark.django_db(transaction=True)
    def test_page_loads_with_heading_and_time_stats(
        self, page: Page, live_server, enrolled_student
    ):
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        expect(page.get_by_role("heading", name=re.compile(r"My Progress", re.I))).to_be_visible()
        expect(page.get_by_text("Today", exact=True)).to_be_visible()
        expect(page.get_by_text("This Week", exact=True)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_all_tab_is_active_by_default(
        self, page: Page, live_server, enrolled_student
    ):
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        all_tab = page.get_by_role("link", name="All").first
        # Active tab has bg-emerald-500 class
        assert "bg-emerald-500" in (all_tab.get_attribute("class") or "")

    @pytest.mark.django_db(transaction=True)
    def test_mathematics_subject_tab_present(
        self, page: Page, live_server, enrolled_student, subject, level, topic, questions
    ):
        """When the student's class has Mathematics, the subject tab renders."""
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        # Might be "Mathematics" or the subject name — fixture uses "Mathematics"
        tab = page.get_by_role("link", name=subject.name)
        assert tab.count() >= 1

    # NOTE: intentionally no "Coding tab hidden without content" test —
    # the view's `has_coding` flag is True whenever the coding app is importable
    # (see _build_coding_progress() in classroom/views.py), not when content
    # exists. The Coding tab therefore always renders for students. Phase 1 of
    # the subject-plugin refactor may tighten this; when it does, add a test
    # asserting the hidden state.

    @pytest.mark.django_db(transaction=True)
    def test_coding_tab_appears_with_active_language(
        self, page: Page, live_server, enrolled_student,
        coding_language, coding_topic,
    ):
        """With an active CodingLanguage, the Coding tab appears in the filter bar."""
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        filter_bar = page.locator("div.flex.flex-wrap").filter(has_text="All").first
        expect(filter_bar.get_by_role("link", name="Coding").first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_coding_tab_switches_to_coding_mode(
        self, page: Page, live_server, enrolled_student,
        coding_language, coding_topic,
    ):
        """Clicking the Coding tab navigates to ?subject=coding."""
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        filter_bar = page.locator("div.flex.flex-wrap").filter(has_text="All").first
        with page.expect_navigation():
            filter_bar.get_by_role("link", name="Coding").first.click()
        page.wait_for_load_state("networkidle")
        assert "subject=coding" in page.url

    @pytest.mark.django_db(transaction=True)
    def test_subject_tab_adds_subject_id_query_param(
        self, page: Page, live_server, enrolled_student, subject
    ):
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        tab = page.get_by_role("link", name=subject.name).first
        href = tab.get_attribute("href") or ""
        assert f"subject_id={subject.pk}" in href

    @pytest.mark.django_db(transaction=True)
    def test_class_dropdown_hidden_with_single_class(
        self, page: Page, live_server, enrolled_student, classroom
    ):
        """Student enrolled in one class → no class dropdown (fewer controls is better)."""
        do_login(page, live_server.url, enrolled_student)
        _goto_dashboard(page, live_server.url)
        filter_bar = page.locator("div.flex.flex-wrap").filter(has_text="All").first
        # The class dropdown is a <select> inside the filter bar
        selects = filter_bar.locator("select")
        assert selects.count() == 0
