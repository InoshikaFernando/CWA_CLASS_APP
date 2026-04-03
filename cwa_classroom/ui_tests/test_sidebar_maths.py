"""
Tests for the maths subject sidebar — shown on /maths/ and quiz pages
when the subject has quiz questions. Falls back to sidebar_student.html
when no questions exist.
"""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import (
    assert_sidebar_has_link,
    assert_sidebar_missing_link,
    click_sidebar_link,
)

pytestmark = pytest.mark.sidebar


class TestMathsSidebarWithQuestions:
    """When maths has questions, the maths sidebar shows subject-specific links."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, questions):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/")
        page.wait_for_load_state("domcontentloaded")

    def test_home_link_visible(self):
        assert_sidebar_has_link(self.page, "Home")

    def test_home_navigates_to_maths_not_hub(self):
        """Home in maths sidebar should go to /maths/, NOT /hub/."""
        click_sidebar_link(self.page, "Home")
        expect(self.page).to_have_url(re.compile(r"/maths/$"))

    def test_topic_quizzes_link(self):
        assert_sidebar_has_link(self.page, "Topic Quizzes")

    def test_basic_facts_link(self):
        click_sidebar_link(self.page, "Basic Facts")
        expect(self.page).to_have_url(re.compile(r"/basic-facts"))

    def test_times_tables_link(self):
        click_sidebar_link(self.page, "Times Tables")
        expect(self.page).to_have_url(re.compile(r"/times-tables"))

    def test_my_progress_link(self):
        click_sidebar_link(self.page, "My Progress")
        expect(self.page).to_have_url(re.compile(r"/student-dashboard"))

    def test_billing_link(self):
        assert_sidebar_has_link(self.page, "Billing")

    def test_profile_link(self):
        assert_sidebar_has_link(self.page, "Profile")

    # Common links should also appear in maths sidebar
    def test_my_classes_link(self):
        assert_sidebar_has_link(self.page, "My Classes")

    def test_homework_link(self):
        assert_sidebar_has_link(self.page, "Homework")

    def test_attendance_link(self):
        assert_sidebar_has_link(self.page, "Attendance")


class TestMathsSidebarOnQuizPages:
    """Maths sidebar should also show on quiz pages when questions exist."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom, questions):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)

    def test_basic_facts_page_has_maths_sidebar(self):
        self.page.goto(f"{self.url}/maths/basic-facts/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(self.page, "Topic Quizzes")
        assert_sidebar_has_link(self.page, "Basic Facts")
        assert_sidebar_has_link(self.page, "Times Tables")

    def test_times_tables_page_has_maths_sidebar(self):
        self.page.goto(f"{self.url}/maths/times-tables/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_sidebar_has_link(self.page, "Topic Quizzes")
        assert_sidebar_has_link(self.page, "Times Tables")


class TestMathsFallbackNoQuestions:
    """When maths has no questions, /maths/ falls back to sidebar_student.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, enrolled_student, school, classroom):
        # No 'questions' fixture → no maths questions in DB
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, enrolled_student)
        page.goto(f"{self.url}/maths/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_topic_quizzes_link(self):
        assert_sidebar_missing_link(self.page, "Topic Quizzes")

    def test_no_basic_facts_link(self):
        assert_sidebar_missing_link(self.page, "Basic Facts")

    def test_no_times_tables_link(self):
        assert_sidebar_missing_link(self.page, "Times Tables")

    def test_common_links_present_with_classes(self):
        """Fallback sidebar shows class-dependent links when student has classes."""
        assert_sidebar_has_link(self.page, "My Classes")
        assert_sidebar_has_link(self.page, "Homework")
        assert_sidebar_has_link(self.page, "Attendance")
        assert_sidebar_has_link(self.page, "Billing")
        assert_sidebar_has_link(self.page, "Profile")


class TestMathsSidebarNoClasses:
    """Class-dependent links hidden when student has no class enrollments."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, student_user, school, roles):
        # student_user with NO ClassStudent enrollment
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, student_user)
        page.goto(f"{self.url}/maths/")
        page.wait_for_load_state("domcontentloaded")

    def test_no_my_classes_link(self):
        assert_sidebar_missing_link(self.page, "My Classes")

    def test_no_homework_link(self):
        assert_sidebar_missing_link(self.page, "Homework")

    def test_no_attendance_link(self):
        assert_sidebar_missing_link(self.page, "Attendance")

    def test_join_class_still_visible(self):
        """Join Class should always be visible so students can enroll."""
        assert_sidebar_has_link(self.page, "Join Class")

    def test_billing_still_visible(self):
        assert_sidebar_has_link(self.page, "Billing")

    def test_profile_still_visible(self):
        assert_sidebar_has_link(self.page, "Profile")
