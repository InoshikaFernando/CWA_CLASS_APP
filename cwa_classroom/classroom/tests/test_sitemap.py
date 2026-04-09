"""
Sitemap tests — verify every URL in the sitemap returns HTTP 200.

Two test suites:
  1. SitemapPublicTest   — public pages, no login needed (uses TestCase for DB-querying views)
  2. SitemapAuthenticatedTest — login-required pages; creates a school + student user,
     logs in, then confirms each page loads.  Django rolls back the whole transaction at
     class teardown (effectively cascade-deleting the school, user, and all related rows).
"""
from xml.etree import ElementTree
from urllib.parse import urlparse

from django.test import TestCase
from django.utils import timezone

from cwa_classroom.sitemaps import StaticViewSitemap, AuthenticatedViewSitemap


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _path(loc: str) -> str:
    """Strip scheme + host, return only the path portion."""
    return urlparse(loc).path or "/"


# ---------------------------------------------------------------------------
# 1. Public pages
# ---------------------------------------------------------------------------

class SitemapXMLTest(TestCase):
    """Verify /sitemap.xml itself returns 200 and is well-formed XML."""

    def test_sitemap_returns_200(self):
        response = self.client.get("/sitemap.xml")
        self.assertEqual(response.status_code, 200)

    def test_sitemap_content_type(self):
        response = self.client.get("/sitemap.xml")
        self.assertIn("xml", response["Content-Type"])

    def test_sitemap_is_valid_xml(self):
        response = self.client.get("/sitemap.xml")
        ElementTree.fromstring(response.content)  # raises on malformed XML

    def test_sitemap_contains_urls(self):
        response = self.client.get("/sitemap.xml")
        tree = ElementTree.fromstring(response.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        locs = tree.findall(".//sm:loc", ns)
        self.assertGreater(len(locs), 0, "Sitemap should contain at least one <loc>")


class SitemapPublicURLsTest(TestCase):
    """Parse /sitemap.xml and verify every <loc> returns 200."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from django.test import Client
        client = Client()
        response = client.get("/sitemap.xml")
        assert response.status_code == 200, "/sitemap.xml did not return 200"
        tree = ElementTree.fromstring(response.content)
        ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
        cls.sitemap_locs = [
            loc.text.strip() for loc in tree.findall(".//sm:loc", ns)
        ]

    def test_sitemap_url_count(self):
        expected = len(StaticViewSitemap._pages) + len(AuthenticatedViewSitemap._pages)
        self.assertEqual(
            len(self.sitemap_locs), expected,
            f"Expected {expected} sitemap URLs, got {len(self.sitemap_locs)}",
        )

    def test_public_sitemap_pages_return_200(self):
        """Public pages (no auth required) must return 200."""
        sm = StaticViewSitemap()
        failures = []
        for item in sm.items():
            path = sm.location(item)
            response = self.client.get(path, follow=True)
            if response.status_code != 200:
                failures.append(f"{path} → {response.status_code}")
        if failures:
            self.fail(
                "Public sitemap pages that did not return 200:\n"
                + "\n".join(f"  {f}" for f in failures)
            )


class SitemapItemsDirectTest(TestCase):
    """Direct test of StaticViewSitemap items — no XML parsing overhead."""

    def setUp(self):
        self.sm = StaticViewSitemap()

    def test_every_item_has_valid_location(self):
        for item in self.sm.items():
            path = self.sm.location(item)
            self.assertTrue(path.startswith("/"), f"Expected absolute path, got: {path!r}")

    def test_every_item_returns_200(self):
        failures = []
        for item in self.sm.items():
            path = self.sm.location(item)
            response = self.client.get(path, follow=True)
            if response.status_code != 200:
                failures.append(f"{path} → {response.status_code}")
        if failures:
            self.fail(
                "Public sitemap pages that did not return 200:\n"
                + "\n".join(f"  {f}" for f in failures)
            )


# ---------------------------------------------------------------------------
# 2. Authenticated pages
# ---------------------------------------------------------------------------

class SitemapAuthenticatedTest(TestCase):
    """
    Tests every login-required page in AuthenticatedViewSitemap.

    Setup
    -----
    * Creates a School with an admin user (as requested, for cascade cleanup).
    * Creates an INDIVIDUAL_STUDENT user with an active Subscription so that
      TrialExpiryMiddleware lets them through.
    * Logs in as that student before each test method.

    Teardown
    --------
    Django's TestCase wraps setUpTestData in a transaction and rolls it back
    at the end of the test class — this effectively cascade-deletes the school,
    users, subscription, and all related rows without any explicit delete call.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser, Role, UserRole
        from billing.models import Package, Subscription
        from classroom.models import School

        # ── School + admin ────────────────────────────────────────────────
        cls.admin_user = CustomUser.objects.create_user(
            username="sitemap_admin",
            email="sitemap_admin@test.internal",
            password="Sitemap@2024!",
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN,
            defaults={"display_name": "Admin"},
        )
        UserRole.objects.create(user=cls.admin_user, role=admin_role)

        cls.school = School.objects.create(
            name="Sitemap Test School",
            slug="sitemap-test-school",
            admin=cls.admin_user,
            is_active=True,
        )
        # School.save() auto-calls _ensure_admin_is_hoi(), which creates
        # SchoolTeacher(head_of_institute) + HEAD_OF_INSTITUTE UserRole for admin_user.

        # ── Individual student + active subscription ──────────────────────
        cls.student = CustomUser.objects.create_user(
            username="sitemap_student",
            email="sitemap_student@test.internal",
            password="Sitemap@2024!",
        )
        student_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT,
            defaults={"display_name": "Individual Student"},
        )
        UserRole.objects.create(user=cls.student, role=student_role)

        # Active subscription → TrialExpiryMiddleware won't redirect
        package = Package.objects.create(
            name="Sitemap Test Package",
            price="0.00",
            is_active=True,
        )
        Subscription.objects.create(
            user=cls.student,
            package=package,
            status=Subscription.STATUS_ACTIVE,
            current_period_end=timezone.now() + timezone.timedelta(days=365),
        )

    def setUp(self):
        """Log in as the student before every test method."""
        self.client.login(username="sitemap_student", password="Sitemap@2024!")

    # ── Structural tests ──────────────────────────────────────────────────

    def test_every_authenticated_item_has_valid_location(self):
        sm = AuthenticatedViewSitemap()
        for item in sm.items():
            path = sm.location(item)
            self.assertTrue(
                path.startswith("/"),
                f"location() should return an absolute path, got: {path!r}",
            )

    # ── 200 checks ───────────────────────────────────────────────────────

    def test_all_authenticated_pages_return_200(self):
        """Every login-required page must return 200 when logged in as student."""
        sm = AuthenticatedViewSitemap()
        failures = []
        for item in sm.items():
            path = sm.location(item)
            response = self.client.get(path, follow=True)
            if response.status_code != 200:
                failures.append(f"{path} → {response.status_code}")
        if failures:
            self.fail(
                "Authenticated sitemap pages that did not return 200:\n"
                + "\n".join(f"  {f}" for f in failures)
            )

    def test_authenticated_pages_redirect_to_login_when_anonymous(self):
        """The same pages must redirect anonymous visitors (not 200)."""
        from django.test import Client
        anon = Client()
        sm = AuthenticatedViewSitemap()
        non_redirecting = []
        for item in sm.items():
            path = sm.location(item)
            response = anon.get(path)
            # We expect a redirect (302) to the login page, NOT a 200
            if response.status_code == 200:
                non_redirecting.append(path)
        if non_redirecting:
            self.fail(
                "These 'authenticated' pages returned 200 for anonymous users "
                "(they should redirect to login):\n"
                + "\n".join(f"  {p}" for p in non_redirecting)
            )
