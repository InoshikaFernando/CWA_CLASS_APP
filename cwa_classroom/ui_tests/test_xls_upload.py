"""End-to-end tests: upload Teachworks .xls files, import users, verify login."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from .conftest import TEST_PASSWORD, _assign_role, _get_or_create_role, do_login
from .helpers import assert_page_has_text
from .xls_fixtures import create_parent_xls, create_student_xls, create_teacher_xls

pytestmark = pytest.mark.csv_import


# ═══════════════════════════════════════════════════════════════════════════
# Fixtures — timestamped school without departments
# ═══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def ts():
    """Unique timestamp suffix for this test run."""
    return str(int(time.time() * 1000))[-8:]


@pytest.fixture
def import_school(db, ts):
    """Create a timestamped school without departments.

    No departments → student import skips the structure-mapping step.
    Cascade-deleted on teardown.
    """
    from accounts.models import CustomUser, Role, UserRole
    from billing.models import InstitutePlan, SchoolSubscription
    from classroom.models import School, SchoolTeacher

    # Create admin/HoI user
    admin = CustomUser.objects.create_user(
        username=f"hoi_{ts}",
        password=TEST_PASSWORD,
        email=f"hoi_{ts}@test.local",
        first_name="HoI",
        last_name=f"Admin{ts}",
        profile_completed=True,
        must_change_password=False,
    )
    role = _get_or_create_role(Role.INSTITUTE_OWNER)
    UserRole.objects.get_or_create(user=admin, role=role)

    school = School.objects.create(
        name=f"Test School {ts}",
        slug=f"test-school-{ts}",
        admin=admin,
        is_active=True,
    )
    plan = InstitutePlan.objects.create(
        name=f"Basic-{ts}",
        slug=f"basic-{ts}",
        price=Decimal("89.00"),
        stripe_price_id=f"price_test_{ts}",
        class_limit=50,
        student_limit=500,
        invoice_limit_yearly=500,
        extra_invoice_rate=Decimal("0.30"),
    )
    SchoolSubscription.objects.create(
        school=school, plan=plan, status="active",
    )
    SchoolTeacher.objects.get_or_create(
        school=school, teacher=admin,
        defaults={"role": "head_of_institute"},
    )

    yield {"school": school, "admin": admin, "ts": ts}

    # Teardown: cascade-delete school and all related objects
    school.delete()
    admin.delete()


# ═══════════════════════════════════════════════════════════════════════════
# Teacher XLS upload — full wizard
# ═══════════════════════════════════════════════════════════════════════════

class TestTeacherXLSUpload:
    """Upload a Teachworks teacher .xls, drive through the wizard, verify import."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, import_school, tmp_path):
        self.url = live_server.url
        self.page = page
        self.school_data = import_school
        self.admin = import_school["admin"]
        self.ts = import_school["ts"]
        self.tmp_path = str(tmp_path)

    def test_upload_and_import_teachers(self):
        page = self.page
        do_login(page, self.url, self.admin)

        # Create XLS file
        xls_path, teachers = create_teacher_xls(self.tmp_path, self.ts)

        # Step 1: Upload page — select Teachworks preset, upload file
        page.goto(f"{self.url}/import-teachers/")
        page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(page, "Import Teachers")

        # Select Teachworks preset
        page.locator("#preset-label-teachworks").click()
        page.locator("input[name='csv_file']").set_input_files(xls_path)
        page.get_by_role("button", name="Upload & Map Columns").click()
        page.wait_for_load_state("domcontentloaded")

        # Step 1b: Column mapping page — preset auto-applied
        assert_page_has_text(page, "Map Columns")
        assert_page_has_text(page, "Preset applied")

        # Submit mapping → preview
        page.get_by_role("button", name="Preview Import").click()
        page.wait_for_load_state("domcontentloaded")

        # Step 2: Preview page — verify teachers listed
        assert_page_has_text(page, "Preview Teacher Import")
        assert_page_has_text(page, teachers[0]["first_name"])
        assert_page_has_text(page, teachers[1]["first_name"])

        # Step 3: Confirm import
        page.locator("#confirm-btn").click()
        page.wait_for_load_state("domcontentloaded")

        # Results page
        assert_page_has_text(page, "Teacher Import Complete")
        assert_page_has_text(page, "Accounts Created")


# ═══════════════════════════════════════════════════════════════════════════
# Student XLS upload — full wizard
# ═══════════════════════════════════════════════════════════════════════════

class TestStudentXLSUpload:
    """Upload a Teachworks student .xls, drive through the wizard, verify import."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, import_school, tmp_path):
        self.url = live_server.url
        self.page = page
        self.school_data = import_school
        self.admin = import_school["admin"]
        self.ts = import_school["ts"]
        self.tmp_path = str(tmp_path)

    def test_upload_and_import_students(self):
        page = self.page
        do_login(page, self.url, self.admin)

        # Create XLS file
        xls_path, students = create_student_xls(self.tmp_path, self.ts)

        # Step 1: Upload page — select Teachworks preset, upload file
        page.goto(f"{self.url}/import-students/")
        page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(page, "Import Students")

        # Select Teachworks preset
        page.locator("#preset-label-teachworks").click()
        page.locator("input[name='csv_file']").set_input_files(xls_path)
        page.get_by_role("button", name="Upload & Map Columns").click()
        page.wait_for_load_state("domcontentloaded")

        # Step 1b: Column mapping page — preset auto-applied
        assert_page_has_text(page, "Map Columns")
        assert_page_has_text(page, "Preset applied")

        # Submit mapping → preview (no departments → skips structure mapping)
        page.get_by_role("button", name="Preview Import").click()
        page.wait_for_load_state("domcontentloaded")

        # Step 2: Preview page — verify students listed
        assert_page_has_text(page, "Preview Import")
        assert_page_has_text(page, students[0]["first_name"])
        assert_page_has_text(page, students[1]["first_name"])

        # Step 3: Confirm import
        page.locator("#confirm-btn").click()
        page.wait_for_load_state("domcontentloaded")

        # Results page
        assert_page_has_text(page, "Import Complete")
        assert_page_has_text(page, "Students Created")


# ═══════════════════════════════════════════════════════════════════════════
# Login tests — imported users can log in
# ═══════════════════════════════════════════════════════════════════════════

class TestImportedUserLogin:
    """Import users via import_services, then verify login through Playwright."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, import_school, tmp_path):
        self.url = live_server.url
        self.page = page
        self.school_data = import_school
        self.school = import_school["school"]
        self.admin = import_school["admin"]
        self.ts = import_school["ts"]
        self.tmp_path = str(tmp_path)

    def _import_teachers(self):
        """Import teachers via service layer. Returns credentials list."""
        from classroom import import_services as isvc

        xls_path, _ = create_teacher_xls(self.tmp_path, self.ts)
        with open(xls_path, "rb") as f:
            headers, data_rows = isvc.parse_upload_file(f.read(), xls_path)

        preset_mapping = isvc.apply_teacher_preset("teachworks", headers)
        preview = isvc.validate_teacher_preview(data_rows, preset_mapping, self.school)
        results = isvc.execute_teacher_import(preview, self.school, self.admin)
        return results["credentials"]

    def _import_students(self):
        """Import students via service layer. Returns (credentials, student_dicts)."""
        from classroom import import_services as isvc

        xls_path, students = create_student_xls(self.tmp_path, self.ts)
        with open(xls_path, "rb") as f:
            headers, data_rows = isvc.parse_upload_file(f.read(), xls_path)

        preset_mapping = isvc.apply_preset("teachworks", headers)
        preview = isvc.validate_and_preview(data_rows, preset_mapping, self.school)
        results = isvc.execute_import(preview, self.school, self.admin)
        return results["credentials"], students

    def _import_parents(self, student_names):
        """Import parents via service layer. Students must exist first.

        ``student_names`` is a list of (first_name, last_name) tuples.
        Returns credentials list.
        """
        from classroom import import_services as isvc

        xls_path, _ = create_parent_xls(self.tmp_path, student_names, self.ts)
        with open(xls_path, "rb") as f:
            headers, data_rows = isvc.parse_upload_file(f.read(), xls_path)

        preset_mapping = isvc.apply_parent_preset("teachworks", headers)
        preview = isvc.validate_parent_preview(data_rows, preset_mapping, self.school)
        results = isvc.execute_parent_import(preview, self.school, self.admin)
        return results["credentials"]

    def test_imported_teacher_can_login(self):
        """A teacher imported via XLS can log in and reaches complete-profile."""
        from accounts.models import CustomUser

        creds = self._import_teachers()
        assert len(creds) >= 1, "Expected at least 1 teacher credential"

        teacher_cred = creds[0]
        user = CustomUser.objects.get(username=teacher_cred["username"])

        # Login via Playwright
        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(teacher_cred["username"])
        page.locator("#id_password").fill(teacher_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)

        # Imported teachers have must_change_password=True → redirected to complete-profile
        page.wait_for_load_state("domcontentloaded")
        assert "complete-profile" in page.url
        assert_page_has_text(page, "password")

    def test_imported_student_can_login(self):
        """A student imported via XLS can log in and reaches complete-profile."""
        from accounts.models import CustomUser

        creds, _ = self._import_students()
        # Filter to student-only credentials
        student_cred = next(c for c in creds if c.get("type") != "parent")
        user = CustomUser.objects.get(username=student_cred["username"])

        # Login via Playwright
        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(student_cred["username"])
        page.locator("#id_password").fill(student_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)

        # Imported students have must_change_password=True → redirected to complete-profile
        page.wait_for_load_state("domcontentloaded")
        assert "complete-profile" in page.url
        assert_page_has_text(page, "password")

    def test_imported_teacher_login_then_dashboard(self):
        """A teacher with profile completed can reach the dashboard after login."""
        from accounts.models import CustomUser

        creds = self._import_teachers()
        assert len(creds) >= 1

        teacher_cred = creds[0]
        user = CustomUser.objects.get(username=teacher_cred["username"])
        # Mark profile as complete so they go to dashboard
        user.must_change_password = False
        user.profile_completed = True
        user.save(update_fields=["must_change_password", "profile_completed"])

        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(teacher_cred["username"])
        page.locator("#id_password").fill(teacher_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)
        page.wait_for_load_state("domcontentloaded")

        # Teacher should reach teacher dashboard
        assert "/accounts/login" not in page.url
        assert_page_has_text(page, "Teacher Dashboard")

    def test_imported_student_login_then_dashboard(self):
        """A student with profile completed can reach the student hub."""
        from accounts.models import CustomUser

        creds, _ = self._import_students()
        assert len(creds) >= 1

        # Filter to student-only credentials (exclude parents)
        student_cred = next(c for c in creds if c.get("type") != "parent")
        user = CustomUser.objects.get(username=student_cred["username"])
        # Mark profile as complete so they go to dashboard
        user.must_change_password = False
        user.profile_completed = True
        user.save(update_fields=["must_change_password", "profile_completed"])

        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(student_cred["username"])
        page.locator("#id_password").fill(student_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)
        page.wait_for_load_state("domcontentloaded")

        # Student should reach the hub home page
        assert "/accounts/login" not in page.url
        assert_page_has_text(page, "Home")

    def test_imported_parent_can_login(self):
        """A parent created during student import can log in."""
        from accounts.models import CustomUser

        # Student import now also creates parent accounts from guardian data
        all_creds, students = self._import_students()
        parent_creds = [c for c in all_creds if c.get("type") == "parent"]
        assert len(parent_creds) >= 1, "Expected at least 1 parent credential from student import"

        parent_cred = parent_creds[0]

        # Login via Playwright
        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(parent_cred["username"])
        page.locator("#id_password").fill(parent_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)

        # Imported parents have must_change_password=True → redirected to complete-profile
        page.wait_for_load_state("domcontentloaded")
        assert "complete-profile" in page.url
        assert_page_has_text(page, "password")

    def test_imported_parent_login_then_dashboard(self):
        """A parent with profile completed can reach the parent dashboard."""
        from accounts.models import CustomUser

        all_creds, students = self._import_students()
        parent_creds = [c for c in all_creds if c.get("type") == "parent"]
        assert len(parent_creds) >= 1

        parent_cred = parent_creds[0]
        user = CustomUser.objects.get(username=parent_cred["username"])
        user.must_change_password = False
        user.profile_completed = True
        user.save(update_fields=["must_change_password", "profile_completed"])

        page = self.page
        page.goto(f"{self.url}/accounts/login/")
        page.wait_for_load_state("networkidle")
        page.locator("#id_username").fill(parent_cred["username"])
        page.locator("#id_password").fill(parent_cred["password"])
        page.locator("button[type='submit'], input[type='submit']").first.click()
        page.wait_for_url(lambda url: "/accounts/login" not in url, timeout=10_000)

        # Parent should reach the parent dashboard
        page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(page, "children")
