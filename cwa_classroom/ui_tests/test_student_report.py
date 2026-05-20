"""
UI tests for CPP-294: Student Report page.

Tests cover:
- HoI can access the report and see students
- Filters (class, status, no_class) narrow the results
- Combined filters + reset
- HoD sees only department-scoped students
- Teacher is denied access
- Sidebar "Reports" section and "Student Report" link are visible
- Empty state is displayed when no students match
"""

import pytest
from playwright.sync_api import expect

from .conftest import do_login, _make_user, _RUN_ID

pytestmark = pytest.mark.reports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _enrol_student_in_school(school, username="report_stu"):
    from accounts.models import Role
    from classroom.models import SchoolStudent

    stu = _make_user(f"{username}_{_RUN_ID}", Role.STUDENT)
    SchoolStudent.objects.get_or_create(school=school, student=stu)
    return stu


def _enrol_student_in_class(classroom, student, school):
    from classroom.models import ClassStudent, SchoolStudent

    SchoolStudent.objects.get_or_create(school=school, student=student)
    ClassStudent.objects.get_or_create(classroom=classroom, student=student, defaults={"is_active": True})


# ---------------------------------------------------------------------------
# HoI — core access
# ---------------------------------------------------------------------------

class TestHoiStudentReport:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        do_login(page, self.url, hoi_user)

    def test_hoi_can_access_student_report(self):
        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_role("heading", name="Student Report")).to_be_visible()

    def test_hoi_sees_enrolled_students(self):
        stu = _enrol_student_in_school(self.school, "vis_stu")
        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text(stu.get_full_name() or stu.username)).to_be_visible()

    def test_hoi_filter_by_class(self, classroom):
        stu = _enrol_student_in_school(self.school, "cls_stu")
        _enrol_student_in_class(classroom, stu, self.school)
        stu_no_class = _enrol_student_in_school(self.school, "no_cls_stu")

        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")

        # Select the class in the dropdown
        self.page.select_option("select[name='class_id']", str(classroom.pk))
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.get_by_text(stu.get_full_name() or stu.username, exact=True)).to_be_visible()

    def test_hoi_filter_by_status_inactive(self):
        from classroom.models import SchoolStudent

        stu = _enrol_student_in_school(self.school, "inactive_stu")
        SchoolStudent.objects.filter(school=self.school, student=stu).update(is_active=False)

        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")

        self.page.select_option("select[name='status']", "inactive")
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.locator(".font-medium", has_text="Inactive Stu")).to_be_visible()

    def test_hoi_not_in_class_filter(self, classroom):
        stu_in_class = _enrol_student_in_school(self.school, "in_cls")
        _enrol_student_in_class(classroom, stu_in_class, self.school)
        stu_no_class = _enrol_student_in_school(self.school, "out_cls")

        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")

        self.page.check("input[name='no_class']")
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.get_by_text("No class")).to_be_visible()

    def test_hoi_reset_clears_filters(self):
        self.page.goto(f"{self.url}/reports/students/?status=inactive")
        self.page.wait_for_load_state("domcontentloaded")
        self.page.get_by_role("link", name="Reset", exact=True).click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(f"{self.url}/reports/students/")

    def test_empty_state_displayed(self):
        # School has no students
        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_text("No students match")).to_be_visible()


# ---------------------------------------------------------------------------
# Sidebar visibility
# ---------------------------------------------------------------------------

class TestReportsSidebarLink:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f"{self.url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")

    def test_sidebar_reports_section_visible(self):
        expect(self.page.get_by_role("button", name="Reports")).to_be_visible()

    def test_sidebar_student_report_link_navigates(self):
        self.page.get_by_role("button", name="Reports").click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role("link", name="Student Report").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page).to_have_url(f"{self.url}/reports/students/")


# ---------------------------------------------------------------------------
# Access denied — teacher
# ---------------------------------------------------------------------------

class TestTeacherDenied:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, teacher_user)

    def test_teacher_cannot_access_student_report(self):
        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")
        # RoleRequiredMixin redirects to public home
        expect(self.page).not_to_have_url(f"{self.url}/reports/students/")


# ---------------------------------------------------------------------------
# HoD scoping
# ---------------------------------------------------------------------------

class TestHodScoping:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hod_user, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        self.department = department
        do_login(page, self.url, hod_user)

    def test_hod_can_access_student_report(self):
        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.get_by_role("heading", name="Student Report")).to_be_visible()

    def test_hod_sees_only_department_students(self, classroom):
        from accounts.models import Role
        from classroom.models import ClassStudent, SchoolStudent

        # Student in HoD's department class
        stu_in = _make_user(f"hod_stu_in_{_RUN_ID}", Role.STUDENT)
        SchoolStudent.objects.get_or_create(school=self.school, student=stu_in)
        ClassStudent.objects.create(classroom=classroom, student=stu_in, is_active=True)

        # Student with no class (should NOT appear for HoD)
        stu_out = _make_user(f"hod_stu_out_{_RUN_ID}", Role.STUDENT)
        SchoolStudent.objects.get_or_create(school=self.school, student=stu_out)

        self.page.goto(f"{self.url}/reports/students/")
        self.page.wait_for_load_state("domcontentloaded")

        expect(self.page.get_by_text(stu_in.get_full_name() or stu_in.username)).to_be_visible()
        expect(self.page.get_by_text(stu_out.get_full_name() or stu_out.username)).not_to_be_visible()
