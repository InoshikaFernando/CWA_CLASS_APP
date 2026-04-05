"""UI tests for the parent portal — dashboard, classes, attendance, progress,
invoices, payments, add-child, and self-registration."""

import re

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import _ensure_sidebar_visible, assert_sidebar_has_link, click_sidebar_link

pytestmark = pytest.mark.parent_portal


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

class TestParentSidebarNewLinks:
    """Verify the new sidebar links added in the parent portal polish."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_add_child_link_visible(self):
        assert_sidebar_has_link(self.page, "Add Child")

    def test_classes_link_visible(self):
        assert_sidebar_has_link(self.page, "Classes")

    def test_add_child_link_navigates(self):
        click_sidebar_link(self.page, "Add Child")
        expect(self.page).to_have_url(re.compile(r"/parent/add-child/"))

    def test_classes_link_navigates(self):
        click_sidebar_link(self.page, "Classes")
        expect(self.page).to_have_url(re.compile(r"/parent/classes/"))


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------

class TestParentDashboard:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/"))

    def test_shows_child_name(self):
        expect(self.page.locator("body")).to_contain_text("Ui Student")

    def test_shows_class_count(self):
        expect(self.page.locator("body")).to_contain_text("Classes")

    def test_shows_attendance_stat(self):
        expect(self.page.locator("body")).to_contain_text("Attendance")

    def test_shows_unpaid_stat(self):
        expect(self.page.locator("body")).to_contain_text("Unpaid")


class TestParentAddChildLinkInDashboard:
    """Add Child link is visible on dashboard and navigates correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/")
        page.wait_for_load_state("domcontentloaded")

    def test_add_child_sidebar_link_navigates(self):
        click_sidebar_link(self.page, "Add Child")
        expect(self.page).to_have_url(re.compile(r"/parent/add-child/"))


# ---------------------------------------------------------------------------
# Add Child
# ---------------------------------------------------------------------------

class TestParentAddChild:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/add-child/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/add-child/"))

    def test_student_id_input_visible(self):
        expect(self.page.locator("input[name='student_id']")).to_be_visible()

    def test_relationship_select_visible(self):
        expect(self.page.locator("select[name='relationship']")).to_be_visible()

    def test_invalid_student_id_shows_error(self):
        self.page.fill("input[name='student_id']", "STU-INVALID-9999")
        self.page.get_by_role("button", name="Link Child").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("was not found")

    def test_empty_submit_shows_error(self):
        # Spaces pass HTML5 required but Django's .strip() makes it blank → server error
        self.page.fill("input[name='student_id']", "   ")
        self.page.get_by_role("button", name="Link Child").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("required")

    def test_cancel_returns_to_dashboard(self):
        self.page.get_by_text("Cancel").click()
        expect(self.page).to_have_url(re.compile(r"/parent/"))


# ---------------------------------------------------------------------------
# Self-Registration
# ---------------------------------------------------------------------------

class TestParentSelfRegistration:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page):
        self.url = live_server.url
        self.page = page
        page.goto(f"{self.url}/accounts/register/parent-join/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/accounts/register/parent-join/"))

    def test_heading_visible(self):
        expect(self.page.locator("h1")).to_contain_text("Register as Parent")

    def test_first_name_input_visible(self):
        expect(self.page.locator("input[name='first_name']")).to_be_visible()

    def test_email_input_visible(self):
        expect(self.page.locator("input[name='email']")).to_be_visible()

    def test_student_id_info_visible(self):
        expect(self.page.locator("body")).to_contain_text("Student ID")

    def test_empty_submit_shows_errors(self):
        # Disable HTML5 validation so Django server-side errors appear in the DOM
        self.page.evaluate("document.querySelector('form').noValidate = true")
        self.page.locator("button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")
        expect(self.page.locator("body")).to_contain_text("required")

    def test_invalid_student_id_shows_error(self):
        self.page.fill("input[name='first_name']", "Test")
        self.page.fill("input[name='last_name']", "Parent")
        self.page.fill("input[name='email']", "testparent_ui@example.com")
        self.page.fill("input[name='password']", "TestPass123!")
        self.page.fill("input[name='confirm_password']", "TestPass123!")
        self.page.fill("input[name='student_id_0']", "STU-INVALID-0000")
        self.page.locator("button[type='submit']").click()
        self.page.wait_for_load_state("domcontentloaded")
        body = self.page.locator("body").inner_text().lower()
        assert "not found" in body or "no valid" in body or "error" in body or "invalid" in body


# ---------------------------------------------------------------------------
# Classes
# ---------------------------------------------------------------------------

class TestParentClasses:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/classes/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/classes/"))

    def test_page_heading(self):
        expect(self.page.locator("h1")).to_contain_text("Classes")

    def test_shows_child_name(self):
        expect(self.page.locator("body")).to_contain_text("Ui Student")

    def test_shows_enrolled_class(self):
        expect(self.page.locator("body")).to_contain_text("Year 7 Maths")


# ---------------------------------------------------------------------------
# Attendance
# ---------------------------------------------------------------------------

class TestParentAttendance:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school, student_attendance):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/attendance/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/attendance/"))

    def test_page_heading(self):
        expect(self.page.locator("h1")).to_contain_text("Attendance")

    def test_shows_stats(self):
        expect(self.page.locator("body")).to_contain_text("Sessions")


# ---------------------------------------------------------------------------
# Progress
# ---------------------------------------------------------------------------

class TestParentProgress:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, enrolled_student, school, subject, level, db):
        from classroom.models import ProgressCriteria, ProgressRecord
        # Create a criteria and a progress record so the stats panel is visible
        criteria = ProgressCriteria.objects.create(
            school=school,
            subject=subject,
            level=level,
            name="Understand fractions",
            order=1,
            status='approved',
        )
        ProgressRecord.objects.create(
            student=enrolled_student,
            criteria=criteria,
            status='achieved',
        )
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/progress/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/progress/"))

    def test_page_heading(self):
        expect(self.page.locator("h1")).to_contain_text("Progress")

    def test_shows_criteria(self):
        expect(self.page.locator("body")).to_contain_text("Total Criteria")


# ---------------------------------------------------------------------------
# Invoices
# ---------------------------------------------------------------------------

class TestParentInvoices:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, parent_with_child, school, enrolled_student, classroom, db):
        from decimal import Decimal
        from datetime import date, timedelta
        from classroom.models import Invoice
        # Create an issued invoice so the parent can see it
        self.issued_invoice = Invoice.objects.create(
            student=enrolled_student,
            school=school,
            invoice_number="INV-PARENT-001",
            billing_period_start=date.today() - timedelta(days=30),
            billing_period_end=date.today(),
            status="issued",
            amount=Decimal("120.00"),
            calculated_amount=Decimal("120.00"),
        )
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, parent_with_child)
        page.goto(f"{self.url}/parent/invoices/")
        page.wait_for_load_state("domcontentloaded")

    def test_page_loads(self):
        expect(self.page).to_have_url(re.compile(r"/parent/invoices/"))

    def test_page_heading(self):
        expect(self.page.locator("h1")).to_contain_text("Invoices")

    def test_shows_invoice_number(self):
        expect(self.page.locator("body")).to_contain_text("INV-PARENT-001")
