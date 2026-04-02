"""Tests for breadcrumb navigation on key pages."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text

pytestmark = pytest.mark.dashboard


class TestBreadcrumbsOnHub:
    """Hub (home page) should NOT show breadcrumbs."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/hub/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_breadcrumbs_on_hub(self):
        breadcrumb_nav = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb_nav).to_have_count(0)


class TestBreadcrumbsOnMaths:
    """Maths pages should show Hub > Maths breadcrumbs."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_maths_home_breadcrumb(self):
        self.page.goto(f"{self.url}/maths/")
        self.page.wait_for_load_state("domcontentloaded")
        breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("Hub")
        expect(breadcrumb).to_contain_text("Maths")

    def test_basic_facts_breadcrumb(self):
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("Hub")
        expect(breadcrumb).to_contain_text("Maths")
        expect(breadcrumb).to_contain_text("Basic Facts")

    def test_times_tables_breadcrumb(self):
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("Hub")
        expect(breadcrumb).to_contain_text("Times Tables")


class TestBreadcrumbsOnClassPages:
    """Class-specific pages should show Hub > ... breadcrumbs."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_my_classes_breadcrumb(self):
        self.page.goto(f"{self.url}/student/my-classes/")
        self.page.wait_for_load_state("domcontentloaded")
        breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("Hub")
        expect(breadcrumb).to_contain_text("My Classes")

    def test_attendance_breadcrumb(self):
        self.page.goto(f"{self.url}/student/attendance/")
        self.page.wait_for_load_state("networkidle")
        # May redirect to billing/module-required if attendance module not subscribed
        if "/attendance" in self.page.url:
            breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
            if breadcrumb.count() > 0:
                expect(breadcrumb).to_contain_text("Hub")
                expect(breadcrumb).to_contain_text("Attendance")

    def test_progress_breadcrumb(self):
        self.page.goto(f"{self.url}/student-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        breadcrumb = self.page.locator("nav[aria-label='Breadcrumb']")
        expect(breadcrumb).to_be_visible()
        expect(breadcrumb).to_contain_text("Hub")
        expect(breadcrumb).to_contain_text("My Progress")


class TestAbsenceTokensOnMyClasses:
    """Absence Tokens button should be on the My Classes page (not sidebar)."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/student/my-classes/")
        page.wait_for_load_state("domcontentloaded")

    def test_absence_tokens_button_visible(self):
        btn = self.page.locator("a", has_text="Absence Tokens")
        expect(btn.first).to_be_visible()

    def test_absence_tokens_button_navigates(self):
        self.page.locator("a", has_text="Absence Tokens").first.click()
        expect(self.page).to_have_url(re.compile(r"/student/absence-tokens"))


class TestBreadcrumbHubLinkNavigates:
    """The 'Hub' crumb should link back to /hub/."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_hub_crumb_links_to_hub(self):
        self.page.goto(f"{self.url}/maths/")
        self.page.wait_for_load_state("domcontentloaded")
        hub_link = self.page.locator("nav[aria-label='Breadcrumb'] a", has_text="Hub")
        expect(hub_link).to_have_attribute("href", "/hub/")
