"""
Tests for CPP-240: invoice_recipient_policy controls who receives invoice emails.

Coverage:
  - _resolve_invoice_recipients() pure logic (no DB)
  - _send_invoice_email() gates on policy (mocked send_templated_email)
  - _send_invoice_cancelled_email() gates on policy
  - School.get_effective_settings() cascades invoice_recipient_policy from department
"""
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.invoicing_services import (
    _resolve_invoice_recipients,
    _send_invoice_cancelled_email,
    _send_invoice_email,
)
from classroom.models import (
    ClassRoom, ClassStudent, Department, DepartmentSubject,
    Guardian, Invoice, InvoiceLineItem, ParentStudent,
    School, SchoolStudent, SchoolTeacher, Subject, StudentGuardian,
)


# ---------------------------------------------------------------------------
# Helpers
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


def _make_invoice(school, student, amount=Decimal('100.00')):
    inv = Invoice.objects.create(
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
    return inv


def _make_school_student(school, student):
    return SchoolStudent.objects.create(school=school, student=student)


def _link_parent(school, student, parent):
    return ParentStudent.objects.create(
        school=school, student=student, parent=parent, is_active=True,
    )


# ---------------------------------------------------------------------------
# TestResolveInvoiceRecipients — pure logic, no DB
# ---------------------------------------------------------------------------

class TestResolveInvoiceRecipients(TestCase):
    """_resolve_invoice_recipients() pure logic tests."""

    def _run(self, policy, n_parents=0, n_guardians=0):
        parent_links = [MagicMock() for _ in range(n_parents)]
        guardian_links = [MagicMock() for _ in range(n_guardians)]
        return _resolve_invoice_recipients(policy, parent_links, guardian_links)

    def test_fallback_with_parents(self):
        send_student, send_parents = self._run('parents_fallback_student', n_parents=2)
        self.assertFalse(send_student)
        self.assertTrue(send_parents)

    def test_fallback_no_parents(self):
        send_student, send_parents = self._run('parents_fallback_student', n_parents=0)
        self.assertTrue(send_student)
        self.assertTrue(send_parents)

    def test_parents_only_with_parents(self):
        send_student, send_parents = self._run('parents_only', n_parents=1)
        self.assertFalse(send_student)
        self.assertTrue(send_parents)

    def test_parents_only_no_parents(self):
        # send_to_parents=True but loops produce nothing — no email sent
        send_student, send_parents = self._run('parents_only', n_parents=0)
        self.assertFalse(send_student)
        self.assertTrue(send_parents)

    def test_parents_and_student_with_parents(self):
        send_student, send_parents = self._run('parents_and_student', n_parents=1)
        self.assertTrue(send_student)
        self.assertTrue(send_parents)

    def test_parents_and_student_no_parents(self):
        send_student, send_parents = self._run('parents_and_student', n_parents=0)
        self.assertTrue(send_student)
        self.assertTrue(send_parents)

    def test_student_only_with_parents(self):
        send_student, send_parents = self._run('student_only', n_parents=2)
        self.assertTrue(send_student)
        self.assertFalse(send_parents)

    def test_student_only_no_parents(self):
        send_student, send_parents = self._run('student_only', n_parents=0)
        self.assertTrue(send_student)
        self.assertFalse(send_parents)

    def test_unknown_policy_falls_back_to_default(self):
        # Unrecognised value → parents_fallback_student behaviour
        send_student, send_parents = self._run('totally_unknown_policy', n_parents=1)
        self.assertFalse(send_student)
        self.assertTrue(send_parents)

    def test_guardian_links_count_as_parents(self):
        # No ParentStudent links, but has guardian → student should NOT get fallback email
        send_student, send_parents = self._run(
            'parents_fallback_student', n_parents=0, n_guardians=1,
        )
        self.assertFalse(send_student)
        self.assertTrue(send_parents)


# ---------------------------------------------------------------------------
# TestSendInvoiceEmailPolicy — mocked send, full DB
# ---------------------------------------------------------------------------

SEND_PATH = 'classroom.email_service.send_templated_email'


class TestSendInvoiceEmailPolicy(TestCase):
    """_send_invoice_email() respects invoice_recipient_policy."""

    def setUp(self):
        self.admin = _make_user('irp_admin', role_name='admin')
        self.student = _make_user('irp_student', email='student@example.com')
        self.parent = _make_user('irp_parent', email='parent@example.com')

    def _setup(self, policy):
        school = _make_school(self.admin, f'irp-{policy.replace("_", "-")}', policy=policy)
        _make_school_student(school, self.student)
        inv = _make_invoice(school, self.student)
        return school, inv

    @patch(SEND_PATH)
    def test_default_sends_to_parents_not_student(self, mock_send):
        school, inv = self._setup('parents_fallback_student')
        _link_parent(school, self.student, self.parent)

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('parent@example.com', recipients)
        self.assertNotIn('student@example.com', recipients)

    @patch(SEND_PATH)
    def test_default_fallback_sends_to_student_when_no_parents(self, mock_send):
        school, inv = self._setup('parents_fallback_student')
        # No parent linked

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('student@example.com', recipients)

    @patch(SEND_PATH)
    def test_parents_only_no_email_when_no_parents(self, mock_send):
        school, inv = self._setup('parents_only')
        # No parent linked

        result = _send_invoice_email(inv)

        mock_send.assert_not_called()
        self.assertEqual(result['sent'], [])

    @patch(SEND_PATH)
    def test_parents_and_student_sends_both(self, mock_send):
        school, inv = self._setup('parents_and_student')
        _link_parent(school, self.student, self.parent)

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('student@example.com', recipients)
        self.assertIn('parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_student_only_skips_parents(self, mock_send):
        school, inv = self._setup('student_only')
        _link_parent(school, self.student, self.parent)

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('student@example.com', recipients)
        self.assertNotIn('parent@example.com', recipients)

    @patch(SEND_PATH)
    def test_deduplication_same_email_sent_once(self, mock_send):
        """If a guardian shares the student's email, only one email is sent."""
        school = _make_school(self.admin, 'irp-dedup', policy='parents_and_student')
        _make_school_student(school, self.student)
        # Guardian has the same email as the student — dedup should fire
        guardian = Guardian.objects.create(
            school=school,
            first_name='Same',
            last_name='Email',
            email='student@example.com',
        )
        StudentGuardian.objects.create(student=self.student, guardian=guardian)
        inv = _make_invoice(school, self.student)

        _send_invoice_email(inv)

        emails_sent = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertEqual(emails_sent.count('student@example.com'), 1)


# ---------------------------------------------------------------------------
# TestSendCancelledEmailPolicy
# ---------------------------------------------------------------------------

class TestSendCancelledEmailPolicy(TestCase):
    """_send_invoice_cancelled_email() respects invoice_recipient_policy."""

    def setUp(self):
        self.admin = _make_user('scp_admin', role_name='admin')
        self.student = _make_user('scp_student', email='student@cancel.com')
        self.parent = _make_user('scp_parent', email='parent@cancel.com')

    def _setup(self, policy):
        school = _make_school(self.admin, f'scp-{policy.replace("_", "-")}', policy=policy)
        _make_school_student(school, self.student)
        inv = _make_invoice(school, self.student)
        inv.status = 'cancelled'
        inv.cancelled_at = timezone.now()
        inv.save()
        return school, inv

    @patch(SEND_PATH)
    def test_cancelled_default_sends_to_parents(self, mock_send):
        school, inv = self._setup('parents_fallback_student')
        _link_parent(school, self.student, self.parent)

        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=False)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('parent@cancel.com', recipients)
        self.assertNotIn('student@cancel.com', recipients)

    @patch(SEND_PATH)
    def test_cancelled_student_only(self, mock_send):
        school, inv = self._setup('student_only')
        _link_parent(school, self.student, self.parent)

        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=False)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('student@cancel.com', recipients)
        self.assertNotIn('parent@cancel.com', recipients)

    @patch(SEND_PATH)
    def test_cancelled_parents_and_student(self, mock_send):
        school, inv = self._setup('parents_and_student')
        _link_parent(school, self.student, self.parent)

        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=False)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('student@cancel.com', recipients)
        self.assertIn('parent@cancel.com', recipients)

    @patch(SEND_PATH)
    def test_cancelled_parents_only_no_parents_no_email(self, mock_send):
        school, inv = self._setup('parents_only')
        # No parent linked

        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=False)

        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# TestGetEffectiveSettingsCascade
# ---------------------------------------------------------------------------

class TestGetEffectiveSettingsCascade(TestCase):
    """School.get_effective_settings() cascades invoice_recipient_policy from department."""

    def setUp(self):
        self.admin = _make_user('esc_admin', role_name='admin')

    def test_school_policy_used_when_dept_blank(self):
        school = _make_school(self.admin, 'esc-school-policy', policy='student_only')
        dept = Department.objects.create(
            school=school, name='Dept A', slug='dept-a',
            invoice_recipient_policy='',  # blank → cascade to school
        )
        eff = school.get_effective_settings(department=dept)
        self.assertEqual(eff['invoice_recipient_policy'], 'student_only')

    def test_dept_policy_overrides_school(self):
        school = _make_school(self.admin, 'esc-dept-override', policy='parents_fallback_student')
        dept = Department.objects.create(
            school=school, name='Dept B', slug='dept-b',
            invoice_recipient_policy='parents_and_student',
        )
        eff = school.get_effective_settings(department=dept)
        self.assertEqual(eff['invoice_recipient_policy'], 'parents_and_student')

    def test_no_dept_uses_school_policy(self):
        school = _make_school(self.admin, 'esc-no-dept', policy='parents_only')
        eff = school.get_effective_settings()
        self.assertEqual(eff['invoice_recipient_policy'], 'parents_only')
