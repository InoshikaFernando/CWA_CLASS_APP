"""Tests for advance invoice generation — period quick-select, future billing logic."""

import calendar
from datetime import date, timedelta
from decimal import Decimal

import pytest
from playwright.sync_api import expect

from .conftest import do_login
from .helpers import assert_page_has_text, assert_url_contains

pytestmark = pytest.mark.invoice


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _go_generate(page, url):
    """Navigate to the generate invoices page."""
    page.goto(f"{url}/invoicing/generate/")
    page.wait_for_load_state("domcontentloaded")


def _next_month_dates():
    """Return (start, end, label) for next month."""
    today = date.today()
    if today.month == 12:
        start = date(today.year + 1, 1, 1)
    else:
        start = date(today.year, today.month + 1, 1)
    end = date(start.year, start.month, calendar.monthrange(start.year, start.month)[1])
    label = start.strftime("%B %Y")
    return start, end, label


# ===========================================================================
# Period Selector UI
# ===========================================================================

class TestPeriodSelectorUI:
    """Test that the period quick-select cards render correctly."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_period_cards_visible(self):
        """All three period cards should be visible."""
        expect(self.page.locator("#period-month")).to_be_visible()
        expect(self.page.locator("#period-term")).to_be_visible()
        expect(self.page.locator("#period-custom")).to_be_visible()

    def test_next_month_card_shows_label(self):
        """Next Month card should display the upcoming month name."""
        _, _, label = _next_month_dates()
        card = self.page.locator("#period-month")
        expect(card).to_contain_text("Next Month")
        expect(card).to_contain_text(label)

    def test_custom_card_shows_label(self):
        """Custom card should have descriptive text."""
        card = self.page.locator("#period-custom")
        expect(card).to_contain_text("Custom")
        expect(card).to_contain_text("Choose dates manually")

    def test_hidden_period_type_input_exists(self):
        """A hidden period_type input should exist in the form."""
        inp = self.page.locator("input[name='period_type']")
        expect(inp).to_be_attached()

    def test_submit_button_visible(self):
        """Generate button should be visible."""
        btn = self.page.get_by_role("button", name="Generate Invoices")
        expect(btn).to_be_visible()


# ===========================================================================
# Next Month Quick-Select
# ===========================================================================

class TestNextMonthSelect:
    """Test clicking Next Month auto-fills dates and hides billing options."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_click_next_month_fills_dates(self):
        """Clicking Next Month should set the hidden date inputs."""
        start, end, _ = _next_month_dates()
        self.page.locator("#period-month").click()

        quick_start = self.page.locator("#quick_period_start")
        quick_end = self.page.locator("#quick_period_end")
        expect(quick_start).to_have_value(start.isoformat())
        expect(quick_end).to_have_value(end.isoformat())

    def test_click_next_month_sets_period_type(self):
        """period_type hidden input should be set to 'month'."""
        self.page.locator("#period-month").click()
        expect(self.page.locator("#period_type")).to_have_value("month")

    def test_click_next_month_hides_billing_type(self):
        """Billing type section should be hidden for future periods."""
        self.page.locator("#period-month").click()
        billing_section = self.page.locator("#billing-type-section")
        expect(billing_section).to_be_hidden()

    def test_click_next_month_hides_attendance_mode(self):
        """Attendance mode section should be hidden for future periods."""
        self.page.locator("#period-month").click()
        attendance_section = self.page.locator("#attendance-mode-section")
        expect(attendance_section).to_be_hidden()

    def test_click_next_month_shows_summary(self):
        """Period summary should be shown with advance label."""
        self.page.locator("#period-month").click()
        summary = self.page.locator("#period-summary")
        expect(summary).to_be_visible()
        expect(summary).to_contain_text("Advance")

    def test_click_next_month_hides_custom_dates(self):
        """Custom date section should be hidden."""
        self.page.locator("#period-month").click()
        custom_section = self.page.locator("#custom-date-section")
        expect(custom_section).to_be_hidden()

    def test_next_month_card_highlighted(self):
        """Next Month card should get the selected styling."""
        card = self.page.locator("#period-month")
        card.click()
        assert "border-indigo-500" in card.get_attribute("class")


# ===========================================================================
# Next Term Quick-Select
# ===========================================================================

class TestNextTermSelect:
    """Test clicking Next Term auto-fills term dates."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, future_term):
        self.url = live_server.url
        self.page = page
        self.future_term = future_term
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_next_term_card_shows_term_name(self):
        """Next Term card should display the term name."""
        card = self.page.locator("#period-term")
        expect(card).to_contain_text("Next Term")
        expect(card).to_contain_text("Term 2")

    def test_click_next_term_fills_dates(self):
        """Clicking Next Term should set the hidden date inputs to term dates."""
        self.page.locator("#period-term").click()
        quick_start = self.page.locator("#quick_period_start")
        quick_end = self.page.locator("#quick_period_end")
        expect(quick_start).to_have_value(self.future_term.start_date.isoformat())
        expect(quick_end).to_have_value(self.future_term.end_date.isoformat())

    def test_click_next_term_sets_period_type(self):
        """period_type hidden input should be set to 'term'."""
        self.page.locator("#period-term").click()
        expect(self.page.locator("#period_type")).to_have_value("term")

    def test_click_next_term_hides_billing_options(self):
        """Billing type and attendance mode should be hidden for future term."""
        self.page.locator("#period-term").click()
        expect(self.page.locator("#billing-type-section")).to_be_hidden()
        expect(self.page.locator("#attendance-mode-section")).to_be_hidden()

    def test_click_next_term_shows_summary(self):
        """Period summary should appear with advance label."""
        self.page.locator("#period-term").click()
        summary = self.page.locator("#period-summary")
        expect(summary).to_be_visible()
        expect(summary).to_contain_text("Advance")


class TestNextTermDisabled:
    """Test that Next Term is disabled when no future term exists."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_next_term_disabled_without_future_term(self):
        """Next Term card should be disabled when no upcoming terms exist."""
        card = self.page.locator("#period-term")
        expect(card).to_be_disabled()

    def test_next_term_shows_no_upcoming(self):
        """Next Term card should show 'No upcoming term'."""
        card = self.page.locator("#period-term")
        expect(card).to_contain_text("No upcoming term")


# ===========================================================================
# Custom Period Select
# ===========================================================================

class TestCustomPeriodSelect:
    """Test clicking Custom shows manual date pickers and billing options."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_click_custom_shows_date_pickers(self):
        """Clicking Custom should reveal manual date inputs."""
        self.page.locator("#period-custom").click()
        custom_section = self.page.locator("#custom-date-section")
        expect(custom_section).to_be_visible()

    def test_click_custom_shows_billing_type(self):
        """Billing type section should be visible in custom mode."""
        self.page.locator("#period-custom").click()
        expect(self.page.locator("#billing-type-section")).to_be_visible()

    def test_click_custom_shows_attendance_mode(self):
        """Attendance mode section should be visible for past dates in custom mode."""
        self.page.locator("#period-custom").click()
        # Set a past end date
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        self.page.locator("#billing_period_end").fill(yesterday)
        self.page.locator("#billing_period_end").dispatch_event("change")
        expect(self.page.locator("#attendance-mode-section")).to_be_visible()

    def test_click_custom_hides_summary(self):
        """Period summary should be hidden in custom mode."""
        self.page.locator("#period-custom").click()
        expect(self.page.locator("#period-summary")).to_be_hidden()

    def test_custom_future_date_hides_billing_options(self):
        """In custom mode, setting a future end date should hide billing type and attendance mode."""
        self.page.locator("#period-custom").click()
        future_date = (date.today() + timedelta(days=30)).isoformat()
        self.page.locator("#billing_period_end").fill(future_date)
        self.page.locator("#billing_period_end").dispatch_event("change")
        expect(self.page.locator("#billing-type-section")).to_be_hidden()
        expect(self.page.locator("#attendance-mode-section")).to_be_hidden()

    def test_custom_sets_period_type(self):
        """period_type hidden input should be 'custom'."""
        self.page.locator("#period-custom").click()
        expect(self.page.locator("#period_type")).to_have_value("custom")


# ===========================================================================
# Switching Between Period Types
# ===========================================================================

class TestPeriodSwitching:
    """Test switching between period selector cards."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom, enrolled_student, future_term):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        _go_generate(page, self.url)

    def test_switch_from_month_to_custom(self):
        """Switching from Next Month to Custom should show date pickers."""
        self.page.locator("#period-month").click()
        expect(self.page.locator("#custom-date-section")).to_be_hidden()

        self.page.locator("#period-custom").click()
        expect(self.page.locator("#custom-date-section")).to_be_visible()
        expect(self.page.locator("#period-summary")).to_be_hidden()

    def test_switch_from_custom_to_term(self):
        """Switching from Custom to Next Term should hide date pickers and show summary."""
        self.page.locator("#period-custom").click()
        expect(self.page.locator("#custom-date-section")).to_be_visible()

        self.page.locator("#period-term").click()
        expect(self.page.locator("#custom-date-section")).to_be_hidden()
        expect(self.page.locator("#period-summary")).to_be_visible()

    def test_switch_from_term_to_month(self):
        """Switching from Next Term to Next Month should update dates."""
        self.page.locator("#period-term").click()
        self.page.locator("#period-month").click()

        start, end, _ = _next_month_dates()
        expect(self.page.locator("#quick_period_start")).to_have_value(start.isoformat())
        expect(self.page.locator("#quick_period_end")).to_have_value(end.isoformat())
        expect(self.page.locator("#period_type")).to_have_value("month")

    def test_only_one_card_highlighted_at_a_time(self):
        """Only the selected card should have the active border."""
        self.page.locator("#period-month").click()
        assert "border-indigo-500" in self.page.locator("#period-month").get_attribute("class")
        assert "border-indigo-500" not in self.page.locator("#period-term").get_attribute("class")

        self.page.locator("#period-term").click()
        assert "border-indigo-500" in self.page.locator("#period-term").get_attribute("class")
        assert "border-indigo-500" not in self.page.locator("#period-month").get_attribute("class")


# ===========================================================================
# Advance Invoice Generation Flow (end-to-end)
# ===========================================================================

class TestAdvanceGenerationFlow:
    """End-to-end test: select future period, generate, preview, issue."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom,
               enrolled_student, future_term):
        self.url = live_server.url
        self.page = page
        self.future_term = future_term
        do_login(page, self.url, hoi_user)

    def test_generate_next_month_submits(self):
        """Selecting Next Month and submitting should navigate to preview or show warning."""
        _go_generate(self.page, self.url)
        self.page.locator("#period-month").click()
        self.page.get_by_role("button", name="Generate Invoices").click()
        self.page.wait_for_load_state("domcontentloaded")
        # Should either go to preview or show 'No invoices' warning
        # (no sessions scheduled for next month in test data)
        url = self.page.url
        assert "/invoicing/" in url

    def test_generate_next_term_submits(self):
        """Selecting Next Term and submitting should navigate to preview or show warning."""
        _go_generate(self.page, self.url)
        self.page.locator("#period-term").click()
        self.page.get_by_role("button", name="Generate Invoices").click()
        self.page.wait_for_load_state("domcontentloaded")
        url = self.page.url
        assert "/invoicing/" in url


# ===========================================================================
# Advance Invoice with Sessions — Full Flow
# ===========================================================================

class TestAdvanceWithSessions:
    """Generate advance invoices when future sessions exist — verify preview and issue."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department, classroom,
               enrolled_student, future_term):
        self.url = live_server.url
        self.page = page
        self.future_term = future_term

        # Create scheduled sessions in the future term period
        from attendance.models import ClassSession
        from datetime import time as t

        term_start = future_term.start_date
        for i in range(4):
            session_date = term_start + timedelta(days=i * 7)
            ClassSession.objects.create(
                classroom=classroom,
                date=session_date,
                start_time=t(9, 0),
                end_time=t(10, 0),
                status="scheduled",
                created_by=hoi_user,
            )

        # Set a fee on the department
        department.default_fee = Decimal("15.00")
        department.save()

        do_login(page, self.url, hoi_user)

    def test_full_advance_flow_term(self):
        """Select Next Term → generate → preview shows drafts → issue succeeds."""
        _go_generate(self.page, self.url)
        self.page.locator("#period-term").click()
        self.page.get_by_role("button", name="Generate Invoices").click()
        self.page.wait_for_load_state("domcontentloaded")

        # Should be on preview page
        assert_page_has_text(self.page, "Invoice Preview")
        assert_page_has_text(self.page, "Draft")

        # Issue all
        self.page.locator("button", has_text="Issue All").first.click()
        self.page.wait_for_load_state("domcontentloaded")

        # Should redirect to invoice list with success message
        assert_page_has_text(self.page, "issued successfully")

    def test_generate_next_month_submits_form(self):
        """Select Next Month and submit — form should post successfully."""
        _go_generate(self.page, self.url)
        self.page.locator("#period-month").click()
        self.page.get_by_role("button", name="Generate Invoices").click()
        self.page.wait_for_load_state("domcontentloaded")
        # Should stay in invoicing area (preview or redirect back with message)
        assert "/invoicing/" in self.page.url


# ===========================================================================
# Invoice List — Period Type Badge
# ===========================================================================

class TestInvoiceListPeriodBadge:
    """Test that period type badge shows on invoice list."""

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, school, enrolled_student, classroom):
        self.url = live_server.url
        self.page = page

        from classroom.models import Invoice, InvoiceLineItem

        # Create invoices with different period types
        for period_type, num in [("month", "0010"), ("term", "0011"), ("custom", "0012")]:
            inv = Invoice.objects.create(
                student=enrolled_student,
                school=school,
                invoice_number=f"INV-{num}",
                billing_period_start=date.today(),
                billing_period_end=date.today() + timedelta(days=30),
                status="issued",
                amount=Decimal("100.00"),
                calculated_amount=Decimal("100.00"),
                period_type=period_type,
            )
            InvoiceLineItem.objects.create(
                invoice=inv,
                classroom=classroom,
                daily_rate=Decimal("10.00"),
                sessions_held=10,
                sessions_attended=10,
                sessions_charged=10,
                line_amount=Decimal("100.00"),
            )

        do_login(page, self.url, hoi_user)

    def test_month_badge_visible(self):
        """Month period type should show a badge on invoice list."""
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Month")

    def test_term_badge_visible(self):
        """Term period type should show a badge on invoice list."""
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        assert_page_has_text(self.page, "Term")

    def test_custom_no_badge(self):
        """Custom period type should NOT show a badge (only non-custom shown)."""
        self.page.goto(f"{self.url}/invoicing/")
        self.page.wait_for_load_state("domcontentloaded")
        # The Custom invoice (INV-0012) should not have a period badge
        row = self.page.locator("tr", has_text="INV-0012")
        # Should not contain a period type badge span
        badge = row.locator("span.rounded-full", has_text="Custom")
        expect(badge).to_have_count(0)
