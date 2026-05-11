"""
Tests for parent invoice Stripe payment feature.
Covers:
  - ParentInvoicesView — combined children, total_outstanding
  - ParentInvoiceCheckoutView — fee calc, allocation, Stripe session creation
  - ParentInvoicePaymentSuccessView — renders correctly
  - ParentBillingView — subscription info
  - _handle_invoice_payment_checkout webhook handler
  - calculate_stripe_fee utility
"""
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import InvoiceStripePayment
from billing.stripe_service import calculate_stripe_fee
from classroom.models import (
    School, SchoolStudent, Department, ParentStudent,
    Invoice, InvoiceLineItem, InvoicePayment,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class InvoicePaymentTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        parent_role, _ = Role.objects.get_or_create(name=Role.PARENT, defaults={'display_name': 'Parent'})
        student_role, _ = Role.objects.get_or_create(name=Role.STUDENT, defaults={'display_name': 'Student'})
        admin_role, _ = Role.objects.get_or_create(name=Role.ADMIN, defaults={'display_name': 'Admin'})

        cls.admin = CustomUser.objects.create_user('inv_admin', 'inv_admin@example.com', 'pass123!')
        cls.admin.roles.add(admin_role)
        cls.school = School.objects.create(name='Pay School', slug='pay-school', admin=cls.admin)

        # Two children for same parent
        cls.child1 = CustomUser.objects.create_user(
            'inv_child1', 'inv_child1@example.com', 'pass123!',
            first_name='Alice', last_name='Smith',
        )
        cls.child1.roles.add(student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.child1)

        cls.child2 = CustomUser.objects.create_user(
            'inv_child2', 'inv_child2@example.com', 'pass123!',
            first_name='Bob', last_name='Smith',
        )
        cls.child2.roles.add(student_role)
        SchoolStudent.objects.create(school=cls.school, student=cls.child2)

        cls.parent = CustomUser.objects.create_user(
            'inv_parent', 'inv_parent@example.com', 'pass123!',
        )
        cls.parent.roles.add(parent_role)
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.child1, school=cls.school, is_active=True,
        )
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.child2, school=cls.school, is_active=True,
        )

        # Unrelated parent — must never see above invoices
        cls.other_parent = CustomUser.objects.create_user(
            'inv_other_parent', 'inv_other@example.com', 'pass123!',
        )
        cls.other_parent.roles.add(parent_role)

    def _make_invoice(self, student, amount, status='issued', due_days=30):
        today = timezone.now().date()
        inv = Invoice.objects.create(
            invoice_number=f'INV-TEST-{Invoice.objects.count() + 1:04d}',
            school=self.school,
            student=student,
            billing_period_start=today,
            billing_period_end=today,
            calculated_amount=amount,
            amount=amount,
            status=status,
            due_date=today + timezone.timedelta(days=due_days),
            created_by=self.admin,
        )
        return inv


# ---------------------------------------------------------------------------
# Utility: calculate_stripe_fee
# ---------------------------------------------------------------------------

class TestCalculateStripeFee(TestCase):

    def test_basic_fee(self):
        fee, total = calculate_stripe_fee(Decimal('100.00'))
        # 100 * 0.029 + 0.30 = 3.20
        self.assertEqual(fee, Decimal('3.20'))
        self.assertEqual(total, Decimal('103.20'))

    def test_zero_amount(self):
        fee, total = calculate_stripe_fee(Decimal('0.00'))
        self.assertEqual(fee, Decimal('0.30'))
        self.assertEqual(total, Decimal('0.30'))

    def test_small_amount(self):
        fee, total = calculate_stripe_fee(Decimal('10.00'))
        # 10 * 0.029 + 0.30 = 0.59
        self.assertEqual(fee, Decimal('0.59'))
        self.assertEqual(total, Decimal('10.59'))

    def test_rounding(self):
        fee, total = calculate_stripe_fee(Decimal('1.00'))
        # 1 * 0.029 + 0.30 = 0.329 → rounds to 0.33
        self.assertEqual(fee, Decimal('0.33'))
        self.assertEqual(total, Decimal('1.33'))

    def test_large_amount(self):
        fee, total = calculate_stripe_fee(Decimal('500.00'))
        # 500 * 0.029 + 0.30 = 14.80
        self.assertEqual(fee, Decimal('14.80'))
        self.assertEqual(total, Decimal('514.80'))


# ---------------------------------------------------------------------------
# ParentInvoicesView — combined children
# ---------------------------------------------------------------------------

class TestParentInvoicesView(InvoicePaymentTestBase):

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.parent)

    def test_shows_invoices_for_all_children(self):
        inv1 = self._make_invoice(self.child1, Decimal('120.00'))
        inv2 = self._make_invoice(self.child2, Decimal('80.00'))
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, inv1.invoice_number)
        self.assertContains(resp, inv2.invoice_number)

    def test_shows_child_name_in_table(self):
        self._make_invoice(self.child1, Decimal('50.00'))
        resp = self.client.get(reverse('parent_invoices'))
        self.assertContains(resp, 'Alice')

    def test_total_outstanding_sum(self):
        self._make_invoice(self.child1, Decimal('100.00'), status='issued')
        self._make_invoice(self.child2, Decimal('60.00'), status='partially_paid')
        self._make_invoice(self.child1, Decimal('40.00'), status='paid')  # paid — not counted
        resp = self.client.get(reverse('parent_invoices'))
        # Only issued + partially_paid count
        self.assertEqual(resp.context['total_outstanding'], Decimal('160.00'))

    def test_paid_invoices_excluded_from_outstanding(self):
        self._make_invoice(self.child1, Decimal('200.00'), status='paid')
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.context['total_outstanding'], Decimal('0.00'))

    def test_pay_banner_hidden_when_nothing_due(self):
        self._make_invoice(self.child1, Decimal('50.00'), status='paid')
        resp = self.client.get(reverse('parent_invoices'))
        self.assertNotContains(resp, 'direct-pay-btn')

    def test_pay_banner_shown_when_outstanding_and_link_configured(self):
        self.school.stripe_payment_link = 'https://pay.example.com'
        self.school.save(update_fields=['stripe_payment_link'])
        self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        resp = self.client.get(reverse('parent_invoices'))
        self.assertContains(resp, 'direct-pay-btn')

    def test_pay_banner_hidden_when_no_payment_link(self):
        """No payment link configured → no Pay Now button even with outstanding."""
        self.school.stripe_payment_link = ''
        self.school.save(update_fields=['stripe_payment_link'])
        self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        resp = self.client.get(reverse('parent_invoices'))
        self.assertNotContains(resp, 'direct-pay-btn')

    def test_isolation_from_other_parents(self):
        """Other parent must not see these invoices."""
        inv = self._make_invoice(self.child1, Decimal('99.00'))
        self.client.force_login(self.other_parent)
        resp = self.client.get(reverse('parent_invoices'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, inv.invoice_number)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse('parent_invoices'))
        self.assertIn(resp.status_code, [302, 403])

    def test_htmx_returns_partial(self):
        self._make_invoice(self.child1, Decimal('30.00'))
        resp = self.client.get(
            reverse('parent_invoices'),
            HTTP_HX_REQUEST='true',
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, 'parent/partials/invoice_table.html')

    def test_status_filter(self):
        self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        self._make_invoice(self.child1, Decimal('70.00'), status='paid')
        resp = self.client.get(reverse('parent_invoices') + '?status=issued')
        invoices = list(resp.context['invoices'])
        self.assertTrue(all(inv.status == 'issued' for inv in invoices))


# ---------------------------------------------------------------------------
# ParentInvoiceCheckoutView
# ---------------------------------------------------------------------------

class TestParentInvoiceCheckoutView(InvoicePaymentTestBase):
    """
    The checkout view redirects to the configured manual payment link.
    If no link is configured, it returns 400.
    """

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.parent)
        self.school.stripe_payment_link = 'https://pay.example.com/school'
        self.school.save(update_fields=['stripe_payment_link'])

    def _post_pay(self, amount=None):
        data = {}
        if amount is not None:
            data['amount'] = str(amount)
        return self.client.post(reverse('parent_invoice_pay'), data)

    def test_returns_payment_link(self):
        self._make_invoice(self.child1, Decimal('100.00'), status='issued')
        resp = self._post_pay()
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['checkout_url'], 'https://pay.example.com/school')

    def test_no_isp_created_for_manual_link(self):
        self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        self._post_pay()
        self.assertFalse(InvoiceStripePayment.objects.filter(parent=self.parent).exists())

    def test_no_payment_link_returns_400(self):
        self.school.stripe_payment_link = ''
        self.school.save(update_fields=['stripe_payment_link'])
        self._make_invoice(self.child1, Decimal('100.00'), status='issued')
        resp = self._post_pay()
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not configured', json.loads(resp.content)['error'])

    def test_no_outstanding_returns_400(self):
        self._make_invoice(self.child1, Decimal('50.00'), status='paid')
        resp = self._post_pay()
        self.assertEqual(resp.status_code, 400)
        data = json.loads(resp.content)
        self.assertIn('error', data)

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.post(reverse('parent_invoice_pay'))
        self.assertIn(resp.status_code, [302, 403])

    def test_other_parent_cannot_pay_these_invoices(self):
        """Other parent has no children so gets 400 not the invoices."""
        self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        self.client.force_login(self.other_parent)
        resp = self.client.post(reverse('parent_invoice_pay'))
        self.assertEqual(resp.status_code, 400)


# ---------------------------------------------------------------------------
# ParentInvoicePaymentSuccessView
# ---------------------------------------------------------------------------

class TestParentInvoicePaymentSuccessView(InvoicePaymentTestBase):

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.parent)

    def test_renders_without_isp(self):
        resp = self.client.get(reverse('parent_invoice_pay_success'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['isp'])

    def test_renders_with_valid_isp(self):
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal('103.20'),
            amount_applied=Decimal('100.00'),
            stripe_fee=Decimal('3.20'),
            status=InvoiceStripePayment.STATUS_PENDING,
        )
        resp = self.client.get(reverse('parent_invoice_pay_success') + f'?isp_id={isp.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['isp'], isp)
        self.assertContains(resp, '100.00')
        self.assertContains(resp, '3.20')

    def test_cannot_see_other_parents_isp(self):
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal('50.00'),
            amount_applied=Decimal('48.00'),
            stripe_fee=Decimal('2.00'),
            status=InvoiceStripePayment.STATUS_PENDING,
        )
        self.client.force_login(self.other_parent)
        resp = self.client.get(reverse('parent_invoice_pay_success') + f'?isp_id={isp.pk}')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['isp'])


# ---------------------------------------------------------------------------
# ParentBillingView
# ---------------------------------------------------------------------------

class TestParentBillingView(InvoicePaymentTestBase):

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.parent)

    def test_renders_no_subscription(self):
        resp = self.client.get(reverse('parent_billing'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['subscription'])
        self.assertContains(resp, 'No active subscription')

    def test_unauthenticated_redirects(self):
        self.client.logout()
        resp = self.client.get(reverse('parent_billing'))
        self.assertIn(resp.status_code, [302, 403])


# ---------------------------------------------------------------------------
# Webhook handler: _handle_invoice_payment_checkout
# ---------------------------------------------------------------------------

class TestHandleInvoicePaymentCheckout(InvoicePaymentTestBase):

    def _make_isp(self, invoices_and_amounts):
        allocations = [
            {'invoice_id': inv.pk, 'amount': str(amt)}
            for inv, amt in invoices_and_amounts
        ]
        total_applied = sum(amt for _, amt in invoices_and_amounts)
        from billing.stripe_service import calculate_stripe_fee
        fee, total = calculate_stripe_fee(total_applied)
        return InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=total,
            amount_applied=total_applied,
            stripe_fee=fee,
            invoice_allocations=allocations,
            status=InvoiceStripePayment.STATUS_PENDING,
        )

    def _fake_session(self, isp):
        return {
            'id': f'cs_fake_{isp.pk}',
            'metadata': {
                'type': 'invoice_payment',
                'isp_id': str(isp.pk),
                'parent_id': str(self.parent.pk),
            },
        }

    def test_creates_invoice_payment_records(self):
        inv = self._make_invoice(self.child1, Decimal('100.00'), status='issued')
        isp = self._make_isp([(inv, Decimal('100.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(self._fake_session(isp)['metadata'], self._fake_session(isp))

        self.assertEqual(InvoicePayment.objects.filter(invoice=inv).count(), 1)
        payment = InvoicePayment.objects.get(invoice=inv)
        self.assertEqual(payment.amount, Decimal('100.00'))
        self.assertEqual(payment.status, 'confirmed')

    def test_marks_invoice_paid_when_fully_covered(self):
        inv = self._make_invoice(self.child1, Decimal('100.00'), status='issued')
        isp = self._make_isp([(inv, Decimal('100.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(self._fake_session(isp)['metadata'], self._fake_session(isp))

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')

    def test_marks_invoice_partially_paid(self):
        inv = self._make_invoice(self.child1, Decimal('200.00'), status='issued')
        isp = self._make_isp([(inv, Decimal('100.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(self._fake_session(isp)['metadata'], self._fake_session(isp))

        inv.refresh_from_db()
        self.assertEqual(inv.status, 'partially_paid')

    def test_marks_isp_succeeded(self):
        inv = self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        isp = self._make_isp([(inv, Decimal('50.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(self._fake_session(isp)['metadata'], self._fake_session(isp))

        isp.refresh_from_db()
        self.assertEqual(isp.status, InvoiceStripePayment.STATUS_SUCCEEDED)

    def test_idempotent_second_call(self):
        """Calling handler twice must not create duplicate InvoicePayment."""
        inv = self._make_invoice(self.child1, Decimal('50.00'), status='issued')
        isp = self._make_isp([(inv, Decimal('50.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        session = self._fake_session(isp)
        _handle_invoice_payment_checkout(session['metadata'], session)
        _handle_invoice_payment_checkout(session['metadata'], session)  # second call

        self.assertEqual(InvoicePayment.objects.filter(invoice=inv).count(), 1)

    def test_multi_invoice_allocation(self):
        inv1 = self._make_invoice(self.child1, Decimal('60.00'), status='issued')
        inv2 = self._make_invoice(self.child2, Decimal('40.00'), status='issued')
        isp = self._make_isp([(inv1, Decimal('60.00')), (inv2, Decimal('40.00'))])
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(self._fake_session(isp)['metadata'], self._fake_session(isp))

        inv1.refresh_from_db()
        inv2.refresh_from_db()
        self.assertEqual(inv1.status, 'paid')
        self.assertEqual(inv2.status, 'paid')

    def test_missing_isp_id_logs_and_returns(self):
        """Should not raise if isp_id missing from metadata."""
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout({}, {'id': 'cs_bad'})  # no exception

    def test_nonexistent_isp_logs_and_returns(self):
        from billing.webhook_handlers import _handle_invoice_payment_checkout
        _handle_invoice_payment_checkout(
            {'isp_id': '99999'},
            {'id': 'cs_bad'},
        )  # no exception
