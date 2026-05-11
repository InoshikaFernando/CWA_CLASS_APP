"""
Tests for parent invoice payment flow.

Covers:
- _handle_invoice_payment_checkout webhook handler
    - full payment marks invoice paid
    - partial payment marks invoice partially_paid
    - multi-invoice allocation (oldest first)
    - multi-child: each child's invoice paid correctly
    - idempotency: duplicate webhook does not double-pay
    - graceful handling of missing isp_id / missing ISP / missing invoice
    - ISP marked succeeded after processing
- ParentInvoiceCheckoutView
    - redirects to manual payment link when configured
    - returns 400 when no payment link or no outstanding invoices
    - no Stripe sessions created (manual link only)
"""
import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InvoiceStripePayment
from billing.webhook_handlers import _handle_invoice_payment_checkout
from classroom.models import (
    School, Invoice, InvoicePayment, ParentStudent, Currency,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _role(name):
    r, _ = Role.objects.get_or_create(name=name, defaults={'display_name': name})
    return r


def _user(username, role_name):
    u = CustomUser.objects.create_user(
        username=username,
        password='Test@1234!',
        email=f'wlhtestmails+{username}@gmail.com',
    )
    UserRole.objects.create(user=u, role=_role(role_name))
    return u


def _invoice(student, school, amount, status='issued', due_offset_days=0):
    from datetime import date, timedelta
    today = date.today()
    return Invoice.objects.create(
        student=student,
        school=school,
        invoice_number=f'INV-{student.pk}-{Invoice.objects.count() + 1}',
        billing_period_start=today - timedelta(days=30),
        billing_period_end=today,
        due_date=today + timedelta(days=due_offset_days),
        calculated_amount=amount,
        amount=amount,
        status=status,
    )


def _isp(parent, invoice, amount=None):
    """Create a pending InvoiceStripePayment for a single invoice."""
    amt = amount or invoice.amount
    return InvoiceStripePayment.objects.create(
        parent=parent,
        total_charged=amt + Decimal('3.00'),
        amount_applied=amt,
        stripe_fee=Decimal('3.00'),
        invoice_allocations=[{'invoice_id': invoice.pk, 'amount': str(amt)}],
        status=InvoiceStripePayment.STATUS_PENDING,
    )


def _fake_session(isp_id, session_id='cs_test_abc123'):
    return {
        'id': session_id,
        'metadata': {
            'type': 'invoice_payment',
            'isp_id': str(isp_id),
        },
    }


# ---------------------------------------------------------------------------
# Webhook handler tests
# ---------------------------------------------------------------------------

class HandleInvoicePaymentCheckoutTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('inv_admin', 'admin')
        cls.school = School.objects.create(
            name='Test School', slug='inv-test-school', admin=cls.admin,
        )
        cls.parent = _user('inv_parent', 'parent')
        cls.student1 = _user('inv_student1', 'student')
        cls.student2 = _user('inv_student2', 'student')

        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student1, school=cls.school,
        )
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student2, school=cls.school,
        )

    def test_full_payment_marks_invoice_paid(self):
        inv = _invoice(self.student1, self.school, Decimal('120.00'))
        isp = _isp(self.parent, inv)

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')

        payments = InvoicePayment.objects.filter(invoice=inv)
        self.assertEqual(payments.count(), 1)
        self.assertEqual(payments.first().amount, Decimal('120.00'))
        self.assertEqual(payments.first().status, 'confirmed')

    def test_full_payment_marks_isp_succeeded(self):
        inv = _invoice(self.student1, self.school, Decimal('50.00'))
        isp = _isp(self.parent, inv)

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        isp.refresh_from_db()
        self.assertEqual(isp.status, InvoiceStripePayment.STATUS_SUCCEEDED)

    def test_partial_payment_marks_invoice_partially_paid(self):
        inv = _invoice(self.student1, self.school, Decimal('200.00'))
        partial_amount = Decimal('80.00')
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=partial_amount + Decimal('2.62'),
            amount_applied=partial_amount,
            stripe_fee=Decimal('2.62'),
            invoice_allocations=[{'invoice_id': inv.pk, 'amount': str(partial_amount)}],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'partially_paid')
        self.assertEqual(inv.amount_due, Decimal('120.00'))

    def test_idempotency_already_succeeded(self):
        inv = _invoice(self.student1, self.school, Decimal('100.00'))
        isp = _isp(self.parent, inv)
        isp.status = InvoiceStripePayment.STATUS_SUCCEEDED
        isp.save()

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        # No InvoicePayment should be created (ISP was already done)
        self.assertEqual(InvoicePayment.objects.filter(invoice=inv).count(), 0)

    def test_idempotency_same_webhook_twice(self):
        inv = _invoice(self.student1, self.school, Decimal('100.00'))
        isp = _isp(self.parent, inv)
        session = _fake_session(isp.pk, 'cs_dup_test')
        metadata = session['metadata']

        _handle_invoice_payment_checkout(metadata, session)
        _handle_invoice_payment_checkout(metadata, session)  # duplicate

        # get_or_create on bank_transaction_id prevents double-payment
        self.assertEqual(InvoicePayment.objects.filter(invoice=inv).count(), 1)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')

    def test_multi_invoice_allocation_both_paid(self):
        """Payment covering two invoices marks both as paid."""
        from datetime import date, timedelta
        today = date.today()
        inv1 = Invoice.objects.create(
            student=self.student1, school=self.school,
            invoice_number='INV-MULTI-1',
            billing_period_start=today - timedelta(days=60),
            billing_period_end=today - timedelta(days=31),
            due_date=today - timedelta(days=15),  # older
            calculated_amount=Decimal('60.00'), amount=Decimal('60.00'),
            status='issued',
        )
        inv2 = Invoice.objects.create(
            student=self.student1, school=self.school,
            invoice_number='INV-MULTI-2',
            billing_period_start=today - timedelta(days=30),
            billing_period_end=today,
            due_date=today,  # newer
            calculated_amount=Decimal('80.00'), amount=Decimal('80.00'),
            status='issued',
        )
        total = Decimal('140.00')
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=total + Decimal('4.36'),
            amount_applied=total,
            stripe_fee=Decimal('4.36'),
            invoice_allocations=[
                {'invoice_id': inv1.pk, 'amount': '60.00'},
                {'invoice_id': inv2.pk, 'amount': '80.00'},
            ],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        inv1.refresh_from_db()
        inv2.refresh_from_db()
        self.assertEqual(inv1.status, 'paid')
        self.assertEqual(inv2.status, 'paid')

    def test_multi_child_each_invoice_paid(self):
        """Paying all outstanding covers invoices from both children."""
        inv1 = _invoice(self.student1, self.school, Decimal('90.00'))
        inv2 = _invoice(self.student2, self.school, Decimal('110.00'))
        total = Decimal('200.00')
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=total + Decimal('6.10'),
            amount_applied=total,
            stripe_fee=Decimal('6.10'),
            invoice_allocations=[
                {'invoice_id': inv1.pk, 'amount': '90.00'},
                {'invoice_id': inv2.pk, 'amount': '110.00'},
            ],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        inv1.refresh_from_db()
        inv2.refresh_from_db()
        self.assertEqual(inv1.status, 'paid', 'child1 invoice should be paid')
        self.assertEqual(inv2.status, 'paid', 'child2 invoice should be paid')

    def test_missing_isp_id_does_not_crash(self):
        """Webhook with no isp_id logs error and returns without raising."""
        # Should not raise
        _handle_invoice_payment_checkout({'type': 'invoice_payment'}, {'id': 'cs_x'})

    def test_isp_not_found_does_not_crash(self):
        """Non-existent isp_id logs error and returns without raising."""
        _handle_invoice_payment_checkout({'isp_id': '999999'}, {'id': 'cs_x'})

    def test_invoice_not_found_skips_and_continues(self):
        """Deleted invoice in allocations is skipped; remaining allocations still processed."""
        inv = _invoice(self.student1, self.school, Decimal('50.00'))
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal('103.00'),
            amount_applied=Decimal('100.00'),
            stripe_fee=Decimal('3.00'),
            invoice_allocations=[
                {'invoice_id': 99999, 'amount': '50.00'},   # does not exist
                {'invoice_id': inv.pk, 'amount': '50.00'},  # exists
            ],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        _handle_invoice_payment_checkout(
            _fake_session(isp.pk)['metadata'],
            _fake_session(isp.pk),
        )

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')


# ---------------------------------------------------------------------------
# ParentInvoiceCheckoutView tests
# ---------------------------------------------------------------------------

class ParentInvoiceCheckoutViewTests(TestCase):
    """
    The checkout view redirects to the configured manual payment link.
    If no link is configured at any level, it returns 400.
    No Stripe Checkout sessions are created by the view.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('co_admin', 'admin')
        cls.usd, _ = Currency.objects.get_or_create(
            code='USD', defaults={'name': 'US Dollar', 'symbol': '$'},
        )
        cls.school = School.objects.create(
            name='Checkout School', slug='checkout-school', admin=cls.admin,
            default_currency=cls.usd,
        )
        cls.parent = _user('co_parent', 'parent')
        cls.student1 = _user('co_student1', 'student')
        cls.student2 = _user('co_student2', 'student')

        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student1, school=cls.school,
        )
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student2, school=cls.school,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='co_parent', password='Test@1234!')
        self.url = reverse('parent_invoice_pay')
        self.school.stripe_payment_link = ''
        self.school.save(update_fields=['stripe_payment_link'])

    # ------------------------------------------------------------------
    # Error cases
    # ------------------------------------------------------------------

    def test_no_outstanding_invoices_returns_400(self):
        resp = self.client.post(self.url, {'amount': '100.00'})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('error', resp.json())

    def test_no_payment_link_returns_400(self):
        """Outstanding invoices but no payment link configured → 400."""
        _invoice(self.student1, self.school, Decimal('100.00'))
        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not configured', resp.json()['error'])

    def test_unauthenticated_redirects(self):
        anon = Client()
        resp = anon.post(self.url, {'amount': '50.00'})
        self.assertIn(resp.status_code, (302, 403))

    # ------------------------------------------------------------------
    # Payment link redirect
    # ------------------------------------------------------------------

    def test_school_link_returns_checkout_url(self):
        """With a payment link configured, view returns it as checkout_url."""
        self.school.stripe_payment_link = 'https://pay.example.com/school'
        self.school.save(update_fields=['stripe_payment_link'])

        _invoice(self.student1, self.school, Decimal('80.00'))

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.example.com/school')
        self.assertFalse(InvoiceStripePayment.objects.exists())

    def test_multi_child_uses_payment_link(self):
        """Payment link works even when multiple children have invoices."""
        self.school.stripe_payment_link = 'https://pay.example.com/school'
        self.school.save(update_fields=['stripe_payment_link'])

        _invoice(self.student1, self.school, Decimal('80.00'))
        _invoice(self.student2, self.school, Decimal('70.00'))

        session = self.client.session
        session['active_child_id'] = self.student1.pk
        session.save()

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertIn('checkout_url', resp.json())
        self.assertFalse(InvoiceStripePayment.objects.exists())


# ---------------------------------------------------------------------------
# End-to-end: checkout → webhook → invoice paid
# ---------------------------------------------------------------------------

class InvoicePaymentEndToEndTests(TestCase):
    """
    Simulates the webhook-driven payment flow:
    1. ISP created (as it would be via Stripe Checkout or external payment)
    2. Webhook fires with isp_id
    3. Invoice status updated to 'paid'
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('e2e_admin', 'admin')
        cls.usd, _ = Currency.objects.get_or_create(
            code='USD', defaults={'name': 'US Dollar', 'symbol': '$'},
        )
        cls.school = School.objects.create(
            name='E2E School', slug='e2e-school', admin=cls.admin,
            default_currency=cls.usd,
        )
        cls.parent = _user('e2e_parent', 'parent')
        cls.student = _user('e2e_student', 'student')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
        )

    def test_isp_then_webhook_marks_invoice_paid(self):
        """ISP creation + webhook fires → invoice marked paid."""
        inv = _invoice(self.student, self.school, Decimal('150.00'))
        isp = _isp(self.parent, inv)
        self.assertEqual(isp.status, InvoiceStripePayment.STATUS_PENDING)

        session_payload = {
            'id': 'cs_e2e_session',
            'metadata': {
                'type': 'invoice_payment',
                'isp_id': str(isp.pk),
            },
        }
        _handle_invoice_payment_checkout(session_payload['metadata'], session_payload)

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')
        isp.refresh_from_db()
        self.assertEqual(isp.status, InvoiceStripePayment.STATUS_SUCCEEDED)

    def test_webhook_multi_child_marks_both_paid(self):
        """Both children's invoices marked paid after webhook fires."""
        student2 = _user('e2e_student2b', 'student')
        ParentStudent.objects.create(
            parent=self.parent, student=student2, school=self.school,
        )

        inv1 = _invoice(self.student, self.school, Decimal('100.00'))
        inv2 = _invoice(student2, self.school, Decimal('80.00'))
        total = Decimal('180.00')

        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=total + Decimal('5.52'),
            amount_applied=total,
            stripe_fee=Decimal('5.52'),
            invoice_allocations=[
                {'invoice_id': inv1.pk, 'amount': '100.00'},
                {'invoice_id': inv2.pk, 'amount': '80.00'},
            ],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        session_payload = {
            'id': 'cs_mc_session',
            'metadata': {'type': 'invoice_payment', 'isp_id': str(isp.pk)},
        }
        _handle_invoice_payment_checkout(session_payload['metadata'], session_payload)

        inv1.refresh_from_db()
        inv2.refresh_from_db()
        self.assertEqual(inv1.status, 'paid')
        self.assertEqual(inv2.status, 'paid')
