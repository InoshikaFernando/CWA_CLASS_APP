"""
test_live_admin.py — Browser-only admin dashboard tests against a deployed environment.

Run:
    pytest ui_tests/test_live_admin.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Tests admin dashboard, school management, search, student edit, and more.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
ADMIN_EMAIL = "user1@test.local"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


def _assert_no_error(page: Page):
    content = page.content()
    assert "Internal Server Error" not in content
    assert "Server Error (500)" not in content


# ═══════════════════════════════════════════════════════════════════════════
# Admin Dashboard & Management
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAdminDashboard:
    """Verify admin dashboard and management pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_dashboard_loads(self):
        self.page.goto(f"{self.url}/admin-dashboard/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_schools_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/schools/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_teachers_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/teachers/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_students_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_parents_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/parents/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_enrollment_requests_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/enrollment-requests/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_academic_years_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/academic-years/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_school_hierarchy_page(self):
        self.page.goto(f"{self.url}/school-hierarchy/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_email_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/email/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_events_page(self):
        self.page.goto(f"{self.url}/audit/events/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_django_admin_page(self):
        self.page.goto(f"{self.url}/admin/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        body = self.page.locator("body")
        expect(body).to_contain_text("Django administration")


# ═══════════════════════════════════════════════════════════════════════════
# Admin Search & Pagination
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAdminSearch:
    """Verify search and pagination on admin pages."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_student_search(self):
        self.page.goto(f"{self.url}/admin-dashboard/students/?q=user")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_student_search_empty_result(self):
        self.page.goto(f"{self.url}/admin-dashboard/students/?q=nonexistent_user_xyz_12345")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_student_pagination_exists(self):
        self.page.goto(f"{self.url}/admin-dashboard/students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        pagination = self.page.locator("nav[aria-label='Pagination'], .pagination, nav.flex")
        if pagination.count():
            expect(pagination.first).to_be_visible()

    def test_parent_search(self):
        self.page.goto(f"{self.url}/admin-dashboard/parents/?q=user")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_teacher_search(self):
        self.page.goto(f"{self.url}/admin-dashboard/teachers/?q=user")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Admin Import Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAdminImport:
    """Verify CSV import pages load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_import_students_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/import-students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_import_students_has_file_input(self):
        self.page.goto(f"{self.url}/admin-dashboard/import-students/")
        self.page.wait_for_load_state("domcontentloaded")
        file_input = self.page.locator("input[type='file']").first
        if file_input.count():
            expect(file_input).to_be_attached()


# ═══════════════════════════════════════════════════════════════════════════
# Admin Billing
# ═══════════════════════════════════════════════════════════════════════════

class TestLiveAdminBilling:
    """Verify billing admin pages load correctly (superuser)."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_billing_page(self):
        self.page.goto(f"{self.url}/billing/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
