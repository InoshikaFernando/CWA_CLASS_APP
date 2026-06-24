"""
UI automation tests for CPP-242 — Invoice email logging UI.

TestEmailDashboardTransactionalTab     — tab visible, badge on failures
TestTransactionalEmailLogPage          — page loads, filters, empty state, invoice link
TestInvoiceDetailEmailHistoryPanel     — panel visible, sent/failed rows, error message
TestEmailHistoryResendButton           — resend button in panel, not outside
TestEmailLogAccessControl              — unauthenticated redirected, student blocked
"""
import datetime
from decimal import Decimal

import pytest
from playwright.sync_api import Page, expect

from .conftest import do_login, _RUN_ID, TEST_PASSWORD

pytestmark = pytest.mark.django_db(transaction=True)


# ---------------------------------------------------------------------------
# Shared fixture: school with an issued invoice and some EmailLog rows
# ---------------------------------------------------------------------------

@pytest.fixture
def invoice_with_email_logs(db, admin_user, school):
    """
    Creates an issued invoice and writes 2 EmailLog rows against it:
      - one 'sent'  to student
      - one 'failed' to parent (with an error message)
    Returns (invoice, student, sent_log, failed_log).
    """
    from decimal import Decimal
    from django.utils import timezone
    from classroom.models import (
        Department, DepartmentSubject, Subject,
        ClassRoom, ClassStudent, ClassTeacher, SchoolTeacher,
        SchoolStudent, ParentStudent,
        Invoice, InvoiceLineItem, EmailLog,
    )
    from accounts.models import CustomUser, Role
    from accounts.models import UserRole

    def _role(name):
        from accounts.models import Role as R
        r, _ = R.objects.get_or_create(name=name, defaults={'display_name': name})
        return r

    # Dept + subject
    subj, _ = Subject.objects.get_or_create(
        slug=f'maths-log-{_RUN_ID}',
        defaults={'name': f'Maths Log {_RUN_ID}', 'school': school},
    )
    dept = Department.objects.create(
        school=school, name=f'Dept Log {_RUN_ID}',
        slug=f'dept-log-{_RUN_ID}', default_fee=Decimal('20.00'),
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)

    classroom = ClassRoom.objects.create(
        school=school, department=dept,
        name=f'Class Log {_RUN_ID}', day='monday',
        start_time=datetime.time(9, 0), end_time=datetime.time(10, 0),
    )
    ClassTeacher.objects.create(classroom=classroom, teacher=admin_user)

    # Student
    student = CustomUser.objects.create_user(
        username=f'ui_inv_student_{_RUN_ID}',
        password=TEST_PASSWORD,
        email=f'ui_inv_student_{_RUN_ID}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    UserRole.objects.get_or_create(user=student, role=_role(Role.STUDENT))
    ss = SchoolStudent.objects.create(school=school, student=student)
    ClassStudent.objects.create(classroom=classroom, student=student, is_active=True)

    # Parent
    parent = CustomUser.objects.create_user(
        username=f'ui_inv_parent_{_RUN_ID}',
        password=TEST_PASSWORD,
        email=f'ui_inv_parent_{_RUN_ID}@test.local',
        profile_completed=True,
        must_change_password=False,
    )
    UserRole.objects.get_or_create(user=parent, role=_role(Role.PARENT))
    ParentStudent.objects.create(
        parent=parent, student=student, school=school,
        relationship='mother', is_active=True,
    )

    # Invoice
    invoice = Invoice.objects.create(
        invoice_number=f'INV-UI-LOG-{_RUN_ID}',
        school=school, student=student,
        billing_period_start=datetime.date(2026, 4, 1),
        billing_period_end=datetime.date(2026, 4, 30),
        attendance_mode='all_class_days', billing_type='upfront',
        period_type='custom',
        calculated_amount=Decimal('80.00'), amount=Decimal('80.00'),
        status='issued', issued_at=timezone.now(),
        created_by=admin_user, due_date=datetime.date(2026, 5, 30),
    )
    InvoiceLineItem.objects.create(
        invoice=invoice, classroom=classroom, department=dept,
        daily_rate=Decimal('20.00'), rate_source='class_default',
        sessions_held=4, sessions_attended=4, sessions_charged=4,
        line_amount=Decimal('80.00'),
    )

    # EmailLog rows
    sent_log = EmailLog.objects.create(
        school=school, invoice=invoice,
        recipient=student,
        recipient_email=student.email,
        subject=f'Invoice {invoice.invoice_number}',
        notification_type='invoice',
        status='sent',
    )
    failed_log = EmailLog.objects.create(
        school=school, invoice=invoice,
        recipient=parent,
        recipient_email=parent.email,
        subject=f'Invoice {invoice.invoice_number}',
        notification_type='invoice',
        status='failed',
        error_message='Connection refused: SMTP server unreachable',
    )

    return invoice, student, sent_log, failed_log


# ---------------------------------------------------------------------------
# 1. Email Dashboard — Transactional tab
# ---------------------------------------------------------------------------

class TestEmailDashboardTransactionalTab:

    @pytest.mark.django_db(transaction=True)
    def test_transactional_tab_visible(
        self, page: Page, live_server, admin_user, school,
    ):
        """'Transactional Emails' tab link must appear on the email dashboard."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_role('link', name='Transactional Emails')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_campaigns_tab_active_on_dashboard(
        self, page: Page, live_server, admin_user, school,
    ):
        """Campaigns tab should have the active border style on the dashboard page."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/')
        page.wait_for_load_state('domcontentloaded')
        campaigns_tab = page.get_by_role('link', name='Campaigns')
        expect(campaigns_tab).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_failed_badge_shown_when_failures_exist(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        """If there are failed emails, a red badge shows in the Transactional tab."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/')
        page.wait_for_load_state('domcontentloaded')
        badge = page.locator('a:has-text("Transactional Emails") span.bg-red-100')
        expect(badge).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_transactional_tab_navigates_to_log_page(
        self, page: Page, live_server, admin_user, school,
    ):
        """Clicking the Transactional Emails tab navigates to /email/logs/."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/')
        page.wait_for_load_state('domcontentloaded')
        page.get_by_role('link', name='Transactional Emails').click()
        page.wait_for_load_state('domcontentloaded')
        assert '/email/logs/' in page.url


# ---------------------------------------------------------------------------
# 2. Transactional Email Log Page
# ---------------------------------------------------------------------------

class TestTransactionalEmailLogPage:

    @pytest.mark.django_db(transaction=True)
    def test_page_loads_with_table(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        """Log page renders a table with email rows."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.locator('table')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_sent_email_shown_in_table(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, student, sent_log, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text(student.email)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_failed_email_shown_with_error_row(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, failed_log = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text('Connection refused', exact=False)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_filter_by_status_failed(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, student, sent_log, failed_log = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/?status=failed')
        page.wait_for_load_state('domcontentloaded')
        # Failed recipient visible; sent recipient not visible
        expect(page.get_by_text(failed_log.recipient_email)).to_be_visible()
        expect(page.get_by_text(student.email)).not_to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_filter_by_type_invoice(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/?type=invoice')
        page.wait_for_load_state('domcontentloaded')
        # Type filter chip should appear
        expect(page.get_by_text('Type: Invoice')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_invoice_number_links_to_invoice_detail(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        inv_link = page.get_by_role('link', name=invoice.invoice_number).first
        expect(inv_link).to_be_visible()
        inv_link.click()
        page.wait_for_load_state('domcontentloaded')
        assert f'/invoicing/{invoice.id}/' in page.url

    @pytest.mark.django_db(transaction=True)
    def test_empty_state_shown_with_no_results(
        self, page: Page, live_server, admin_user, school,
    ):
        """With no email logs, empty state message is shown."""
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text('No emails found', exact=False)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_search_by_email_filters_results(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, student, sent_log, failed_log = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        search_box = page.locator('input[name="q"]')
        search_box.fill(student.email)
        page.get_by_role('button', name='Filter').click()
        page.wait_for_load_state('domcontentloaded')
        expect(page.locator('tbody').get_by_text(student.email)).to_be_visible()
        # The parent email (failed) should not appear when searching for student email
        expect(page.get_by_text(failed_log.recipient_email)).not_to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_clear_filters_link_shown_when_active(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/?status=failed')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_role('link', name='Clear')).to_be_visible()


# ---------------------------------------------------------------------------
# 3. Invoice Detail — Email History panel
# ---------------------------------------------------------------------------

class TestInvoiceDetailEmailHistoryPanel:

    @pytest.mark.django_db(transaction=True)
    def test_email_history_panel_visible(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text('Email History')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_sent_row_shown_with_sky_dot(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, student, sent_log, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text(student.email).first).to_be_visible()
        # 'Sent' = accepted by Resend, awaiting delivery confirmation → sky badge
        # (emerald is now reserved for 'delivered'). See CPP-343.
        sent_badge = page.locator('.bg-sky-50.text-sky-700', has_text='Sent')
        expect(sent_badge.first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_failed_row_shown_with_red_dot(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, failed_log = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text(failed_log.recipient_email)).to_be_visible()
        failed_badge = page.locator('.bg-red-50.text-red-700', has_text='Failed')
        expect(failed_badge.first).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_error_message_shown_for_failed_row(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, failed_log = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text('Connection refused', exact=False)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_email_count_shown_in_panel_header(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        # Panel header shows "2 emails"
        expect(page.get_by_text('2 emails', exact=False)).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_empty_state_shown_when_no_emails(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        """A draft invoice with no email logs shows the empty state."""
        from classroom.models import Invoice
        from django.utils import timezone

        invoice, _, _, _ = invoice_with_email_logs
        draft = Invoice.objects.create(
            invoice_number=f'INV-UI-DRAFT-{_RUN_ID}',
            school=school, student=invoice.student,
            billing_period_start=datetime.date(2026, 6, 1),
            billing_period_end=datetime.date(2026, 6, 30),
            attendance_mode='all_class_days', billing_type='upfront',
            period_type='custom',
            calculated_amount=Decimal('50.00'), amount=Decimal('50.00'),
            status='draft', created_by=admin_user,
        )
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{draft.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_text('No emails sent for this invoice yet.')).to_be_visible()


# ---------------------------------------------------------------------------
# 4. Resend button lives inside the Email History panel
# ---------------------------------------------------------------------------

class TestEmailHistoryResendButton:

    @pytest.mark.django_db(transaction=True)
    def test_resend_button_visible_for_issued_invoice(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        invoice, _, _, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        expect(page.get_by_role('button', name='Resend Invoice Email')).to_be_visible()

    @pytest.mark.django_db(transaction=True)
    def test_resend_button_inside_email_history_panel(
        self, page: Page, live_server, admin_user, school, invoice_with_email_logs,
    ):
        """Resend button must be inside the Email History card, not a separate card."""
        invoice, _, _, _ = invoice_with_email_logs
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/invoicing/{invoice.id}/')
        page.wait_for_load_state('domcontentloaded')
        email_history_card = page.locator('div.rounded-2xl', has_text='Email History')
        resend_btn = email_history_card.get_by_role('button', name='Resend Invoice Email')
        expect(resend_btn).to_be_visible()


# ---------------------------------------------------------------------------
# 5. Access control
# ---------------------------------------------------------------------------

class TestEmailLogAccessControl:

    @pytest.mark.django_db(transaction=True)
    def test_unauthenticated_redirected_from_log_page(
        self, page: Page, live_server, school,
    ):
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        assert '/accounts/login/' in page.url

    @pytest.mark.django_db(transaction=True)
    def test_student_cannot_access_log_page(
        self, page: Page, live_server, student_user, school,
    ):
        do_login(page, live_server.url, student_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        # Should redirect away — not the log list page
        assert '/email/logs/' not in page.url or page.get_by_text('Email History').count() == 0

    @pytest.mark.django_db(transaction=True)
    def test_hod_admin_can_access_log_page(
        self, page: Page, live_server, admin_user, school,
    ):
        do_login(page, live_server.url, admin_user)
        page.goto(f'{live_server.url}/admin-dashboard/email/logs/')
        page.wait_for_load_state('domcontentloaded')
        assert '/email/logs/' in page.url
        expect(page.get_by_role('link', name='Transactional Emails')).to_be_visible()
