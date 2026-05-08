"""
test_live_smoke.py — Browser-only E2E tests against a deployed environment.

Run:
    pytest ui_tests/test_live_smoke.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x

These tests create all data through the UI (no Django ORM), so they work
without a local database connection. They validate the full stack: forms,
views, database writes, and page rendering.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import (
    LIVE_PASSWORD,
    create_department,
    create_school,
    create_student,
    create_teacher,
    live_login,
    live_logout,
    register_hoi,
    unique,
)

pytestmark = pytest.mark.live


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


@pytest.fixture(scope="module")
def browser_page(browser):
    context = browser.new_context(viewport={"width": 1280, "height": 800})
    page = context.new_page()
    yield page
    context.close()


@pytest.fixture(scope="module")
def hoi_account(browser_page, live_url):
    """Register a fresh Head of Institute account via the UI."""
    return register_hoi(browser_page, live_url)


@pytest.fixture(scope="module")
def school_setup(browser_page, live_url, hoi_account):
    """Login as HoI and create school infrastructure via UI."""
    live_login(browser_page, live_url, hoi_account["email"], hoi_account["password"])

    # Find the school ID — HoI was redirected after registration
    browser_page.goto(f"{live_url}/admin-dashboard/")
    browser_page.wait_for_load_state("domcontentloaded")

    # Look for school link in the admin dashboard
    school_link = browser_page.locator("a[href*='/schools/']").first
    if school_link.count():
        href = school_link.get_attribute("href")
        match = re.search(r"/schools/(\d+)", href)
        school_id = int(match.group(1)) if match else None
    else:
        school_id = None

    return {"school_id": school_id, **hoi_account}


class TestLoginPage:
    """Verify the login page renders correctly."""

    def test_login_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        expect(page.locator("#id_username")).to_be_visible()
        expect(page.locator("#id_password")).to_be_visible()

    def test_login_page_has_submit_button(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        submit = page.locator("button[type='submit'], input[type='submit']").first
        expect(submit).to_be_visible()

    def test_invalid_login_shows_error(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        page.locator("#id_username").fill("nonexistent@test.local")
        page.locator("#id_password").fill("wrongpassword")
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_load_state("domcontentloaded")
        # Should stay on login page
        assert "/accounts/login" in page.url


class TestSanitizedUserLogin:
    """Test login with sanitized database users (Password1!)."""

    def test_sanitized_user_can_login(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/login/")
        page.wait_for_load_state("domcontentloaded")
        page.locator("#id_username").fill("user1@test.local")
        page.locator("#id_password").fill("Password1!")
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=15_000)
        assert "/accounts/login" not in page.url


class TestHoIRegistration:
    """Test the Head of Institute registration flow."""

    def test_registration_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/teacher-center/")
        page.wait_for_load_state("domcontentloaded")
        assert page.url.endswith("/accounts/register/teacher-center/") or \
               "register" in page.url

    def test_register_and_login(self, live_url, page: Page):
        """Full registration flow: register HoI, then verify login works."""
        account = register_hoi(page, live_url)
        live_logout(page, live_url)

        # Login with the new account
        live_login(page, live_url, account["email"], account["password"])
        assert "/accounts/login" not in page.url


class TestAdminDashboard:
    """Test admin dashboard pages load after login."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, "user1@test.local", "Password1!")
        yield
        live_logout(page, live_url)

    def test_admin_dashboard_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/admin/")
        page.wait_for_load_state("domcontentloaded")
        assert page.url.endswith("/admin/") or "admin" in page.url

    def test_maths_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/maths/")
        page.wait_for_load_state("domcontentloaded")
        # Should not be a 500 error
        assert "Internal Server Error" not in page.content()

    def test_coding_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/coding/")
        page.wait_for_load_state("domcontentloaded")
        assert "Internal Server Error" not in page.content()


class TestTeacherCreation:
    """Test creating a teacher through the admin UI."""

    def test_create_teacher_via_ui(self, live_url, page: Page, school_setup):
        if not school_setup["school_id"]:
            pytest.skip("No school_id found")

        live_login(page, live_url, school_setup["email"], school_setup["password"])
        teacher = create_teacher(page, live_url, school_setup["school_id"])

        # Verify teacher was created — logout and login as new teacher
        live_logout(page, live_url)
        live_login(page, live_url, teacher["email"], teacher["password"])
        assert "/accounts/login" not in page.url


class TestStudentCreation:
    """Test creating a student through the admin UI."""

    def test_create_student_via_ui(self, live_url, page: Page, school_setup):
        if not school_setup["school_id"]:
            pytest.skip("No school_id found")

        live_login(page, live_url, school_setup["email"], school_setup["password"])
        student = create_student(page, live_url, school_setup["school_id"])

        # Verify student was created — logout and login as new student
        live_logout(page, live_url)
        live_login(page, live_url, student["email"], student["password"])
        assert "/accounts/login" not in page.url


class TestDepartmentCreation:
    """Test creating a department through the admin UI."""

    def test_create_department_via_ui(self, live_url, page: Page, school_setup):
        if not school_setup["school_id"]:
            pytest.skip("No school_id found")

        live_login(page, live_url, school_setup["email"], school_setup["password"])
        dept = create_department(page, live_url, school_setup["school_id"])
        assert dept["dept_name"]
