"""
A student with no email address of their own must not suppress their parents'
copy of the invoice.

That is the normal case for a young child — the parent is the intended
recipient, and the school's recipient policy usually says so explicitly. The
old code returned at the top of _send_invoice_email the moment the student had
no address, before the policy was consulted, so those invoices reached nobody
and nothing recorded that they had been skipped.
"""
from decimal import Decimal
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from billing.models import InstitutePlan, SchoolSubscription
from classroom.invoicing_services import (
    _send_invoice_email, get_invoice_email_recipients, issue_invoices,
)
from classroom.models import (
    Guardian, Invoice, ParentStudent, School, SchoolStudent, StudentGuardian,
)

SEND = 'classroom.email_service.send_templated_email'


def _user(username, email=None, role=None):
    user = CustomUser.objects.create_user(
        username=username, password='pass', email=email,
        profile_completed=True, must_change_password=False)
    # create_user normalises a None email to ''; force the real NULL so several
    # address-less users can coexist (CustomUser.email is unique).
    CustomUser.objects.filter(pk=user.pk).update(email=email)
    user.refresh_from_db()
    if role:
        obj, _ = Role.objects.get_or_create(
            name=role, defaults={'display_name': role.title()})
        user.roles.add(obj)
    return user


class NoStudentEmailTest(TestCase):
    def setUp(self):
        self.admin = _user('nse_admin', 'nse_admin@example.com', role='admin')

    def _school(self, slug, policy):
        school = School.objects.create(
            name=f'School {slug}', slug=slug, admin=self.admin, is_active=True,
            invoice_due_days=30, invoice_recipient_policy=policy)
        plan, _ = InstitutePlan.objects.get_or_create(
            slug=f'{slug}-plan', defaults={
                'name': 'Plan', 'price': Decimal('0.00'), 'class_limit': 100,
                'student_limit': 100, 'invoice_limit_yearly': 1000,
                'extra_invoice_rate': Decimal('0.00')})
        SchoolSubscription.objects.create(
            school=school, plan=plan, status=SchoolSubscription.STATUS_ACTIVE)
        return school

    def _invoice(self, school, student, number, status='issued'):
        return Invoice.objects.create(
            school=school, student=student, invoice_number=number,
            amount=Decimal('210.00'), calculated_amount=Decimal('210.00'),
            status=status,
            issued_at=timezone.now() if status != 'draft' else None,
            due_date=timezone.now().date(),
            billing_period_start=timezone.now().date(),
            billing_period_end=timezone.now().date())

    def _child_with_parent(self, school, tag):
        child = _user(f'child_{tag}', None)
        SchoolStudent.objects.create(school=school, student=child)
        parent = _user(f'parent_{tag}', f'parent_{tag}@example.com')
        ParentStudent.objects.create(
            school=school, student=child, parent=parent, is_active=True)
        return child, parent

    # -- the regression, across every policy that includes parents ---------

    def test_parent_is_emailed_for_each_parent_inclusive_policy(self):
        for policy in ('parents_fallback_student', 'parents_only',
                       'parents_and_student'):
            with self.subTest(policy=policy):
                tag = policy.replace('_', '')
                school = self._school(f'nse-{tag}', policy)
                child, parent = self._child_with_parent(school, tag)
                invoice = self._invoice(school, child, f'INV-{tag}')

                with patch(SEND, return_value=True) as send:
                    result = _send_invoice_email(invoice)

                sent = [c.kwargs['recipient_email'] for c in send.call_args_list]
                self.assertEqual(sent, [parent.email])
                self.assertFalse(result['skipped_no_email'])

    def test_guardian_contact_is_emailed_when_student_has_no_address(self):
        school = self._school('nse-guardian', 'parents_fallback_student')
        child = _user('nse_g_child', None)
        SchoolStudent.objects.create(school=school, student=child)
        guardian = Guardian.objects.create(
            school=school, first_name='Gran', last_name='Parent',
            email='gran@example.com')
        StudentGuardian.objects.create(student=child, guardian=guardian)
        invoice = self._invoice(school, child, 'INV-guardian')

        with patch(SEND, return_value=True) as send:
            result = _send_invoice_email(invoice)

        self.assertEqual(
            [c.kwargs['recipient_email'] for c in send.call_args_list],
            ['gran@example.com'])
        self.assertFalse(result['skipped_no_email'])

    def test_fallback_reaches_student_when_the_linked_parent_has_no_address(self):
        """A parent link with no email must not swallow the fallback.

        'Has parents' has to mean contactable parents, or the policy falls back
        to nobody and the invoice silently goes nowhere.
        """
        school = self._school('nse-emptyparent', 'parents_fallback_student')
        student = _user('nse_ep_student', 'teen@example.com')
        SchoolStudent.objects.create(school=school, student=student)
        parent = _user('nse_ep_parent', None)
        ParentStudent.objects.create(
            school=school, student=student, parent=parent, is_active=True)
        invoice = self._invoice(school, student, 'INV-emptyparent')

        with patch(SEND, return_value=True) as send:
            result = _send_invoice_email(invoice)

        self.assertEqual(
            [c.kwargs['recipient_email'] for c in send.call_args_list],
            ['teen@example.com'])
        self.assertFalse(result['skipped_no_email'])

    # -- the genuinely unreachable case is reported, not hidden ------------

    def test_no_contact_with_an_address_is_flagged(self):
        school = self._school('nse-nobody', 'parents_fallback_student')
        child = _user('nse_nobody_child', None)
        SchoolStudent.objects.create(school=school, student=child)
        invoice = self._invoice(school, child, 'INV-nobody')

        with patch(SEND, return_value=True) as send:
            result = _send_invoice_email(invoice)

        send.assert_not_called()
        self.assertTrue(result['skipped_no_email'])

    def test_issue_invoices_records_the_skip_on_each_invoice(self):
        """The caller must be able to tell which invoices reached nobody."""
        school = self._school('nse-issue', 'parents_fallback_student')
        reachable, _ = self._child_with_parent(school, 'issue_ok')
        unreachable = _user('nse_issue_none', None)
        SchoolStudent.objects.create(school=school, student=unreachable)

        good = self._invoice(school, reachable, 'INV-issue-ok', status='draft')
        bad = self._invoice(school, unreachable, 'INV-issue-none', status='draft')

        issued = issue_invoices([good.id, bad.id], self.admin)

        by_number = {inv.invoice_number: inv for inv in issued}
        self.assertFalse(
            by_number['INV-issue-ok'].email_result['skipped_no_email'])
        self.assertTrue(
            by_number['INV-issue-none'].email_result['skipped_no_email'])

    # -- recipient resolution -----------------------------------------------

    def test_recipients_are_deduplicated_across_contact_types(self):
        school = self._school('nse-dedup', 'parents_and_student')
        student = _user('nse_dedup_student', 'shared@example.com')
        SchoolStudent.objects.create(school=school, student=student)
        guardian = Guardian.objects.create(
            school=school, first_name='Same', last_name='Address',
            email='SHARED@example.com')
        StudentGuardian.objects.create(student=student, guardian=guardian)
        invoice = self._invoice(school, student, 'INV-dedup')

        recipients, _ = get_invoice_email_recipients(invoice)

        self.assertEqual([r['email'] for r in recipients], ['shared@example.com'])
        self.assertEqual(recipients[0]['kind'], 'student')

    def test_student_only_policy_still_ignores_parents(self):
        school = self._school('nse-studentonly', 'student_only')
        student = _user('nse_so_student', 'so_student@example.com')
        SchoolStudent.objects.create(school=school, student=student)
        parent = _user('nse_so_parent', 'so_parent@example.com')
        ParentStudent.objects.create(
            school=school, student=student, parent=parent, is_active=True)
        invoice = self._invoice(school, student, 'INV-studentonly')

        recipients, _ = get_invoice_email_recipients(invoice)

        self.assertEqual([r['email'] for r in recipients],
                         ['so_student@example.com'])
