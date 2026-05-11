"""
test_live_sidebar.py — Browser-only sidebar tests against a deployed environment.

Run:
    pytest ui_tests/test_live_sidebar.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests every sidebar link for every role using sanitized test users.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .helpers import (
    _ensure_sidebar_visible,
    assert_sidebar_has_link,
    assert_sidebar_missing_link,
    click_sidebar_link,
)
from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"

# ── Sanitized user mapping (from dev DB) ──────────────────────────────────
ADMIN_EMAIL = "user1@test.local"
TEACHER_EMAIL = "user45@test.local"
STUDENT_EMAIL = "user46@test.local"
HOI_EMAIL = "user52@test.local"
HOD_EMAIL = "user53@test.local"         # also senior_teacher
SENIOR_TEACHER_EMAIL = "user53@test.local"
ACCOUNTANT_EMAIL = "user71@test.local"
PARENT_EMAIL = "user73@test.local"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


# ═══════════════════════════════════════════════════════════════════════════
# Admin Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAdminSidebar:
    """Verify admin sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/admin-dashboard/"))

    def test_schools_link(self):
        assert_sidebar_has_link(self.page, "Schools")

    def test_teachers_link(self):
        click_sidebar_link(self.page, "Teachers")
        expect(self.page).to_have_url(re.compile(r"/teachers"))

    def test_students_link(self):
        click_sidebar_link(self.page, "Students")
        expect(self.page).to_have_url(re.compile(r"/students"))

    def test_parents_link(self):
        click_sidebar_link(self.page, "Parents")
        expect(self.page).to_have_url(re.compile(r"/parents"))

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    def test_academic_years_link(self):
        click_sidebar_link(self.page, "Academic Years")
        expect(self.page).to_have_url(re.compile(r"/academic-years|/terms"))

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        assert "Server Error" not in self.page.content()

    def test_enrollment_requests_link(self):
        click_sidebar_link(self.page, "Enrollment Requests")
        assert "Server Error" not in self.page.content()

    def test_browse_topics_link(self):
        click_sidebar_link(self.page, "Browse Topics")
        expect(self.page).to_have_url(re.compile(r"/topics"))

    def test_upload_questions_link(self):
        assert_sidebar_has_link(self.page, "Upload Questions")

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    def test_email_link(self):
        click_sidebar_link(self.page, "Email")
        assert "Server Error" not in self.page.content()

    def test_billing_link(self):
        assert_sidebar_has_link(self.page, "Billing")

    def test_events_link(self):
        click_sidebar_link(self.page, "Events")
        expect(self.page).to_have_url(re.compile(r"/audit/events"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    def test_billing_admin_visible_for_superuser(self):
        assert_sidebar_has_link(self.page, "Billing Admin")


# ═══════════════════════════════════════════════════════════════════════════
# Teacher Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveTeacherSidebar:
    """Verify teacher sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, TEACHER_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/teacher/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/teacher/"))

    def test_my_classes_link(self):
        click_sidebar_link(self.page, "My Classes")
        expect(self.page).to_have_url(re.compile(r"/hub/|/teacher/"))

    def test_enrollments_link(self):
        click_sidebar_link(self.page, "Enrollments")
        assert "Server Error" not in self.page.content()

    def test_attendance_approvals_link(self):
        click_sidebar_link(self.page, "Attendance Approvals")
        assert "Server Error" not in self.page.content()

    def test_class_progress_link(self):
        click_sidebar_link(self.page, "Class Progress")
        assert "Server Error" not in self.page.content()

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        assert "Server Error" not in self.page.content()

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


# ═══════════════════════════════════════════════════════════════════════════
# Student Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveStudentSidebar:
    """Verify student sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/student/my-classes/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_home_link(self):
        assert_sidebar_has_link(self.page, "Home")

    def test_home_navigates_to_hub(self):
        click_sidebar_link(self.page, "Home")
        expect(self.page).to_have_url(re.compile(r"/hub/"))

    def test_my_classes_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="My Classes").first
        if link.count():
            expect(link).to_be_visible()

    def test_join_class_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Join Class").first
        if link.count():
            link.click()
            self.page.wait_for_load_state("domcontentloaded")
            expect(self.page).to_have_url(re.compile(r"/student/join|/billing/module-required"))

    def test_my_progress_link(self):
        click_sidebar_link(self.page, "My Progress")
        expect(self.page).to_have_url(re.compile(r"/student-dashboard"))

    def test_attendance_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Attendance").first
        if link.count():
            link.click()
            self.page.wait_for_load_state("domcontentloaded")
            expect(self.page).to_have_url(re.compile(r"/attendance|/billing/module-required"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


# ═══════════════════════════════════════════════════════════════════════════
# Parent Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveParentSidebar:
    """Verify parent sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, PARENT_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/parent/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        assert "Server Error" not in self.page.content()

    def test_my_children_link(self):
        click_sidebar_link(self.page, "My Children")
        expect(self.page).to_have_url(re.compile(r"/parent/"))

    def test_attendance_link(self):
        click_sidebar_link(self.page, "Attendance")
        expect(self.page).to_have_url(re.compile(r"/attendance"))

    def test_invoices_link(self):
        click_sidebar_link(self.page, "Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoices"))

    def test_payments_link(self):
        click_sidebar_link(self.page, "Payments")
        expect(self.page).to_have_url(re.compile(r"/payments"))

    def test_progress_link(self):
        click_sidebar_link(self.page, "Progress")
        expect(self.page).to_have_url(re.compile(r"/progress"))

    def test_homework_link(self):
        assert_sidebar_has_link(self.page, "Homework")

    def test_homework_navigates(self):
        click_sidebar_link(self.page, "Homework")
        expect(self.page).to_have_url(re.compile(r"/parent/homework"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


# ═══════════════════════════════════════════════════════════════════════════
# HoI Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveHoiSidebar:
    """Verify HoI sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, HOI_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy|/billing/module-required"))

    def test_departments_link(self):
        click_sidebar_link(self.page, "Departments")
        expect(self.page).to_have_url(re.compile(r"/departments"))

    def test_subjects_link(self):
        click_sidebar_link(self.page, "Subjects")
        expect(self.page).to_have_url(re.compile(r"/subjects|/subject-levels"))

    def test_academic_levels_link(self):
        click_sidebar_link(self.page, "Academic Levels")
        expect(self.page).to_have_url(re.compile(r"/subject-levels"))

    def test_classes_link(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/manage-classes"))

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_ai_import_link(self):
        click_sidebar_link(self.page, "AI Import Questions")
        expect(self.page).to_have_url(re.compile(r"/ai-import"))

    def test_teachers_link(self):
        click_sidebar_link(self.page, "Teachers")
        expect(self.page).to_have_url(re.compile(r"/teachers"))

    def test_students_link(self):
        click_sidebar_link(self.page, "Students")
        expect(self.page).to_have_url(re.compile(r"/students"))

    def test_parents_link(self):
        click_sidebar_link(self.page, "Parents")
        expect(self.page).to_have_url(re.compile(r"/parents"))

    def test_enrollments_link(self):
        assert_sidebar_has_link(self.page, "Enrollment")

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    def test_teacher_workload_link(self):
        click_sidebar_link(self.page, "Teacher Workload")
        expect(self.page).to_have_url(re.compile(r"/workload"))

    def test_departmental_reports_link(self):
        click_sidebar_link(self.page, "Departmental Reports")
        expect(self.page).to_have_url(re.compile(r"/reports"))

    def test_fee_configuration_link(self):
        click_sidebar_link(self.page, "Fee Configuration")
        expect(self.page).to_have_url(re.compile(r"/invoicing/fees"))

    def test_opening_balances_link(self):
        click_sidebar_link(self.page, "Opening Balances")
        expect(self.page).to_have_url(re.compile(r"/opening-balances"))

    def test_generate_invoices_link(self):
        click_sidebar_link(self.page, "Generate Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/generate"))

    def test_invoices_link(self):
        click_sidebar_link(self.page, "Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/"))

    def test_rate_configuration_link(self):
        click_sidebar_link(self.page, "Rate Configuration")
        expect(self.page).to_have_url(re.compile(r"/salaries/rates"))

    def test_generate_salary_slips_link(self):
        click_sidebar_link(self.page, "Generate Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/generate"))

    def test_salary_slips_link(self):
        click_sidebar_link(self.page, "Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/"))

    def test_events_link(self):
        click_sidebar_link(self.page, "Events")
        expect(self.page).to_have_url(re.compile(r"/audit/events"))

    def test_billing_link(self):
        assert_sidebar_has_link(self.page, "Billing")

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    def test_institution_setup_section(self):
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Institution Setup")
        expect(toggle.first).to_be_visible()

    def test_invoicing_section(self):
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Invoicing")
        expect(toggle.first).to_be_visible()

    def test_salaries_section(self):
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Salaries")
        expect(toggle.first).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════
# HoD Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveHodSidebar:
    """Verify HoD sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, HOD_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/dashboard/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_dashboard_navigates(self):
        click_sidebar_link(self.page, "Dashboard")
        expect(self.page).to_have_url(re.compile(r"/dashboard/"))

    def test_school_hierarchy_link(self):
        click_sidebar_link(self.page, "School Hierarchy")
        expect(self.page).to_have_url(re.compile(r"/school-hierarchy|/billing/module-required"))

    def test_classes_link(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/manage-classes"))

    def test_academic_levels_link(self):
        click_sidebar_link(self.page, "Academic Levels")
        expect(self.page).to_have_url(re.compile(r"/subject-levels"))

    def test_teacher_workload_link(self):
        click_sidebar_link(self.page, "Teacher Workload")
        expect(self.page).to_have_url(re.compile(r"/workload"))

    def test_import_students_link(self):
        click_sidebar_link(self.page, "Import Students")
        expect(self.page).to_have_url(re.compile(r"/import-students"))

    def test_import_balances_link(self):
        click_sidebar_link(self.page, "Import Balances")
        expect(self.page).to_have_url(re.compile(r"/import-balances"))

    def test_create_questions_link(self):
        click_sidebar_link(self.page, "Create Questions")
        expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


# ═══════════════════════════════════════════════════════════════════════════
# Accountant Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAccountantSidebar:
    """Verify accountant sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ACCOUNTANT_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/accounting/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_user_statistics_link(self):
        click_sidebar_link(self.page, "User Statistics")
        expect(self.page).to_have_url(re.compile(r"/users"))

    def test_export_reports_link(self):
        click_sidebar_link(self.page, "Export Reports")
        expect(self.page).to_have_url(re.compile(r"/export"))

    def test_refunds_link(self):
        click_sidebar_link(self.page, "Refunds")
        expect(self.page).to_have_url(re.compile(r"/refunds"))

    def test_institute_settings_link(self):
        click_sidebar_link(self.page, "Institute Settings")
        expect(self.page).to_have_url(re.compile(r"/settings|/manage-settings|/accounting/"))

    def test_fee_configuration_link(self):
        click_sidebar_link(self.page, "Fee Configuration")
        expect(self.page).to_have_url(re.compile(r"/invoicing/fees"))

    def test_opening_balances_link(self):
        click_sidebar_link(self.page, "Opening Balances")
        expect(self.page).to_have_url(re.compile(r"/opening-balances"))

    def test_upload_payments_link(self):
        click_sidebar_link(self.page, "Upload Bank Statements")
        expect(self.page).to_have_url(re.compile(r"/invoicing/csv"))

    def test_reference_mappings_link(self):
        click_sidebar_link(self.page, "Reference Mappings")
        expect(self.page).to_have_url(re.compile(r"/reference-mappings"))

    def test_generate_invoices_link(self):
        click_sidebar_link(self.page, "Generate Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/generate"))

    def test_invoices_link(self):
        click_sidebar_link(self.page, "Invoices")
        expect(self.page).to_have_url(re.compile(r"/invoicing/"))

    def test_rate_configuration_link(self):
        click_sidebar_link(self.page, "Rate Configuration")
        expect(self.page).to_have_url(re.compile(r"/salaries/rates"))

    def test_generate_salary_slips_link(self):
        click_sidebar_link(self.page, "Generate Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/generate"))

    def test_salary_slips_link(self):
        click_sidebar_link(self.page, "Salary Slips")
        expect(self.page).to_have_url(re.compile(r"/salaries/"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))

    def test_invoicing_section_visible(self):
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Invoicing")
        expect(toggle).to_be_visible()

    def test_salaries_section_visible(self):
        _ensure_sidebar_visible(self.page)
        toggle = self.page.locator("aside#sidebar button", has_text="Salaries")
        expect(toggle).to_be_visible()


# ═══════════════════════════════════════════════════════════════════════════
# Senior Teacher Sidebar
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveSeniorTeacherSidebar:
    """Verify senior teacher sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, SENIOR_TEACHER_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/teacher/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_dashboard_link(self):
        assert_sidebar_has_link(self.page, "Dashboard")

    def test_classes_link(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/manage-classes|/teacher/"))

    def test_browse_topics_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Browse Topics").first
        if link.count():
            link.click()
            self.page.wait_for_load_state("domcontentloaded")
            expect(self.page).to_have_url(re.compile(r"/topics"))

    def test_upload_questions_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Upload Questions").first
        if link.count():
            link.click()
            self.page.wait_for_load_state("domcontentloaded")
            expect(self.page).to_have_url(re.compile(r"/upload"))

    def test_create_questions_link(self):
        _ensure_sidebar_visible(self.page)
        link = self.page.locator("aside#sidebar a", has_text="Create Questions").first
        if link.count():
            link.click()
            self.page.wait_for_load_state("domcontentloaded")
            expect(self.page).to_have_url(re.compile(r"/create-question"))

    def test_profile_link(self):
        click_sidebar_link(self.page, "Profile")
        expect(self.page).to_have_url(re.compile(r"/accounts/profile"))


# ═══════════════════════════════════════════════════════════════════════════
# Maths Sidebar (Student on /maths/)
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveMathsSidebar:
    """Verify maths subject sidebar links on the deployed environment."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        page.goto(f"{live_url}/maths/")
        page.wait_for_load_state("domcontentloaded")
        self.page = page
        self.url = live_url

    def test_home_link(self):
        assert_sidebar_has_link(self.page, "Home")

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

    def test_profile_link(self):
        assert_sidebar_has_link(self.page, "Profile")
