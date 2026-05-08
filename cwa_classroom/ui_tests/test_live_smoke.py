"""
test_live_smoke.py — Browser-only E2E tests against a deployed environment.

Run:
    pytest ui_tests/test_live_smoke.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Validates that the app, database, migrations, and key pages are working
by logging in with sanitized test credentials and navigating key flows.
No Django ORM or local DB connection needed.
"""
import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login, live_logout

pytestmark = pytest.mark.live

SANITIZED_PASSWORD = "Password1!"


@pytest.fixture(scope="module")
def live_url(request):
    url = request.config.getoption("--live-url", default=None)
    if not url:
        pytest.skip("--live-url not provided")
    return url.rstrip("/")


# ═══════════════════════════════════════════════════════════════════════════
# Login & Authentication
# ═══════════════════════════════════════════════════════════════════════════

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
        assert "/accounts/login" in page.url

    def test_sanitized_user_can_login(self, live_url, page: Page):
        live_login(page, live_url, "user1@test.local", SANITIZED_PASSWORD)
        assert "/accounts/login" not in page.url


# ═══════════════════════════════════════════════════════════════════════════
# Registration pages load
# ═══════════════════════════════════════════════════════════════════════════

class TestRegistrationPages:
    """Verify registration pages render without errors."""

    def test_teacher_center_registration_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/teacher-center/")
        page.wait_for_load_state("domcontentloaded")
        assert "Internal Server Error" not in page.content()

    def test_school_student_registration_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/school-student/")
        page.wait_for_load_state("domcontentloaded")
        assert "Internal Server Error" not in page.content()

    def test_individual_student_registration_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/register/individual-student/")
        page.wait_for_load_state("domcontentloaded")
        assert "Internal Server Error" not in page.content()


# ═══════════════════════════════════════════════════════════════════════════
# Django Admin
# ═══════════════════════════════════════════════════════════════════════════

class TestDjangoAdmin:
    """Verify Django admin loads (requires staff user)."""

    def test_admin_login_page_loads(self, live_url, page: Page):
        page.goto(f"{live_url}/admin/login/")
        page.wait_for_load_state("domcontentloaded")
        assert "Internal Server Error" not in page.content()


# ═══════════════════════════════════════════════════════════════════════════
# Authenticated pages — test with sanitized user
# ═══════════════════════════════════════════════════════════════════════════

class TestAuthenticatedPages:
    """Login with sanitized user and verify key pages load without 500s."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, "user1@test.local", SANITIZED_PASSWORD)
        yield

    def _assert_no_error(self, page: Page):
        content = page.content()
        assert "Internal Server Error" not in content
        assert "Server Error (500)" not in content

    def test_home_page(self, live_url, page: Page):
        page.goto(f"{live_url}/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_maths_page(self, live_url, page: Page):
        page.goto(f"{live_url}/maths/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_coding_page(self, live_url, page: Page):
        page.goto(f"{live_url}/coding/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_hub_page(self, live_url, page: Page):
        page.goto(f"{live_url}/hub/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_teacher_dashboard(self, live_url, page: Page):
        page.goto(f"{live_url}/teacher/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_admin_dashboard(self, live_url, page: Page):
        page.goto(f"{live_url}/admin-dashboard/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_brainbuzz_page(self, live_url, page: Page):
        page.goto(f"{live_url}/brainbuzz/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_attendance_page(self, live_url, page: Page):
        page.goto(f"{live_url}/attendance/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_profile_page(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/profile/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)

    def test_password_change_page(self, live_url, page: Page):
        page.goto(f"{live_url}/accounts/password-change/")
        page.wait_for_load_state("domcontentloaded")
        self._assert_no_error(page)
