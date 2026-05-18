"""
Integration tests for CPP-240: full invoicing flow respects invoice_recipient_policy.

Unlike the unit tests (which mock send_templated_email and test the service helpers
in isolation), these tests exercise the real call chain:

  issue_invoices() → _send_invoice_email()   (mocked at send_templated_email boundary)
  cancel_invoice() → _send_invoice_cancelled_email()

This verifies that the policy is resolved correctly end-to-end through the
higher-level service functions that other parts of the system call.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.invoicing_services import cancel_invoice, issue_invoices
from classroom.models import (
    Department, Guardian, Invoice, ParentStudent,
    School, SchoolStudent, SchoolTeacher, StudentGuardian,
)

SEND_PATH = 'classroom.email_service.send_templated_email'


# ---------------------------------------------------------------------------
# Shared helpers (duplicated from unit test module to keep files independent)
# ---------------------------------------------------------------------------

def _make_user(username, email=None, role_name=None):
    from accounts.models import CustomUser
    u = CustomUser.objects.create_user(
        username=username,
        password='pass',
        email=email or f'{username}@example.com',
        profile_completed=True,
        must_change_password=False,
    )
    if role_name:
        role, _ = Role.objects.get_or_create(
            name=role_name,
            defaults={'display_name': role_name.title()},
        )
        u.roles.add(role)
    return u


def _make_school(admin, slug, policy='parents_fallback_student'):
    school = School.objects.create(
        name=f'School {slug}',
        slug=slug,
        admin=admin,
        is_active=True,
        invoice_due_days=30,
        invoice_recipient_policy=policy,
    )
    plan, _ = InstitutePlan.objects.get_or_create(
        slug=f'plan-{slug}',
        defaults={
            'name': f'Plan {slug}',
            'price': Decimal('0.00'),
            'class_limit': 100,
            'student_limit': 100,
            'invoice_limit_yearly': 1000,
            'extra_invoice_rate': Decimal('0.00'),
        },
    )
    SchoolSubscription.objects.create(
        school=school, plan=plan,
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    return school


def _make_draft_invoice(school, student, amount=Decimal('100.00')):
    return Invoice.objects.create(
        school=school,
        student=student,
        invoice_number=f'DRAFT-{school.slug}-{student.username}',
        amount=amount,
        calculated_amount=amount,
        status='draft',
        billing_period_start=timezone.now().date(),
        billing_period_end=timezone.now().date(),
    )


def _make_issued_invoice(school, student, amount=Decimal('100.00')):
    return Invoice.objects.create(
        school=school,
        student=student,
        invoice_number=f'INV-{school.slug}-{student.username}',
        amount=amount,
        calculated_amount=amount,
        status='issued',
        issued_at=timezone.now(),
        due_date=timezone.now().date(),
        billing_period_start=timezone.now().date(),
        billing_period_end=timezone.now().date(),
    )


def _link_parent(school, student, parent):
    return ParentStudent.objects.create(
        school=school, student=student, parent=parent, is_active=True,
    )


# ---------------------------------------------------------------------------
# TestIssueInvoicesFlow — issue_invoices() respects policy
# ---------------------------------------------------------------------------

class TestIssueInvoicesFlow(TestCase):
    """issue_invoices() calls _send_invoice_email() with the correct routing."""

    def setUp(self):
        self.admin = _make_user('ii_admin', role_name='admin')
        self.student = _make_user('ii_student', email='ii_student@example.com')
        self.parent = _make_user('ii_parent', email='ii_parent@example.com')

    def _setup(self, policy):
        school = _make_school(self.admin, f'ii-{policy.replace("_", "-")}', policy=policy)
        SchoolStudent.objects.create(school=school, student=self.student)
        draft = _make_draft_invoice(school, self.student)
        return school, draft

    @patch(SEND_PATH)
    def test_issue_changes_status_to_issued(self, mock_send):
        """issue_invoices() transitions the invoice from draft → issued."""
        school, draft = self._setup('student_only')
        issue_invoices([draft.id], self.admin)
        draft.refresh_from_db()
        self.assertEqual(draft.status, 'issued')

    @patch(SEND_PATH)
    def test_issue_sets_due_date(self, mock_send):
        """issue_invoices() sets due_date = today + invoice_due_days."""
        school, draft = self._setup('student_only')
        school.invoice_due_days = 14
        school.save(update_fields=['invoice_due_days'])
        issue_invoices([draft.id], self.admin)
        draft.refresh_from_db()
        expected = timezone.now().date() + __import__('datetime').timedelta(days=14)
        self.assertEqual(draft.due_date, expected)

    @patch(SEND_PATH)
    def test_issue_student_only_sends_to_student(self, mock_send):
        """student_only policy → only student receives the issued email."""
        school, draft = self._setup('student_only')
        _link_parent(school, self.student, self.parent)
        issue_invoices([draft.id], self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ii_student@example.com', recipients)
        self.assertNotIn('ii_parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_issue_parents_and_student_sends_both(self, mock_send):
        """parents_and_student policy → both student and parent receive the issued email."""
        school, draft = self._setup('parents_and_student')
        _link_parent(school, self.student, self.parent)
        issue_invoices([draft.id], self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ii_student@example.com', recipients)
        self.assertIn('ii_parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_issue_parents_only_no_parents_sends_nothing(self, mock_send):
        """parents_only + no parents → issue_invoices() sends no email."""
        _, draft = self._setup('parents_only')
        issue_invoices([draft.id], self.admin)
        mock_send.assert_not_called()

    @patch(SEND_PATH)
    def test_issue_fallback_sends_student_when_no_parents(self, mock_send):
        """parents_fallback_student + no parents → student receives fallback email."""
        _, draft = self._setup('parents_fallback_student')
        issue_invoices([draft.id], self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ii_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_issue_multiple_invoices_each_send_respected(self, mock_send):
        """issue_invoices() with 2 drafts → each triggers an email send."""
        school = _make_school(self.admin, 'ii-multi', policy='student_only')
        student2 = _make_user('ii_student2', email='ii_student2@example.com')
        SchoolStudent.objects.create(school=school, student=self.student)
        SchoolStudent.objects.create(school=school, student=student2)
        draft1 = _make_draft_invoice(school, self.student)
        draft2 = _make_draft_invoice(school, student2)

        issue_invoices([draft1.id, draft2.id], self.admin)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ii_student@example.com', recipients)
        self.assertIn('ii_student2@example.com', recipients)


# ---------------------------------------------------------------------------
# TestCancelInvoiceFlow — cancel_invoice() respects policy
# ---------------------------------------------------------------------------

class TestCancelInvoiceFlow(TestCase):
    """cancel_invoice() calls _send_invoice_cancelled_email() with the correct routing."""

    def setUp(self):
        self.admin = _make_user('ci_admin', role_name='admin')
        self.student = _make_user('ci_student', email='ci_student@example.com')
        self.parent = _make_user('ci_parent', email='ci_parent@example.com')

    def _setup(self, policy):
        school = _make_school(self.admin, f'ci-{policy.replace("_", "-")}', policy=policy)
        SchoolStudent.objects.create(school=school, student=self.student)
        inv = _make_issued_invoice(school, self.student)
        return school, inv

    @patch(SEND_PATH)
    def test_cancel_sets_status(self, mock_send):
        """cancel_invoice() changes status to cancelled."""
        _, inv = self._setup('student_only')
        cancel_invoice(inv, reason='Test', cancelled_by=self.admin)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'cancelled')

    @patch(SEND_PATH)
    def test_cancel_student_only_notifies_student(self, mock_send):
        """student_only policy → student gets cancellation email, parent skipped."""
        school, inv = self._setup('student_only')
        _link_parent(school, self.student, self.parent)
        cancel_invoice(inv, reason='Test', cancelled_by=self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ci_student@example.com', recipients)
        self.assertNotIn('ci_parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_cancel_parents_only_no_parents_sends_nothing(self, mock_send):
        """parents_only + no parents → cancel_invoice() sends no email."""
        _, inv = self._setup('parents_only')
        cancel_invoice(inv, reason='No parents', cancelled_by=self.admin)
        mock_send.assert_not_called()

    @patch(SEND_PATH)
    def test_cancel_parents_and_student_notifies_both(self, mock_send):
        """parents_and_student policy → both notified on cancellation."""
        school, inv = self._setup('parents_and_student')
        _link_parent(school, self.student, self.parent)
        cancel_invoice(inv, reason='Test', cancelled_by=self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ci_student@example.com', recipients)
        self.assertIn('ci_parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_cancel_fallback_sends_student_when_no_parents(self, mock_send):
        """parents_fallback_student + no parents → student gets cancellation email."""
        _, inv = self._setup('parents_fallback_student')
        cancel_invoice(inv, reason='Test', cancelled_by=self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ci_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_cancel_records_cancellation_reason(self, mock_send):
        """cancel_invoice() persists the cancellation_reason on the invoice."""
        _, inv = self._setup('student_only')
        cancel_invoice(inv, reason='Non-payment', cancelled_by=self.admin)
        inv.refresh_from_db()
        self.assertEqual(inv.cancellation_reason, 'Non-payment')

    @patch(SEND_PATH)
    def test_cancel_guardian_notified_under_fallback_policy(self, mock_send):
        """Guardian link counts as 'has parents' → student not cc'd under fallback."""
        school, inv = self._setup('parents_fallback_student')
        guardian = Guardian.objects.create(
            school=school, first_name='Ci', last_name='Guard',
            email='ci_guard@example.com',
        )
        school_student = SchoolStudent.objects.get(school=school, student=self.student)
        StudentGuardian.objects.create(student=self.student, guardian=guardian)
        cancel_invoice(inv, reason='Test', cancelled_by=self.admin)
        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('ci_guard@example.com', recipients)
        self.assertNotIn('ci_student@example.com', recipients)


# ---------------------------------------------------------------------------
# TestDeptPolicyInFullFlow — department policy override end-to-end
# ---------------------------------------------------------------------------

class TestDeptPolicyInFullFlow(TestCase):
    """Department-level policy override is respected in issue_invoices() and cancel_invoice()."""

    def setUp(self):
        self.admin = _make_user('dp_admin', role_name='admin')
        self.student = _make_user('dp_student', email='dp_student@example.com')
        self.parent = _make_user('dp_parent', email='dp_parent@example.com')

    @patch(SEND_PATH)
    def test_dept_policy_overrides_school_on_issue(self, mock_send):
        """
        School says parents_fallback_student, dept says student_only.
        Invoice line item belongs to dept's classroom → student_only wins.
        Parent is linked but should NOT receive email.
        """
        from classroom.models import ClassRoom, InvoiceLineItem

        school = _make_school(self.admin, 'dp-issue', policy='parents_fallback_student')
        dept = Department.objects.create(
            school=school, name='DP Dept', slug='dp-dept',
            invoice_recipient_policy='student_only',
        )
        SchoolStudent.objects.create(school=school, student=self.student)
        _link_parent(school, self.student, self.parent)

        classroom = ClassRoom.objects.create(name='DP Class', school=school, department=dept)
        draft = _make_draft_invoice(school, self.student)
        InvoiceLineItem.objects.create(
            invoice=draft, classroom=classroom, department=dept,
            daily_rate=Decimal('10.00'), rate_source='department_default',
            sessions_held=1, sessions_attended=1, sessions_charged=1,
            line_amount=Decimal('10.00'),
        )

        issue_invoices([draft.id], self.admin)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('dp_student@example.com', recipients)
        self.assertNotIn('dp_parent@example.com', recipients)
