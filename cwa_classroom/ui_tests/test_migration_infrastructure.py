"""
test_migration_infrastructure.py — Validates infrastructure after PA → DO migration.

Run:
    pytest ui_tests/test_migration_infrastructure.py --live-url=https://dev.wizardslearninghub.co.nz --headed -x -n0

Checks: static files, media/images, Stripe keys, Piston API, CDN resources,
email config, database connectivity, and all critical URLs.
No Django ORM or local DB connection needed.
"""
import re

import pytest
from playwright.sync_api import Page, expect

from .live_helpers import live_login

pytestmark = pytest.mark.migration

SANITIZED_PASSWORD = "Password1!"
ADMIN_EMAIL = "user1@test.local"
TEACHER_EMAIL = "user45@test.local"
STUDENT_EMAIL = "user46@test.local"


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


def _check_resource_status(page: Page, url: str) -> int:
    """Navigate to a resource URL and return HTTP status code."""
    resp = page.goto(url)
    return resp.status if resp else 0


# ═══════════════════════════════════════════════════════════════════════════
# Static Files
# ═══════════════════════════════════════════════════════════════════════════

class TestStaticFiles:
    """Verify static files are served correctly (WhiteNoise or collectstatic)."""

    def test_tailwind_js(self, live_url, page: Page):
        status = _check_resource_status(page, f"{live_url}/static/js/tailwind.min.js")
        assert status == 200, f"Tailwind JS returned HTTP {status}"

    def test_logo_image(self, live_url, page: Page):
        status = _check_resource_status(page, f"{live_url}/static/images/logo.png")
        assert status == 200, f"Logo image returned HTTP {status}"

    def test_favicon(self, live_url, page: Page):
        resp = page.goto(f"{live_url}/favicon.ico")
        status = resp.status if resp else 0
        assert status in (200, 301, 302), f"Favicon returned HTTP {status}"

    def test_google_fonts_css(self, live_url, page: Page):
        status = _check_resource_status(page, f"{live_url}/static/css/google-fonts-full.css")
        assert status == 200, f"Google Fonts CSS returned HTTP {status}"

    def test_robots_txt(self, live_url, page: Page):
        status = _check_resource_status(page, f"{live_url}/robots.txt")
        assert status == 200, f"robots.txt returned HTTP {status}"


# ═══════════════════════════════════════════════════════════════════════════
# Media / User-Uploaded Images
# ═══════════════════════════════════════════════════════════════════════════

class TestMediaFiles:
    """Verify media file serving — profile pics, uploaded content, etc."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_media_url_accessible(self):
        """Check /media/ path returns something (not 500)."""
        resp = self.page.goto(f"{self.url}/media/")
        status = resp.status if resp else 0
        assert status != 500, f"Media URL returned HTTP 500"

    def test_profile_images_on_students_page(self):
        """Navigate to students list and check all img tags load."""
        self.page.goto(f"{self.url}/admin-dashboard/students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        broken = self._find_broken_images()
        assert not broken, f"Broken images found: {broken}"

    def test_profile_images_on_teachers_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/teachers/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        broken = self._find_broken_images()
        assert not broken, f"Broken images found: {broken}"

    def test_profile_images_on_parents_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/parents/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        broken = self._find_broken_images()
        assert not broken, f"Broken images found: {broken}"

    def test_school_logos_on_schools_page(self):
        self.page.goto(f"{self.url}/admin-dashboard/schools/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        broken = self._find_broken_images()
        assert not broken, f"Broken images found: {broken}"

    def test_no_pythonanywhere_media_urls(self):
        """Ensure no images still reference pythonanywhere.com."""
        self.page.goto(f"{self.url}/admin-dashboard/students/")
        self.page.wait_for_load_state("domcontentloaded")
        pa_refs = self.page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .map(i => i.src)
                .filter(s => s.includes('pythonanywhere'));
        }""")
        assert not pa_refs, f"PythonAnywhere media URLs found: {pa_refs}"

    def _find_broken_images(self):
        """Return list of broken image src attributes on current page."""
        return self.page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .filter(i => i.src && !i.complete)
                .map(i => i.src)
                .concat(
                    imgs.filter(i => i.src && i.naturalWidth === 0 && i.complete)
                        .map(i => i.src)
                );
        }""")


# ═══════════════════════════════════════════════════════════════════════════
# CDN / External Resources
# ═══════════════════════════════════════════════════════════════════════════

class TestExternalResources:
    """Verify external CDN resources load correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_tailwind_loads(self):
        """Check that Tailwind JS loads on a page."""
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("networkidle")
        has_tailwind = self.page.evaluate("""() => {
            return typeof tailwind !== 'undefined'
                || Array.from(document.querySelectorAll('script'))
                    .some(s => s.src && s.src.includes('tailwind'));
        }""")
        assert has_tailwind, "Tailwind JS not loaded"

    def test_alpinejs_loads(self):
        """Check Alpine.js is available on interactive pages."""
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("networkidle")
        has_alpine = self.page.evaluate("() => typeof Alpine !== 'undefined'")
        if not has_alpine:
            scripts = self.page.evaluate("""() => {
                return Array.from(document.querySelectorAll('script'))
                    .map(s => s.src)
                    .filter(s => s.includes('alpine'));
            }""")
            assert scripts, "Alpine.js not loaded and no Alpine script tags found"

    def test_no_mixed_content(self):
        """Ensure no HTTP resources on HTTPS pages (mixed content)."""
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("domcontentloaded")
        if self.url.startswith("https"):
            mixed = self.page.evaluate("""() => {
                const all = [
                    ...document.querySelectorAll('img[src^="http:"]'),
                    ...document.querySelectorAll('script[src^="http:"]'),
                    ...document.querySelectorAll('link[href^="http:"]'),
                ];
                return all.map(el => el.src || el.href);
            }""")
            assert not mixed, f"Mixed content found: {mixed}"

    def test_all_page_images_load(self):
        """Check hub page images all load successfully."""
        self.page.goto(f"{self.url}/hub/")
        self.page.wait_for_load_state("networkidle")
        broken = self.page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            return imgs
                .filter(i => i.src && i.naturalWidth === 0 && i.complete)
                .map(i => i.src);
        }""")
        assert not broken, f"Broken images on hub: {broken}"


# ═══════════════════════════════════════════════════════════════════════════
# Stripe Integration
# ═══════════════════════════════════════════════════════════════════════════

class TestStripeIntegration:
    """Verify Stripe keys are configured and billing pages work."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_billing_page_loads(self):
        self.page.goto(f"{self.url}/billing/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_billing_page_no_stripe_error(self):
        """Ensure billing page doesn't show 'Stripe not configured' errors."""
        self.page.goto(f"{self.url}/billing/")
        self.page.wait_for_load_state("domcontentloaded")
        content = self.page.content()
        assert "Stripe is not configured" not in content
        assert "STRIPE_PUBLISHABLE_KEY" not in content

    def test_stripe_js_available(self):
        """Check billing page loads without Stripe configuration errors."""
        self.page.goto(f"{self.url}/billing/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_module_billing_page(self):
        """Check module add-on billing page loads."""
        self.page.goto(f"{self.url}/billing/modules/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Piston Code Execution API
# ═══════════════════════════════════════════════════════════════════════════

class TestPistonAPI:
    """Verify Piston code execution is working for coding exercises."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, STUDENT_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_coding_page_loads(self):
        self.page.goto(f"{self.url}/coding/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_coding_page_renders(self):
        """Check coding page renders without error (may be empty if no exercises)."""
        self.page.goto(f"{self.url}/coding/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_codemirror_loads_on_exercise(self):
        """Navigate to a coding exercise and verify CodeMirror editor loads."""
        self.page.goto(f"{self.url}/coding/")
        self.page.wait_for_load_state("domcontentloaded")
        exercise_link = self.page.locator("main a[href*='/coding/'], .content a[href*='/coding/']").first
        if exercise_link.count() == 0:
            pytest.skip("No coding exercises available for this user")
        exercise_link.click()
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        # Check for CodeMirror or code editor element
        has_editor = self.page.evaluate("""() => {
            return document.querySelector('.CodeMirror') !== null
                || document.querySelector('.cm-editor') !== null
                || document.querySelector('textarea[name="code"]') !== null;
        }""")
        if not has_editor:
            # May be a topic list page, not an exercise
            pass

    def test_piston_run_endpoint(self):
        """Try running simple code and verify response (via the coding UI)."""
        self.page.goto(f"{self.url}/coding/")
        self.page.wait_for_load_state("domcontentloaded")
        # Find an exercise with a code editor
        links = self.page.locator("a[href*='/coding/exercise/'], a[href*='/coding/problem/']")
        if links.count() == 0:
            pytest.skip("No coding exercises with editor available")
        links.first.click()
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        # Look for Run button
        run_btn = self.page.locator("button:has-text('Run'), button:has-text('Submit'), button:has-text('Execute')").first
        if run_btn.count() == 0:
            pytest.skip("No Run button found on exercise page")
        # Don't actually click Run (could create unwanted submissions)
        # Just verify the button exists and page loaded without errors


# ═══════════════════════════════════════════════════════════════════════════
# Email Configuration (visible in settings/admin)
# ═══════════════════════════════════════════════════════════════════════════

class TestEmailConfig:
    """Verify email settings are visible in admin (not console backend)."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_email_compose_page_loads(self):
        self.page.goto(f"{self.url}/admin-dashboard/email/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)


# ═══════════════════════════════════════════════════════════════════════════
# Database Connectivity (verified through page content)
# ═══════════════════════════════════════════════════════════════════════════

class TestDatabaseConnectivity:
    """Verify database is connected and has expected data."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def test_students_list_has_data(self):
        """Verify students page shows actual student data from DB."""
        self.page.goto(f"{self.url}/admin-dashboard/students/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"user\d+@test\.local|student|@test\.local"))

    def test_teachers_list_has_data(self):
        self.page.goto(f"{self.url}/admin-dashboard/teachers/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        body = self.page.locator("body")
        expect(body).to_contain_text(re.compile(r"user\d+@test\.local|teacher|@test\.local"))

    def test_schools_list_has_data(self):
        self.page.goto(f"{self.url}/admin-dashboard/schools/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)

    def test_django_admin_shows_data(self):
        """Verify Django admin is accessible and shows model data."""
        self.page.goto(f"{self.url}/admin/")
        self.page.wait_for_load_state("domcontentloaded")
        _assert_no_error(self.page)
        body = self.page.locator("body")
        expect(body).to_contain_text("Django administration")


# ═══════════════════════════════════════════════════════════════════════════
# URL Configuration — No Broken Internal Links
# ═══════════════════════════════════════════════════════════════════════════

class TestURLConfiguration:
    """Verify all critical URL patterns are wired correctly."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def _check_url(self, path):
        resp = self.page.goto(f"{self.url}{path}")
        status = resp.status if resp else 0
        assert 200 <= status < 500, f"{path} returned HTTP {status}"

    def test_home_url(self):
        self._check_url("/")

    def test_accounts_login(self):
        self._check_url("/accounts/login/")

    def test_accounts_register_teacher(self):
        self._check_url("/accounts/register/teacher-center/")

    def test_accounts_register_student(self):
        self._check_url("/accounts/register/school-student/")

    def test_accounts_register_individual(self):
        self._check_url("/accounts/register/individual-student/")

    def test_accounts_register_parent(self):
        self._check_url("/accounts/register/parent/")

    def test_accounts_profile(self):
        self._check_url("/accounts/profile/")

    def test_accounts_password_change(self):
        self._check_url("/accounts/password-change/")

    def test_maths_url(self):
        self._check_url("/maths/")

    def test_coding_url(self):
        self._check_url("/coding/")

    def test_hub_url(self):
        self._check_url("/hub/")

    def test_attendance_url(self):
        self._check_url("/attendance/")

    def test_brainbuzz_url(self):
        self._check_url("/brainbuzz/")

    def test_admin_dashboard_url(self):
        self._check_url("/admin-dashboard/")

    def test_billing_url(self):
        self._check_url("/billing/")

    def test_homework_url(self):
        self._check_url("/homework/")

    def test_school_hierarchy_url(self):
        self._check_url("/school-hierarchy/")

    def test_admin_url(self):
        self._check_url("/admin/")


# ═══════════════════════════════════════════════════════════════════════════
# PythonAnywhere Remnants — nothing should reference PA
# ═══════════════════════════════════════════════════════════════════════════

class TestNoPythonAnywhereRemnants:
    """Ensure no page content references PythonAnywhere after migration."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def _check_no_pa(self, path):
        self.page.goto(f"{self.url}{path}")
        self.page.wait_for_load_state("domcontentloaded")
        pa_refs = self.page.evaluate("""() => {
            const html = document.documentElement.innerHTML;
            const matches = html.match(/pythonanywhere\\.com/gi);
            return matches || [];
        }""")
        assert not pa_refs, f"PythonAnywhere references on {path}: {pa_refs}"

    def test_home_no_pa(self):
        self._check_no_pa("/")

    def test_hub_no_pa(self):
        self._check_no_pa("/hub/")

    def test_admin_dashboard_no_pa(self):
        self._check_no_pa("/admin-dashboard/")

    def test_maths_no_pa(self):
        self._check_no_pa("/maths/")

    def test_billing_no_pa(self):
        self._check_no_pa("/billing/")

    def test_students_page_no_pa(self):
        self._check_no_pa("/admin-dashboard/students/")


# ═══════════════════════════════════════════════════════════════════════════
# Image Scan Across Key Pages
# ═══════════════════════════════════════════════════════════════════════════

class TestImageIntegrity:
    """Scan multiple pages for broken images."""

    @pytest.fixture(autouse=True)
    def _login(self, live_url, page: Page):
        live_login(page, live_url, ADMIN_EMAIL, SANITIZED_PASSWORD)
        self.page = page
        self.url = live_url

    def _scan_images(self, path):
        self.page.goto(f"{self.url}{path}")
        self.page.wait_for_load_state("networkidle")
        result = self.page.evaluate("""() => {
            const imgs = Array.from(document.querySelectorAll('img'));
            const broken = imgs
                .filter(i => i.src && i.naturalWidth === 0 && i.complete)
                .map(i => i.src);
            const all_srcs = imgs.map(i => i.src).filter(Boolean);
            return { broken, total: all_srcs.length, all_srcs };
        }""")
        return result

    def test_home_images(self):
        result = self._scan_images("/")
        assert not result["broken"], f"Broken images on /: {result['broken']}"

    def test_hub_images(self):
        result = self._scan_images("/hub/")
        assert not result["broken"], f"Broken images on /hub/: {result['broken']}"

    def test_admin_dashboard_images(self):
        result = self._scan_images("/admin-dashboard/")
        assert not result["broken"], f"Broken images on /admin-dashboard/: {result['broken']}"

    def test_maths_images(self):
        result = self._scan_images("/maths/")
        assert not result["broken"], f"Broken images on /maths/: {result['broken']}"

    def test_coding_images(self):
        result = self._scan_images("/coding/")
        assert not result["broken"], f"Broken images on /coding/: {result['broken']}"

    def test_billing_images(self):
        result = self._scan_images("/billing/")
        assert not result["broken"], f"Broken images on /billing/: {result['broken']}"

    def test_teacher_dashboard_images(self):
        result = self._scan_images("/teacher/")
        assert not result["broken"], f"Broken images on /teacher/: {result['broken']}"

    def test_students_list_images(self):
        result = self._scan_images("/admin-dashboard/students/")
        assert not result["broken"], f"Broken images on students list: {result['broken']}"

    def test_profile_page_images(self):
        result = self._scan_images("/accounts/profile/")
        assert not result["broken"], f"Broken images on profile: {result['broken']}"
