"""
Tests for CPP-240: invoice_recipient_policy controls who receives invoice emails.

Coverage:
  - _resolve_invoice_recipients() pure logic (no DB)
  - _send_invoice_email() gates on policy, return values, edge cases
  - _send_invoice_cancelled_email() gates on policy
  - resend_invoice_email() delegation and guard raises
  - School.get_effective_settings() cascades invoice_recipient_policy from department
"""
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.invoicing_services import (
    _resolve_invoice_recipients,
    _send_invoice_cancelled_email,
    _send_invoice_email,
    resend_invoice_email,
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


# ---------------------------------------------------------------------------
# TestSendInvoiceEmailReturnValues — result dict structure and edge cases
# ---------------------------------------------------------------------------

class TestSendInvoiceEmailReturnValues(TestCase):
    """Edge-case and return-value tests for _send_invoice_email()."""

    def setUp(self):
        self.admin = _make_user('rv_admin', role_name='admin')
        self.student = _make_user('rv_student', email='rv_student@example.com')

    def _setup(self, policy='parents_fallback_student', slug_suffix=''):
        slug = f'rv-{policy.replace("_", "-")}{slug_suffix}'
        school = _make_school(self.admin, slug, policy=policy)
        _make_school_student(school, self.student)
        inv = _make_invoice(school, self.student)
        return school, inv

    @patch(SEND_PATH)
    def test_result_has_required_keys(self, mock_send):
        """Return dict always contains sent, failed, skipped_no_email."""
        _, inv = self._setup(slug_suffix='-keys')
        result = _send_invoice_email(inv)
        self.assertIn('sent', result)
        self.assertIn('failed', result)
        self.assertIn('skipped_no_email', result)

    @patch(SEND_PATH)
    def test_sent_list_populated_on_success(self, mock_send):
        """result['sent'] contains the recipient email when send succeeds."""
        _, inv = self._setup('student_only', slug_suffix='-sent')
        result = _send_invoice_email(inv)
        self.assertIn('rv_student@example.com', result['sent'])
        self.assertFalse(result['skipped_no_email'])

    def test_student_no_email_sets_skipped_flag(self):
        """Student with blank email → skipped_no_email=True, no send attempted."""
        from accounts.models import CustomUser
        no_email_user = CustomUser.objects.create_user(
            username='rv_noemail', password='pass',
            profile_completed=True, must_change_password=False,
        )
        CustomUser.objects.filter(pk=no_email_user.pk).update(email='')
        no_email_user.refresh_from_db()

        school = _make_school(self.admin, 'rv-noemail', policy='student_only')
        SchoolStudent.objects.create(school=school, student=no_email_user)
        inv = Invoice.objects.create(
            school=school, student=no_email_user,
            invoice_number='INV-noemail', amount=Decimal('10.00'),
            calculated_amount=Decimal('10.00'), status='issued',
            issued_at=timezone.now(), due_date=timezone.now().date(),
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date(),
        )
        result = _send_invoice_email(inv)
        self.assertTrue(result['skipped_no_email'])
        self.assertEqual(result['sent'], [])

    @patch(SEND_PATH)
    def test_failed_list_populated_on_exception(self, mock_send):
        """When send_templated_email raises, email goes to result['failed']."""
        mock_send.side_effect = Exception('SMTP connection refused')
        _, inv = self._setup('student_only', slug_suffix='-fail')
        result = _send_invoice_email(inv)
        self.assertIn('rv_student@example.com', result['failed'])
        self.assertEqual(result['sent'], [])

    @patch(SEND_PATH)
    def test_multiple_parents_all_receive_email(self, mock_send):
        """Two active parents both receive an email."""
        parent1 = _make_user('rv_p1', email='parent1@rv.com')
        parent2 = _make_user('rv_p2', email='parent2@rv.com')
        school, inv = self._setup('parents_and_student', slug_suffix='-multi')
        _link_parent(school, self.student, parent1)
        _link_parent(school, self.student, parent2)

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('parent1@rv.com', recipients)
        self.assertIn('parent2@rv.com', recipients)
        self.assertIn('rv_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_guardian_link_receives_email(self, mock_send):
        """StudentGuardian link → guardian email sent, student skipped (fallback policy)."""
        school, inv = self._setup('parents_fallback_student', slug_suffix='-guard')
        guardian = Guardian.objects.create(
            school=school, first_name='G', last_name='G', email='guardian@rv.com',
        )
        StudentGuardian.objects.create(student=self.student, guardian=guardian)

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('guardian@rv.com', recipients)
        self.assertNotIn('rv_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_dedup_is_case_insensitive(self, mock_send):
        """Guardian with UPPERCASE version of student email → only 1 email sent."""
        school, inv = self._setup('parents_and_student', slug_suffix='-cidup')
        guardian = Guardian.objects.create(
            school=school, first_name='Up', last_name='Case',
            email='RV_STUDENT@EXAMPLE.COM',
        )
        StudentGuardian.objects.create(student=self.student, guardian=guardian)

        _send_invoice_email(inv)

        emails_lower = [c.kwargs['recipient_email'].lower() for c in mock_send.call_args_list]
        self.assertEqual(emails_lower.count('rv_student@example.com'), 1)

    @patch(SEND_PATH)
    def test_dept_policy_used_when_line_item_has_dept(self, mock_send):
        """Invoice with line item in a dept that overrides school policy uses dept policy."""
        school = _make_school(self.admin, 'rv-dept-eff', policy='parents_fallback_student')
        _make_school_student(school, self.student)
        dept = Department.objects.create(
            school=school, name='Dept Eff', slug='dept-eff',
            invoice_recipient_policy='student_only',
        )
        parent = _make_user('rv_dept_parent', email='rv_dept_parent@example.com')
        _link_parent(school, self.student, parent)

        inv = _make_invoice(school, self.student)
        # Attach a line item belonging to a classroom in the dept
        classroom = ClassRoom.objects.create(
            name='Dept Eff Class', school=school, department=dept,
        )
        InvoiceLineItem.objects.create(
            invoice=inv, classroom=classroom, department=dept,
            daily_rate=Decimal('10.00'), rate_source='department_default',
            sessions_held=1, sessions_attended=1, sessions_charged=1,
            line_amount=Decimal('10.00'),
        )

        _send_invoice_email(inv)

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        # dept says student_only → student gets email, parent skipped
        self.assertIn('rv_student@example.com', recipients)
        self.assertNotIn('rv_dept_parent@example.com', recipients)


# ---------------------------------------------------------------------------
# TestSendCancelledEmailEdgeCases
# ---------------------------------------------------------------------------

class TestSendCancelledEmailEdgeCases(TestCase):
    """Additional edge cases for _send_invoice_cancelled_email()."""

    def setUp(self):
        self.admin = _make_user('sce_admin', role_name='admin')
        self.student = _make_user('sce_student', email='sce_student@example.com')
        self.parent = _make_user('sce_parent', email='sce_parent@example.com')

    def _setup(self, policy):
        school = _make_school(self.admin, f'sce-{policy.replace("_", "-")}', policy=policy)
        _make_school_student(school, self.student)
        inv = _make_invoice(school, self.student)
        inv.status = 'cancelled'
        inv.cancelled_at = timezone.now()
        inv.save()
        return school, inv

    @patch(SEND_PATH)
    def test_guardian_receives_cancellation_email(self, mock_send):
        """StudentGuardian link → guardian gets cancellation email."""
        school, inv = self._setup('parents_fallback_student')
        guardian = Guardian.objects.create(
            school=school, first_name='C', last_name='G', email='c_guardian@example.com',
        )
        StudentGuardian.objects.create(student=self.student, guardian=guardian)

        _send_invoice_cancelled_email(inv, reason='Test cancel', credit_returned=Decimal('0'))

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('c_guardian@example.com', recipients)
        self.assertNotIn('sce_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_multiple_parents_all_notified_on_cancel(self, mock_send):
        """Two parents both get cancellation email under parents_and_student policy."""
        parent2 = _make_user('sce_parent2', email='sce_parent2@example.com')
        school, inv = self._setup('parents_and_student')
        _link_parent(school, self.student, self.parent)
        _link_parent(school, self.student, parent2)

        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=Decimal('0'))

        recipients = [c.kwargs['recipient_email'] for c in mock_send.call_args_list]
        self.assertIn('sce_parent@example.com', recipients)
        self.assertIn('sce_parent2@example.com', recipients)
        self.assertIn('sce_student@example.com', recipients)

    @patch(SEND_PATH)
    def test_cancelled_parents_only_silent_suppression_no_send(self, mock_send):
        """parents_only + no parents → _send_invoice_cancelled_email sends nothing."""
        _, inv = self._setup('parents_only')
        _send_invoice_cancelled_email(inv, reason='Test', credit_returned=Decimal('0'))
        mock_send.assert_not_called()


# ---------------------------------------------------------------------------
# TestResendInvoiceEmail — guard raises and delegation
# ---------------------------------------------------------------------------

class TestResendInvoiceEmail(TestCase):
    """resend_invoice_email() guard conditions and delegation."""

    def setUp(self):
        self.admin = _make_user('re_admin', role_name='admin')
        self.student = _make_user('re_student', email='re_student@example.com')
        self.school = _make_school(self.admin, 're-school', policy='student_only')
        _make_school_student(self.school, self.student)

    def _make_issued_invoice(self):
        return _make_invoice(self.school, self.student)

    def test_resend_raises_for_cancelled_invoice(self):
        inv = self._make_issued_invoice()
        inv.status = 'cancelled'
        inv.save(update_fields=['status'])
        with self.assertRaises(ValueError):
            resend_invoice_email(inv)

    def test_resend_raises_for_draft_invoice(self):
        inv = self._make_issued_invoice()
        inv.status = 'draft'
        inv.save(update_fields=['status'])
        with self.assertRaises(ValueError):
            resend_invoice_email(inv)

    @patch(SEND_PATH)
    def test_resend_issued_invoice_sends_email(self, mock_send):
        """resend on issued invoice delegates to _send_invoice_email."""
        inv = self._make_issued_invoice()
        result = resend_invoice_email(inv)
        mock_send.assert_called_once()
        self.assertIn('re_student@example.com', result['sent'])
