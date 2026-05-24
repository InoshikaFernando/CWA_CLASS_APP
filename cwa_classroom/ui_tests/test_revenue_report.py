"""
UI tests for CPP-296: Revenue Report page.

Tests cover:
- HoI can access the report and see the page structure
- Filters (student, status, date range) narrow results
- Summary totals are visible and update with data
- Empty state displayed when no invoices match
- Sidebar "Revenue Report" link navigates correctly
- Teacher is denied access
"""

import pytest
from datetime import date
from decimal import Decimal
from playwright.sync_api import expect

from .conftest import do_login, _make_user, _RUN_ID

pytestmark = pytest.mark.reports


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_invoice(school, student, created_by, amount='100.00', status='issued',
                    start=None, end=None):
    from classroom.models import Invoice

    start = start or date(2026, 4, 1)
    end = end or date(2026, 4, 30)
    import uuid
    inv_num = f'INV-UI-{uuid.uuid4().hex[:8]}'
    return Invoice.objects.create(
        invoice_number=inv_num,
        school=school,
        student=student,
        billing_period_start=start,
        billing_period_end=end,
        attendance_mode='all_class_days',
        calculated_amount=Decimal(amount),
        amount=Decimal(amount),
        status=status,
        created_by=created_by,
    )


def _create_payment(invoice, amount='50.00', method='bank_transfer'):
    from classroom.models import InvoicePayment

    return InvoicePayment.objects.create(
        invoice=invoice,
        student=invoice.student,
        school=invoice.school,
        amount=Decimal(amount),
        payment_date=date(2026, 4, 15),
        payment_method=method,
        status='confirmed',
    )


def _enrol_student(school, username='rv_ui_stu'):
    from accounts.models import Role
    from classroom.models import SchoolStudent

    stu = _make_user(f'{username}_{_RUN_ID}', Role.STUDENT)
    SchoolStudent.objects.get_or_create(school=school, student=stu)
    return stu


# ---------------------------------------------------------------------------
# HoI — core access and structure
# ---------------------------------------------------------------------------

class TestHoiRevenueReport:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup):
        self.url = live_server.url
        self.page = page
        self.school = hoi_school_setup
        self.hoi = hoi_user
        do_login(page, self.url, hoi_user)

    def test_hoi_can_access_revenue_report(self):
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.get_by_role('heading', name='Revenue Report')).to_be_visible()

    def test_filters_visible(self):
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.locator('select[name="student_id"]')).to_be_visible()
        expect(self.page.locator('select[name="status"]')).to_be_visible()
        expect(self.page.locator('select[name="payment_method"]')).to_be_visible()
        expect(self.page.locator('input[name="date_from"]')).to_be_visible()
        expect(self.page.locator('input[name="date_to"]')).to_be_visible()

    def test_summary_totals_visible_with_data(self):
        stu = _enrol_student(self.school, 'rv_tot_stu')
        inv = _create_invoice(self.school, stu, self.hoi, amount='200.00', status='issued')
        _create_payment(inv, amount='80.00')
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.get_by_text('Total Invoiced')).to_be_visible()
        expect(self.page.get_by_text('Total Paid')).to_be_visible()
        expect(self.page.get_by_text('Outstanding')).to_be_visible()
        expect(self.page.get_by_text('$200.00').first).to_be_visible()

    def test_filter_by_status(self):
        stu = _enrol_student(self.school, 'rv_filt_stu')
        _create_invoice(self.school, stu, self.hoi, status='paid')
        _create_invoice(self.school, stu, self.hoi, status='issued')
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        self.page.select_option('select[name="status"]', 'paid')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.get_by_text('1 invoice found')).to_be_visible()

    def test_empty_state(self):
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page.get_by_text('No invoices match')).to_be_visible()

    def test_reset_clears_filters(self):
        self.page.goto(f'{self.url}/reports/revenue/?status=paid')
        self.page.wait_for_load_state('domcontentloaded')
        self.page.get_by_role('link', name='Reset', exact=True).click()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page).to_have_url(f'{self.url}/reports/revenue/')


# ---------------------------------------------------------------------------
# Sidebar link
# ---------------------------------------------------------------------------

class TestRevenueSidebarLink:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, hoi_user, hoi_school_setup, department):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, hoi_user)
        page.goto(f'{self.url}/dashboard/')
        page.wait_for_load_state('domcontentloaded')

    def test_sidebar_revenue_report_link_navigates(self):
        self.page.get_by_role('button', name='Reports').click()
        self.page.wait_for_timeout(300)
        self.page.get_by_role('link', name='Revenue Report').click()
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page).to_have_url(f'{self.url}/reports/revenue/')


# ---------------------------------------------------------------------------
# Access denied — teacher
# ---------------------------------------------------------------------------

class TestTeacherDeniedRevenue:

    @pytest.fixture(autouse=True)
    def _setup(self, live_server, page, teacher_user):
        self.url = live_server.url
        self.page = page
        do_login(page, self.url, teacher_user)

    def test_teacher_cannot_access_revenue_report(self):
        self.page.goto(f'{self.url}/reports/revenue/')
        self.page.wait_for_load_state('domcontentloaded')
        expect(self.page).not_to_have_url(f'{self.url}/reports/revenue/')
