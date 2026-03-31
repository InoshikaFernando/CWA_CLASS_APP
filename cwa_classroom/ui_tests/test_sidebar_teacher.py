"""Tests for the teacher sidebar — every link."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.sidebar


class TestTeacherSidebarLinks:
    """Each link in sidebar_teacher.html."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user, school, department, classroom):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, teacher_user)
        page.goto(f"{self.url}/teacher/")
        page.wait_for_load_state("domcontentloaded")

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/teacher/"))

    def test_my_classes_link(self):
        click_sidebar_link(self.page, "My Classes")
        expect(self.page).to_have_url(re.compile(r"/hub/"))

    def test_enrollments_link(self):
        click_sidebar_link(self.page, "Enrollments")
        expect(self.page).to_have_url(re.compile(r"/enrollment"))

    def test_attendance_approvals_link(self):
        click_sidebar_link(self.page, "Attendance Approvals")
        expect(self.page).to_have_url(re.compile(r"/attendance-approvals"))

    def test_class_progress_link(self):
        click_sidebar_link(self.page, "Class Progress")
        expect(self.page).to_have_url(re.compile(r"/class/progress"))

    def test_student_progress_report_link(self):
        click_sidebar_link(self.page, "Student Progress Report")
        expect(self.page).to_have_url(re.compile(r"/progress/report"))

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy"))

    def test_browse_topics_link(self):
        click_sidebar_link(self.page, "Browse Topics")
        expect(self.page).to_have_url(re.compile(r"/topics"))

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_upload_questions_link(self):
        click_sidebar_link(self.page, "Upload Questions")
        expect(self.page).to_have_url(re.compile(r"/upload"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))
