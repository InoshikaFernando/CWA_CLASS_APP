"""
UI tests for CPP-167 — Stripe Payment Links integration.

Covers:
  - Invoice.get_stripe_payment_link() resolution logic (invoice → dept → school)
  - SchoolSettingsView GET/POST (Payments tab)
  - DepartmentEditView GET/POST (Stripe link field)
  - InvoiceEditView POST (stripe_payment_link saved on draft)
  - InvoiceDetailView GET (resolved link in context) + POST (update any status)
  - ParentInvoiceDetailView GET (Pay Now banner shown/hidden)
  - ParentInvoicesView GET (Pay Now column in list)
"""

import datetime
from decimal import Decimal

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.models import (
    School, Department, DepartmentSubject, Subject,
    SchoolStudent, SchoolTeacher,
    Invoice, InvoiceLineItem,
    ParentStudent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='testpass123', **kwargs):
    return CustomUser.objects.create_user(
        username=username,
        password=password,
        email=kwargs.pop('email', f'{username}@example.com'),
        **kwargs,
    )


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)


def _setup_school(admin_user, school_name='Test School', slug=None):
    slug = slug or school_name.lower().replace(' ', '-')
    school = School.objects.create(
        name=school_name,
        slug=slug,
        admin=admin_user,
        is_active=True,
        invoice_due_days=30,
    )
    plan = InstitutePlan.objects.create(
        name=f'Plan-{slug}',
        slug=f'plan-{slug}',
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


def _create_department(school, name='Mathematics', stripe_payment_link=''):
    subj, _ = Subject.objects.get_or_create(
        slug='maths-test', defaults={'name': 'Maths', 'is_active': True},
    )
    dept = Department.objects.create(
        school=school,
        name=name,
        slug=name.lower().replace(' ', '-'),
        stripe_payment_link=stripe_payment_link,
    )
    DepartmentSubject.objects.create(department=dept, subject=subj)
    return dept


def _create_invoice(school, student, created_by, status='draft',
                    amount='100.00', stripe_payment_link=''):
    amt = Decimal(amount)
    return Invoice.objects.create(
        invoice_number=f'INV-{Invoice.objects.count() + 1:04d}',
        school=school,
        student=student,
        billing_period_start=datetime.date(2026, 1, 1),
        billing_period_end=datetime.date(2026, 1, 31),
        attendance_mode='all_class_days',
        calculated_amount=amt,
        amount=amt,
        status=status,
        stripe_payment_link=stripe_payment_link,
        created_by=created_by,
    )


def _add_line_item(invoice, department=None, line_amount='100.00'):
    InvoiceLineItem.objects.create(
        invoice=invoice,
        department=department,
        classroom=None,
        daily_rate=Decimal(line_amount),
        rate_source='opening_balance',
        sessions_held=0,
        sessions_attended=0,
        sessions_charged=0,
        line_amount=Decimal(line_amount),
    )


# ---------------------------------------------------------------------------
# 1. Invoice.get_stripe_payment_link() resolution logic
# ---------------------------------------------------------------------------

class InvoiceGetStripePaymentLinkTests(TestCase):
    """Unit tests for the fallback resolution chain."""

    def setUp(self):
        self.hoi = _create_user('hoi_res')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school(self.hoi, school_name='Res School', slug='res-school')
        self.student = _create_user('student_res')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)

    def test_invoice_level_link_returned_first(self):
        """Invoice-level link is returned when set, regardless of dept/school."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        dept = _create_department(self.school, stripe_payment_link='https://buy.stripe.com/dept')
        invoice = _create_invoice(
            self.school, self.student, self.hoi,
            stripe_payment_link='https://buy.stripe.com/invoice',
        )
        _add_line_item(invoice, department=dept)

        self.assertEqual(invoice.get_stripe_payment_link(), 'https://buy.stripe.com/invoice')

    def test_department_link_used_when_invoice_has_none(self):
        """Department link is returned when invoice has no link set."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        dept = _create_department(self.school, stripe_payment_link='https://buy.stripe.com/dept')
        invoice = _create_invoice(self.school, self.student, self.hoi)
        _add_line_item(invoice, department=dept)

        self.assertEqual(invoice.get_stripe_payment_link(), 'https://buy.stripe.com/dept')

    def test_school_link_used_as_final_fallback(self):
        """School link is returned when invoice and department have no link."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        dept = _create_department(self.school)  # no dept link
        invoice = _create_invoice(self.school, self.student, self.hoi)
        _add_line_item(invoice, department=dept)

        self.assertEqual(invoice.get_stripe_payment_link(), 'https://buy.stripe.com/school')

    def test_returns_none_when_no_link_anywhere(self):
        """Returns None when no Stripe link is set at any level."""
        invoice = _create_invoice(self.school, self.student, self.hoi)
        _add_line_item(invoice)

        self.assertIsNone(invoice.get_stripe_payment_link())

    def test_department_with_blank_link_falls_back_to_school(self):
        """A department with an empty stripe link does not block fallback to school."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        dept = _create_department(self.school, stripe_payment_link='')
        invoice = _create_invoice(self.school, self.student, self.hoi)
        _add_line_item(invoice, department=dept)

        self.assertEqual(invoice.get_stripe_payment_link(), 'https://buy.stripe.com/school')


# ---------------------------------------------------------------------------
# 2. SchoolSettingsView — Payments tab
# ---------------------------------------------------------------------------

class SchoolSettingsStripeTests(TestCase):
    """Tests for the Stripe Payment Link field in Institute Settings."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_settings')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school(self.hoi, school_name='Settings School', slug='settings-school')
        self.client.login(username='hoi_settings', password='testpass123')

    def _url(self):
        return reverse('admin_school_settings', kwargs={'school_id': self.school.id})

    def test_get_payments_tab_shows_stripe_field(self):
        """GET Payments tab renders the stripe_payment_link input."""
        response = self.client.get(self._url() + '?tab=payments')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'stripe_payment_link')
        self.assertContains(response, 'Stripe Payment Link')

    def test_get_payments_tab_shows_existing_link(self):
        """GET Payments tab pre-fills the existing Stripe link."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/existing'
        self.school.save()
        response = self.client.get(self._url() + '?tab=payments')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://buy.stripe.com/existing')

    def test_post_saves_stripe_payment_link(self):
        """POST with a Stripe link saves it to the school."""
        response = self.client.post(self._url(), {
            'active_tab': 'payments',
            'stripe_payment_link': 'https://buy.stripe.com/new-link',
        })
        self.assertEqual(response.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.stripe_payment_link, 'https://buy.stripe.com/new-link')

    def test_post_clears_stripe_payment_link(self):
        """POST with blank Stripe link clears it."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/existing'
        self.school.save()

        self.client.post(self._url(), {
            'active_tab': 'payments',
            'stripe_payment_link': '',
        })
        self.school.refresh_from_db()
        self.assertEqual(self.school.stripe_payment_link, '')


# ---------------------------------------------------------------------------
# 3. DepartmentEditView — Stripe link field
# ---------------------------------------------------------------------------

class DepartmentEditStripeTests(TestCase):
    """Tests for the Stripe Payment Link field on the department edit form."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_dept')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school(self.hoi, school_name='Dept School', slug='dept-school')
        self.dept = _create_department(self.school)
        self.client.login(username='hoi_dept', password='testpass123')

    def _url(self):
        return reverse('admin_department_edit', kwargs={
            'school_id': self.school.id,
            'dept_id': self.dept.id,
        })

    def test_get_edit_shows_stripe_field(self):
        """GET department edit form shows the Stripe Payment Link field."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'stripe_payment_link')
        self.assertContains(response, 'Stripe Payment Link')

    def test_get_edit_prefills_existing_stripe_link(self):
        """GET department edit pre-fills an existing Stripe link."""
        self.dept.stripe_payment_link = 'https://buy.stripe.com/dept-existing'
        self.dept.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'https://buy.stripe.com/dept-existing')

    def test_post_saves_stripe_payment_link(self):
        """POST saves the Stripe link on the department."""
        response = self.client.post(self._url(), {
            'name': self.dept.name,
            'description': '',
            'stripe_payment_link': 'https://buy.stripe.com/dept-new',
        })
        self.assertEqual(response.status_code, 302)
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.stripe_payment_link, 'https://buy.stripe.com/dept-new')

    def test_post_clears_stripe_payment_link(self):
        """POST with blank Stripe link clears it."""
        self.dept.stripe_payment_link = 'https://buy.stripe.com/dept-existing'
        self.dept.save()

        self.client.post(self._url(), {
            'name': self.dept.name,
            'description': '',
            'stripe_payment_link': '',
        })
        self.dept.refresh_from_db()
        self.assertEqual(self.dept.stripe_payment_link, '')


# ---------------------------------------------------------------------------
# 4. InvoiceEditView — stripe_payment_link saved on draft
# ---------------------------------------------------------------------------

class InvoiceEditStripeTests(TestCase):
    """Tests for the Stripe link field in the draft invoice edit form."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_inv_edit')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school(self.hoi, school_name='Edit School', slug='edit-school')
        self.student = _create_user('student_inv_edit')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.invoice = _create_invoice(self.school, self.student, self.hoi)
        _add_line_item(self.invoice)
        self.client.login(username='hoi_inv_edit', password='testpass123')

    def _url(self):
        return reverse('invoice_edit', kwargs={'invoice_id': self.invoice.id})

    def test_get_shows_stripe_field(self):
        """GET invoice edit shows the Stripe Payment Link input."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'stripe_payment_link')

    def test_post_save_persists_stripe_link(self):
        """POST save stores the stripe_payment_link on the invoice."""
        line = self.invoice.line_items.first()
        response = self.client.post(self._url(), {
            'action': 'save',
            f'line_amount_{line.id}': '100.00',
            'notes': '',
            'due_date': '',
            'stripe_payment_link': 'https://buy.stripe.com/inv-override',
        })
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.stripe_payment_link, 'https://buy.stripe.com/inv-override')

    def test_post_save_clears_stripe_link(self):
        """POST save with blank stripe link clears it."""
        self.invoice.stripe_payment_link = 'https://buy.stripe.com/old'
        self.invoice.save()
        line = self.invoice.line_items.first()

        self.client.post(self._url(), {
            'action': 'save',
            f'line_amount_{line.id}': '100.00',
            'notes': '',
            'due_date': '',
            'stripe_payment_link': '',
        })
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.stripe_payment_link, '')


# ---------------------------------------------------------------------------
# 5. InvoiceDetailView — GET context + POST update (any status)
# ---------------------------------------------------------------------------

class InvoiceDetailStripeTests(TestCase):
    """Tests for the Stripe link card on the HoI invoice detail page."""

    def setUp(self):
        self.client = Client()
        self.hoi = _create_user('hoi_inv_detail')
        _assign_role(self.hoi, Role.HEAD_OF_INSTITUTE)
        self.school = _setup_school(self.hoi, school_name='Detail School', slug='detail-school')
        self.student = _create_user('student_inv_detail')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)
        self.invoice = _create_invoice(
            self.school, self.student, self.hoi, status='issued',
        )
        _add_line_item(self.invoice)
        self.client.login(username='hoi_inv_detail', password='testpass123')

    def _url(self):
        return reverse('invoice_detail', kwargs={'invoice_id': self.invoice.id})

    def test_get_passes_resolved_stripe_link_to_context(self):
        """GET passes resolved_stripe_link in template context."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['resolved_stripe_link'],
            'https://buy.stripe.com/school',
        )

    def test_get_resolved_link_is_none_when_not_configured(self):
        """GET passes None when no Stripe link is configured anywhere."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['resolved_stripe_link'])

    def test_post_updates_stripe_link_on_issued_invoice(self):
        """POST updates stripe_payment_link on an issued invoice."""
        response = self.client.post(self._url(), {
            'stripe_payment_link': 'https://buy.stripe.com/issued-override',
        })
        self.assertEqual(response.status_code, 302)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.stripe_payment_link, 'https://buy.stripe.com/issued-override')

    def test_post_clears_stripe_link(self):
        """POST with blank value clears the invoice-level link."""
        self.invoice.stripe_payment_link = 'https://buy.stripe.com/old'
        self.invoice.save()

        self.client.post(self._url(), {'stripe_payment_link': ''})
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.stripe_payment_link, '')

    def test_post_redirects_back_to_detail(self):
        """POST redirects back to the invoice detail page."""
        response = self.client.post(self._url(), {
            'stripe_payment_link': 'https://buy.stripe.com/redir',
        })
        self.assertRedirects(response, self._url())


# ---------------------------------------------------------------------------
# 6. ParentInvoiceDetailView — Pay Now banner
# ---------------------------------------------------------------------------

class ParentInvoiceDetailStripeTests(TestCase):
    """Tests for the Pay Now banner on the parent invoice detail page."""

    def setUp(self):
        self.client = Client()
        admin = _create_user('admin_parent_detail')
        _assign_role(admin, Role.ADMIN)
        self.school = _setup_school(admin, school_name='Parent Detail School', slug='parent-detail-school')

        self.student = _create_user('student_parent_detail')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)

        self.parent = _create_user('parent_detail')
        _assign_role(self.parent, Role.PARENT)
        ParentStudent.objects.create(
            parent=self.parent, student=self.student,
            school=self.school, relationship='mother',
        )

        self.invoice = _create_invoice(
            self.school, self.student, admin, status='issued', amount='120.00',
        )
        _add_line_item(self.invoice, line_amount='120.00')

        self.client.login(username='parent_detail', password='testpass123')

    def _url(self):
        return reverse('parent_invoice_detail', kwargs={'invoice_id': self.invoice.id})

    def test_pay_now_banner_shown_when_link_set_and_amount_due(self):
        """Pay Now banner visible when stripe link resolves and amount_due > 0."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/pay'
        self.school.save()
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pay Now')
        self.assertContains(response, 'https://buy.stripe.com/pay')

    def test_pay_now_banner_hidden_when_no_stripe_link(self):
        """Pay Now banner absent when no Stripe link is configured."""
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Pay Now')

    def test_pay_now_banner_hidden_when_invoice_fully_paid(self):
        """Pay Now banner absent when amount_due == 0 (fully paid)."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/pay'
        self.school.save()
        self.invoice.status = 'paid'
        self.invoice.amount = Decimal('0.00')
        self.invoice.calculated_amount = Decimal('0.00')
        self.invoice.save()

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Pay Now')

    def test_stripe_link_in_context(self):
        """stripe_payment_link is passed in template context."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/ctx'
        self.school.save()
        response = self.client.get(self._url())
        self.assertEqual(response.context['stripe_payment_link'], 'https://buy.stripe.com/ctx')

    def test_invoice_level_link_overrides_school_link(self):
        """Invoice-level Stripe link takes priority over school-level in Pay Now banner."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/school'
        self.school.save()
        self.invoice.stripe_payment_link = 'https://buy.stripe.com/invoice-specific'
        self.invoice.save()

        response = self.client.get(self._url())
        self.assertContains(response, 'https://buy.stripe.com/invoice-specific')
        self.assertNotContains(response, 'https://buy.stripe.com/school')


# ---------------------------------------------------------------------------
# 7. ParentInvoicesView — Pay Now column in list
# ---------------------------------------------------------------------------

class ParentInvoicesListStripeTests(TestCase):
    """Tests for the Pay Now column on the parent invoices list page."""

    def setUp(self):
        self.client = Client()
        admin = _create_user('admin_parent_list')
        _assign_role(admin, Role.ADMIN)
        self.school = _setup_school(admin, school_name='Parent List School', slug='parent-list-school')

        self.student = _create_user('student_parent_list')
        _assign_role(self.student, Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=self.student)

        self.parent = _create_user('parent_list')
        _assign_role(self.parent, Role.PARENT)
        ParentStudent.objects.create(
            parent=self.parent, student=self.student,
            school=self.school, relationship='father',
        )

        self.client.login(username='parent_list', password='testpass123')

    def _url(self):
        return reverse('parent_invoices')

    def _make_invoice(self, status='issued', amount='100.00'):
        inv = _create_invoice(self.school, self.student, self.student, status=status, amount=amount)
        _add_line_item(inv, line_amount=amount)
        return inv

    def test_pay_now_appears_for_issued_invoice_with_link(self):
        """Pay Now button shown for an issued invoice when school has a Stripe link."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/list-pay'
        self.school.save()
        self._make_invoice(status='issued')

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Pay Now')
        self.assertContains(response, 'https://buy.stripe.com/list-pay')

    def test_pay_now_appears_for_partially_paid_invoice(self):
        """Pay Now button shown for a partially_paid invoice with a Stripe link."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/partial'
        self.school.save()
        self._make_invoice(status='partially_paid')

        response = self.client.get(self._url())
        self.assertContains(response, 'Pay Now')

    def test_pay_now_absent_for_paid_invoice(self):
        """Pay Now button not shown for a fully paid invoice."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/paid'
        self.school.save()
        self._make_invoice(status='paid')

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Pay Now')

    def test_pay_now_absent_when_no_stripe_link(self):
        """Pay Now button absent when no Stripe link is configured."""
        self._make_invoice(status='issued')
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Pay Now')

    def test_resolved_stripe_link_annotated_on_invoices(self):
        """View annotates resolved_stripe_link on each invoice object."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/annotate'
        self.school.save()
        inv = self._make_invoice(status='issued')

        response = self.client.get(self._url())
        self.assertEqual(response.status_code, 200)
        invoices = list(response.context['invoices'])
        target = next(i for i in invoices if i.id == inv.id)
        self.assertEqual(target.resolved_stripe_link, 'https://buy.stripe.com/annotate')

    def test_paid_invoice_has_no_resolved_stripe_link_annotation(self):
        """Paid invoices have resolved_stripe_link set to None."""
        self.school.stripe_payment_link = 'https://buy.stripe.com/skip'
        self.school.save()
        inv = self._make_invoice(status='paid')

        response = self.client.get(self._url())
        invoices = list(response.context['invoices'])
        target = next(i for i in invoices if i.id == inv.id)
        self.assertIsNone(target.resolved_stripe_link)
