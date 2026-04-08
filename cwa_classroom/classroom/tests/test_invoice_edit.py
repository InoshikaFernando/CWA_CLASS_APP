"""
Tests for draft invoice editing functionality.

Covers: GET/POST edit view, line item add/remove, field updates,
non-draft rejection, role-based access.
"""

import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, DepartmentSubject, Subject, Level,
    ClassRoom, SchoolStudent, SchoolTeacher,
    Invoice, InvoiceLineItem,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='password1!', **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'wlhtestmails+{username}@gmail.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school_with_subscription(admin_user, school_name='Test School'):
    school = School.objects.create(
        name=school_name,
        slug=school_name.lower().replace(' ', '-'),
        admin=admin_user,
        is_active=True,
        invoice_due_days=30,
    )
    plan = InstitutePlan.objects.create(
        name='Test Plan',
        slug='test-plan',
        price=Decimal('0.00'),
        class_limit=100,
        student_limit=100,
        invoice_limit_yearly=1000,
        extra_invoice_rate=Decimal('0.00'),
    )
    SchoolSubscription.objects.create(
        school=school,
        plan=plan,
        status=SchoolSubscription.STATUS_ACTIVE,
    )
    return school


def _create_draft_invoice(school, student, created_by, amount='100.00', notes='',
                          num_lines=1, line_amount=None):
    """Create a draft invoice with line items."""
    amt = Decimal(amount)
    invoice = Invoice.objects.create(
        invoice_number=f'INV-DRAFT-{Invoice.objects.count() + 1}',
        school=school,
        student=student,
        billing_period_start=datetime.date(2026, 1, 1),
        billing_period_end=datetime.date(2026, 1, 31),
        attendance_mode='all_class_days',
        calculated_amount=amt,
        amount=amt,
        status='draft',
        notes=notes,
        created_by=created_by,
    )
    per_line = Decimal(line_amount) if line_amount else amt / num_lines
    for i in range(num_lines):
        InvoiceLineItem.objects.create(
            invoice=invoice,
            classroom=None,
            department=None,
            daily_rate=per_line,
            rate_source='opening_balance',
            sessions_held=0,
            sessions_attended=0,
            sessions_charged=0,
            line_amount=per_line,
        )
    return invoice


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class InvoiceEditViewTests(TestCase):
    """Tests for the InvoiceEditView (GET and POST)."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_user', first_name='Head', last_name='Owner')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school_with_subscription(self.hoi)

        self.student = _create_user('student1', first_name='Test', last_name='Student')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)

        self.invoice = _create_draft_invoice(
            self.school, self.student, self.hoi,
            amount='200.00', num_lines=2, line_amount='100.00',
        )
        self.client.login(username='hoi_user', password='password1!')

    def _url(self, invoice_id=None):
        return reverse('invoice_edit', kwargs={
            'invoice_id': invoice_id or self.invoice.id,
        })

    # --- GET tests ---

    def test_get_edit_page_for_draft(self):
        """GET edit page for a draft invoice returns 200."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit')
        self.assertContains(response, self.invoice.invoice_number)

    def test_get_edit_page_for_issued_invoice_redirects(self):
        """GET edit page for a non-draft invoice redirects with error."""
        self.invoice.status = 'issued'
        self.invoice.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('invoice_detail', kwargs={
            'invoice_id': self.invoice.id,
        }))

    def test_get_edit_page_for_paid_invoice_redirects(self):
        """GET edit page for a paid invoice redirects."""
        self.invoice.status = 'paid'
        self.invoice.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)

    def test_get_edit_page_for_cancelled_invoice_redirects(self):
        """GET edit page for a cancelled invoice redirects."""
        self.invoice.status = 'cancelled'
        self.invoice.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)

    # --- POST save tests ---

    def test_save_updates_line_amounts(self):
        """POST save updates line item amounts and recalculates totals."""
        lines = list(self.invoice.line_items.all())
        data = {
            'action': 'save',
            f'line_amount_{lines[0].id}': '150.00',
            f'line_amount_{lines[1].id}': '75.00',
            'notes': 'Updated notes',
            'due_date': '2026-02-28',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal('225.00'))
        self.assertEqual(self.invoice.calculated_amount, Decimal('225.00'))
        self.assertEqual(self.invoice.notes, 'Updated notes')
        self.assertEqual(self.invoice.due_date, datetime.date(2026, 2, 28))

        lines[0].refresh_from_db()
        self.assertEqual(lines[0].line_amount, Decimal('150.00'))

    def test_save_clears_due_date_when_empty(self):
        """POST save with empty due_date clears the field."""
        self.invoice.due_date = datetime.date(2026, 3, 1)
        self.invoice.save()

        lines = list(self.invoice.line_items.all())
        data = {
            'action': 'save',
            f'line_amount_{lines[0].id}': '100.00',
            f'line_amount_{lines[1].id}': '100.00',
            'notes': '',
            'due_date': '',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)

        self.invoice.refresh_from_db()
        self.assertIsNone(self.invoice.due_date)

    def test_save_invalid_due_date_shows_error(self):
        """POST save with invalid due_date redirects back to edit."""
        lines = list(self.invoice.line_items.all())
        data = {
            'action': 'save',
            f'line_amount_{lines[0].id}': '100.00',
            f'line_amount_{lines[1].id}': '100.00',
            'notes': '',
            'due_date': 'not-a-date',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        # Should redirect back to edit (not detail)
        self.assertRedirects(response, self._url())

    def test_save_on_non_draft_invoice_redirects(self):
        """POST save on a non-draft invoice redirects to detail."""
        self.invoice.status = 'issued'
        self.invoice.save()
        data = {'action': 'save', 'notes': 'Hacked notes', 'due_date': ''}
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('invoice_detail', kwargs={
            'invoice_id': self.invoice.id,
        }))
        # Notes should not have changed
        self.invoice.refresh_from_db()
        self.assertNotEqual(self.invoice.notes, 'Hacked notes')

    # --- Add line item tests ---

    def test_add_line_item(self):
        """POST add_line creates a new line item and recalculates totals."""
        initial_count = self.invoice.line_items.count()
        data = {
            'action': 'add_line',
            'new_description': 'Extra fee',
            'new_amount': '50.00',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, self._url())

        self.assertEqual(self.invoice.line_items.count(), initial_count + 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal('250.00'))
        self.assertIn('Extra fee', self.invoice.notes)

    def test_add_line_item_missing_fields(self):
        """POST add_line with missing fields shows error."""
        data = {
            'action': 'add_line',
            'new_description': '',
            'new_amount': '50.00',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        # Count unchanged
        self.assertEqual(self.invoice.line_items.count(), 2)

    def test_add_line_item_invalid_amount(self):
        """POST add_line with invalid amount shows error."""
        data = {
            'action': 'add_line',
            'new_description': 'Bad fee',
            'new_amount': 'abc',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.invoice.line_items.count(), 2)

    # --- Remove line item tests ---

    def test_remove_line_item(self):
        """POST remove_line removes a line item and recalculates totals."""
        line = self.invoice.line_items.first()
        data = {
            'action': 'remove_line',
            'line_id': str(line.id),
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)

        self.assertEqual(self.invoice.line_items.count(), 1)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.amount, Decimal('100.00'))

    def test_remove_nonexistent_line_item(self):
        """POST remove_line with bad line_id shows error, no change."""
        data = {
            'action': 'remove_line',
            'line_id': '99999',
        }
        response = self.client.post(self._url(), data)
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.invoice.line_items.count(), 2)

    # --- Role access tests ---

    def test_unauthenticated_user_cannot_access(self):
        """Unauthenticated user is redirected to login."""
        self.client.logout()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('login', response.url.lower())

    def test_student_cannot_access_edit(self):
        """Student role cannot access the edit page."""
        student_client = Client()
        student_client.login(username='student1', password='password1!')
        response = student_client.get(self._url())
        # Should be forbidden or redirect (RoleRequiredMixin behaviour)
        self.assertIn(response.status_code, [302, 403])

    def test_accountant_can_access_edit(self):
        """Accountant role can access the edit page for their school."""
        accountant = _create_user('accountant1', first_name='Acc', last_name='User')
        _assign_role(accountant, Role.ACCOUNTANT)
        SchoolTeacher.objects.update_or_create(
            school=self.school, teacher=accountant, is_active=True,
        )
        acc_client = Client()
        acc_client.login(username='accountant1', password='password1!')
        response = acc_client.get(self._url())
        self.assertEqual(response.status_code, 200)


class InvoiceDetailEditButtonTests(TestCase):
    """Tests that the Edit button appears only for draft invoices."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_btn', first_name='Head', last_name='Owner')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school_with_subscription(self.hoi, school_name='Btn School')

        self.student = _create_user('student_btn', first_name='Btn', last_name='Student')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student, is_active=True)

        self.invoice = _create_draft_invoice(self.school, self.student, self.hoi)
        self.client.login(username='hoi_btn', password='password1!')

    def test_edit_button_shown_for_draft(self):
        """Detail page shows Edit Invoice button for draft."""
        url = reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Edit Invoice')
        self.assertContains(response, reverse('invoice_edit', kwargs={
            'invoice_id': self.invoice.id,
        }))

    def test_edit_button_hidden_for_issued(self):
        """Detail page does not show Edit Invoice for issued invoice."""
        self.invoice.status = 'issued'
        self.invoice.save()
        url = reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Edit Invoice')

    def test_edit_button_hidden_for_paid(self):
        """Detail page does not show Edit Invoice for paid invoice."""
        self.invoice.status = 'paid'
        self.invoice.save()
        url = reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Edit Invoice')
