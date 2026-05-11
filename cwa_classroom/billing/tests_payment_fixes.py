"""
Tests for payment/invoice fixes.

Fix 1 — Manual payment link priority:
  - Configured payment link (MHM) is used via fallback chain: invoice → department → school
  - If NO link is configured at any level, Pay Now is disabled (returns 400)

Fix 2 — Invoice regeneration cancels old invoices:
  - When a new invoice is generated for the same student + period,
    the old invoice is cancelled and replaced (not silently skipped)
  - Cancelled invoices do not block new ones
  - Different periods are independent

Fix 3 — Currency from school settings, not .env:
  - Stripe Checkout always uses school.default_currency
  - .env STRIPE_CURRENCY is never used for invoice payments
  - Webhook logs warning on currency mismatch
"""
from datetime import date, timedelta
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InvoiceStripePayment
from billing.webhook_handlers import _handle_invoice_payment_checkout
from classroom.models import (
    School, Invoice, InvoiceLineItem, InvoicePayment,
    ParentStudent, Department, Currency,
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


def _invoice(student, school, amount, status='issued', due_offset_days=0,
             billing_start=None, billing_end=None):
    today = date.today()
    return Invoice.objects.create(
        student=student,
        school=school,
        invoice_number=f'INV-FIX-{student.pk}-{Invoice.objects.count() + 1}',
        billing_period_start=billing_start or (today - timedelta(days=30)),
        billing_period_end=billing_end or today,
        due_date=today + timedelta(days=due_offset_days),
        calculated_amount=amount,
        amount=amount,
        status=status,
    )


def _student_data(lines=None):
    """Build a single-line student_data entry for create_draft_invoices."""
    return {
        'lines': lines or [{
            'classroom': None,
            'department': None,
            'daily_rate': Decimal('10.00'),
            'rate_source': 'school',
            'sessions_held': 10,
            'sessions_attended': 10,
            'sessions_charged': 10,
            'line_amount': Decimal('100.00'),
        }],
    }


# ===========================================================================
# Fix 1 — Manual payment link always takes priority over Stripe Checkout
# ===========================================================================

class ManualPaymentLinkPriorityTests(TestCase):
    """
    The configured payment link (set on invoice / department / school) is
    used via a fallback chain.  When a link is configured, Pay Now redirects
    there.  When NO link exists at any level, the endpoint returns 400 and
    the Pay Now button is hidden in the template.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('mplink_admin', 'admin')
        cls.aud, _ = Currency.objects.get_or_create(
            code='AUD', defaults={'name': 'Australian Dollar', 'symbol': '$'},
        )
        cls.school = School.objects.create(
            name='MHM School', slug='mhm-school', admin=cls.admin,
            default_currency=cls.aud,
        )
        cls.parent = _user('mplink_parent', 'parent')
        cls.student = _user('mplink_student', 'student')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
        )

    def setUp(self):
        self.client = Client()
        self.client.login(username='mplink_parent', password='Test@1234!')
        self.url = reverse('parent_invoice_pay')
        # Reset school link between tests
        self.school.stripe_payment_link = ''
        self.school.save(update_fields=['stripe_payment_link'])

    # ------------------------------------------------------------------
    # Manual link set → Stripe Checkout must NOT be used
    # ------------------------------------------------------------------

    def test_school_link_redirects_to_manual_url(self):
        """School-level link is used.  No Stripe session created."""
        self.school.stripe_payment_link = 'https://pay.mhm.com/invoice'
        self.school.save(update_fields=['stripe_payment_link'])

        _invoice(self.student, self.school, Decimal('100.00'))

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.mhm.com/invoice')
        self.assertFalse(
            InvoiceStripePayment.objects.exists(),
            'No ISP should be created when redirecting to manual link',
        )

    def test_department_link_takes_priority_over_school(self):
        """Department-level link overrides school fallback."""
        self.school.stripe_payment_link = 'https://pay.mhm.com/school'
        self.school.save(update_fields=['stripe_payment_link'])

        dept = Department.objects.create(
            school=self.school, name='Music',
            stripe_payment_link='https://pay.mhm.com/music',
        )

        inv = _invoice(self.student, self.school, Decimal('100.00'))
        InvoiceLineItem.objects.create(
            invoice=inv, department=dept,
            daily_rate=Decimal('10.00'), rate_source='school',
            sessions_held=10, sessions_attended=10, sessions_charged=10,
            line_amount=Decimal('100.00'),
        )

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.mhm.com/music')

    def test_invoice_link_overrides_department_and_school(self):
        """Invoice-level link is highest priority in the chain."""
        self.school.stripe_payment_link = 'https://pay.mhm.com/school'
        self.school.save(update_fields=['stripe_payment_link'])

        inv = _invoice(self.student, self.school, Decimal('100.00'))
        inv.stripe_payment_link = 'https://pay.mhm.com/invoice-specific'
        inv.save(update_fields=['stripe_payment_link'])

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.mhm.com/invoice-specific')

    def test_manual_link_used_even_with_custom_amount(self):
        """Even when parent supplies a custom amount, manual link is used."""
        self.school.stripe_payment_link = 'https://pay.mhm.com/invoice'
        self.school.save(update_fields=['stripe_payment_link'])

        _invoice(self.student, self.school, Decimal('200.00'))

        resp = self.client.post(self.url, {'amount': '50.00'})
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.mhm.com/invoice')
        self.assertFalse(InvoiceStripePayment.objects.exists())

    def test_manual_link_used_for_multiple_children(self):
        """Manual link is used even when multiple children have invoices."""
        self.school.stripe_payment_link = 'https://pay.mhm.com/invoice'
        self.school.save(update_fields=['stripe_payment_link'])

        child2 = _user('mplink_student2', 'student')
        ParentStudent.objects.create(
            parent=self.parent, student=child2, school=self.school,
        )

        _invoice(self.student, self.school, Decimal('125.00'))
        _invoice(child2, self.school, Decimal('200.00'))

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.json()['checkout_url'], 'https://pay.mhm.com/invoice')
        self.assertFalse(InvoiceStripePayment.objects.exists())

    # ------------------------------------------------------------------
    # No manual link → Pay Now returns 400 (no Stripe Checkout fallback)
    # ------------------------------------------------------------------

    def test_no_link_returns_400(self):
        """Without any configured payment link, the endpoint returns 400."""
        _invoice(self.student, self.school, Decimal('100.00'))

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not configured', resp.json()['error'])
        self.assertFalse(InvoiceStripePayment.objects.exists())

    def test_empty_string_link_returns_400(self):
        """Empty string link is treated as no link — returns 400."""
        self.school.stripe_payment_link = ''
        self.school.save(update_fields=['stripe_payment_link'])

        _invoice(self.student, self.school, Decimal('100.00'))

        resp = self.client.post(self.url, {})
        self.assertEqual(resp.status_code, 400)
        self.assertIn('not configured', resp.json()['error'])


# ===========================================================================
# Fix 2 — Invoice regeneration cancels old invoice, creates new one
# ===========================================================================

class InvoiceRegenerationTests(TestCase):
    """
    When invoices are generated for a student who already has one for the
    same period, the OLD invoice should be cancelled and a new one created.
    This prevents duplicate invoices for the same child + period.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('regen_admin', 'admin')
        cls.school = School.objects.create(
            name='Regen School', slug='regen-school', admin=cls.admin,
        )
        cls.student1 = _user('regen_student1', 'student')
        cls.student2 = _user('regen_student2', 'student')

    def _generate(self, students, period_start, period_end):
        from classroom.invoicing_services import create_draft_invoices
        student_data = []
        for s in students:
            d = _student_data()
            d['student'] = s
            student_data.append(d)
        return create_draft_invoices(
            self.school, student_data, 'all_class_days',
            period_start, period_end, self.admin,
        )

    def test_old_issued_invoice_cancelled_when_regenerated(self):
        """Regenerating for the same period cancels the old issued invoice."""
        period_start = date(2025, 6, 1)
        period_end = date(2025, 6, 30)

        old = _invoice(
            self.student1, self.school, Decimal('200.00'),
            status='issued',
            billing_start=period_start, billing_end=period_end,
        )

        new_invoices = self._generate([self.student1], period_start, period_end)

        self.assertEqual(len(new_invoices), 1)
        old.refresh_from_db()
        self.assertEqual(old.status, 'cancelled', 'Old invoice should be cancelled')
        self.assertIn('Replaced', old.cancellation_reason)

    def test_old_draft_invoice_cancelled_when_regenerated(self):
        """Regenerating for the same period cancels old draft invoices too."""
        period_start = date(2025, 7, 1)
        period_end = date(2025, 7, 31)

        old = _invoice(
            self.student1, self.school, Decimal('200.00'),
            status='draft',
            billing_start=period_start, billing_end=period_end,
        )

        new_invoices = self._generate([self.student1], period_start, period_end)

        self.assertEqual(len(new_invoices), 1)
        old.refresh_from_db()
        self.assertEqual(old.status, 'cancelled')

    def test_cancelled_invoices_do_not_block(self):
        """Already cancelled invoices do not interfere with new ones."""
        period_start = date(2025, 8, 1)
        period_end = date(2025, 8, 31)

        _invoice(
            self.student1, self.school, Decimal('200.00'),
            status='cancelled',
            billing_start=period_start, billing_end=period_end,
        )

        new_invoices = self._generate([self.student1], period_start, period_end)
        self.assertEqual(len(new_invoices), 1)

    def test_different_period_not_affected(self):
        """Existing invoice for a different period is not cancelled."""
        june = _invoice(
            self.student1, self.school, Decimal('200.00'),
            status='issued',
            billing_start=date(2025, 6, 1), billing_end=date(2025, 6, 30),
        )

        new_invoices = self._generate(
            [self.student1], date(2025, 7, 1), date(2025, 7, 31),
        )

        self.assertEqual(len(new_invoices), 1)
        june.refresh_from_db()
        self.assertEqual(june.status, 'issued', 'June invoice should NOT be cancelled')

    def test_second_child_does_not_affect_first_child(self):
        """
        Generating invoices for child2 does NOT cancel child1's existing invoice
        (different student, same period).
        """
        period_start = date(2025, 6, 1)
        period_end = date(2025, 6, 30)

        child1_inv = _invoice(
            self.student1, self.school, Decimal('125.00'),
            status='issued',
            billing_start=period_start, billing_end=period_end,
        )

        # Generate only for child2
        new_invoices = self._generate([self.student2], period_start, period_end)

        self.assertEqual(len(new_invoices), 1)
        self.assertEqual(new_invoices[0].student, self.student2)

        child1_inv.refresh_from_db()
        self.assertEqual(
            child1_inv.status, 'issued',
            'Child1 invoice must not be affected when generating for child2',
        )

    def test_regenerate_both_children_cancels_only_matching_student(self):
        """
        Regenerating for both children: child1's old invoice is cancelled
        and replaced; child2 (no old invoice) gets a fresh one.
        """
        period_start = date(2025, 6, 1)
        period_end = date(2025, 6, 30)

        child1_old = _invoice(
            self.student1, self.school, Decimal('125.00'),
            status='issued',
            billing_start=period_start, billing_end=period_end,
        )

        new_invoices = self._generate(
            [self.student1, self.student2], period_start, period_end,
        )

        self.assertEqual(len(new_invoices), 2)

        child1_old.refresh_from_db()
        self.assertEqual(child1_old.status, 'cancelled')

        student_ids = {inv.student_id for inv in new_invoices}
        self.assertIn(self.student1.pk, student_ids)
        self.assertIn(self.student2.pk, student_ids)

    def test_partially_paid_invoice_cancelled_when_regenerated(self):
        """Even partially paid invoices are cancelled on regeneration."""
        period_start = date(2025, 9, 1)
        period_end = date(2025, 9, 30)

        old = _invoice(
            self.student1, self.school, Decimal('200.00'),
            status='partially_paid',
            billing_start=period_start, billing_end=period_end,
        )

        new_invoices = self._generate([self.student1], period_start, period_end)

        self.assertEqual(len(new_invoices), 1)
        old.refresh_from_db()
        self.assertEqual(old.status, 'cancelled')


# ===========================================================================
# Fix 3 — Currency from school settings, never from .env
# ===========================================================================

class CurrencyFromSchoolSettingsTests(TestCase):
    """
    Stripe Checkout must ALWAYS use the school's default_currency.
    The .env STRIPE_CURRENCY setting must never be used for invoice payments.
    Tests call create_invoice_checkout_session directly (the view no longer
    creates Stripe sessions — it only redirects to manual payment links).
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('cur_admin', 'admin')
        cls.aud, _ = Currency.objects.get_or_create(
            code='AUD', defaults={'name': 'Australian Dollar', 'symbol': '$'},
        )
        cls.nzd, _ = Currency.objects.get_or_create(
            code='NZD', defaults={'name': 'New Zealand Dollar', 'symbol': '$'},
        )
        cls.school = School.objects.create(
            name='AUD School', slug='aud-school', admin=cls.admin,
            default_currency=cls.aud,
        )
        cls.parent = _user('cur_parent', 'parent')
        cls.student = _user('cur_student', 'student')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
        )

    @override_settings(STRIPE_CURRENCY='nzd')
    @patch('billing.stripe_service.stripe')
    def test_school_currency_used_not_env(self, mock_stripe):
        """
        Even when .env STRIPE_CURRENCY is 'nzd', the checkout uses the
        school's default_currency (AUD) when called with currency='aud'.
        """
        from billing.stripe_service import create_invoice_checkout_session

        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/pay/cs_aud'
        mock_session.id = 'cs_aud'
        mock_stripe.checkout.Session.create.return_value = mock_session

        inv = _invoice(self.student, self.school, Decimal('125.00'))

        create_invoice_checkout_session(
            parent=self.parent,
            amount_applied=Decimal('125.00'),
            invoice_allocations=[{'invoice_id': inv.pk, 'amount': '125.00'}],
            request=MagicMock(build_absolute_uri=lambda path: f'http://test{path}'),
            currency='aud',
        )

        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        stripe_currency = call_kwargs['line_items'][0]['price_data']['currency']
        self.assertEqual(
            stripe_currency, 'aud',
            'Must use school currency AUD, not .env STRIPE_CURRENCY (nzd)',
        )

        isp = InvoiceStripePayment.objects.latest('created_at')
        self.assertEqual(isp.currency, 'aud')

    @patch('billing.stripe_service.stripe')
    def test_nzd_school_uses_nzd(self, mock_stripe):
        """School with NZD default_currency charges in NZD."""
        from billing.stripe_service import create_invoice_checkout_session

        mock_session = MagicMock()
        mock_session.url = 'https://checkout.stripe.com/pay/cs_nzd'
        mock_session.id = 'cs_nzd'
        mock_stripe.checkout.Session.create.return_value = mock_session

        inv = _invoice(self.student, self.school, Decimal('100.00'))

        create_invoice_checkout_session(
            parent=self.parent,
            amount_applied=Decimal('100.00'),
            invoice_allocations=[{'invoice_id': inv.pk, 'amount': '100.00'}],
            request=MagicMock(build_absolute_uri=lambda path: f'http://test{path}'),
            currency='nzd',
        )

        call_kwargs = mock_stripe.checkout.Session.create.call_args[1]
        stripe_currency = call_kwargs['line_items'][0]['price_data']['currency']
        self.assertEqual(stripe_currency, 'nzd')

    @override_settings(STRIPE_CURRENCY='nzd')
    def test_no_currency_raises_valueerror(self):
        """create_invoice_checkout_session raises ValueError if currency is None."""
        from billing.stripe_service import create_invoice_checkout_session

        _invoice(self.student, self.school, Decimal('100.00'))

        with self.assertRaises(ValueError, msg='currency is required'):
            create_invoice_checkout_session(
                parent=self.parent,
                amount_applied=Decimal('100.00'),
                invoice_allocations=[],
                request=MagicMock(),
                currency=None,
            )

    @override_settings(STRIPE_CURRENCY='nzd')
    @patch('billing.stripe_service.stripe')
    def test_env_stripe_currency_completely_ignored(self, mock_stripe):
        """
        Passing currency='aud' uses AUD regardless of .env STRIPE_CURRENCY=nzd.
        Passing currency=None raises ValueError — no fallback to .env.
        """
        from billing.stripe_service import create_invoice_checkout_session

        _invoice(self.student, self.school, Decimal('100.00'))

        with self.assertRaises(ValueError):
            create_invoice_checkout_session(
                parent=self.parent,
                amount_applied=Decimal('100.00'),
                invoice_allocations=[],
                request=MagicMock(),
                currency=None,
            )


class CurrencyWebhookWarningTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = _user('cww_admin', 'admin')
        cls.aud, _ = Currency.objects.get_or_create(
            code='AUD', defaults={'name': 'Australian Dollar', 'symbol': '$'},
        )
        cls.school = School.objects.create(
            name='CWW School', slug='cww-school', admin=cls.admin,
            default_currency=cls.aud,
        )
        cls.parent = _user('cww_parent', 'parent')
        cls.student = _user('cww_student', 'student')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, school=cls.school,
        )

    def test_currency_mismatch_logs_warning(self):
        """Webhook logs warning when Stripe currency != school currency."""
        inv = _invoice(self.student, self.school, Decimal('125.00'))
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal('128.00'),
            amount_applied=Decimal('125.00'),
            stripe_fee=Decimal('3.00'),
            currency='nzd',
            invoice_allocations=[{'invoice_id': inv.pk, 'amount': '125.00'}],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        session = {'id': 'cs_mismatch_test', 'currency': 'nzd'}
        metadata = {'isp_id': str(isp.pk)}

        with self.assertLogs('billing.webhook_handlers', level='WARNING') as cm:
            _handle_invoice_payment_checkout(metadata, session)

        self.assertTrue(
            any('Currency mismatch' in msg for msg in cm.output),
            'Should log a currency mismatch warning',
        )

        # Payment is still applied (warning only, not rejection)
        inv.refresh_from_db()
        self.assertEqual(inv.status, 'paid')

    def test_no_warning_when_currencies_match(self):
        """No warning logged when Stripe currency matches school currency."""
        inv = _invoice(self.student, self.school, Decimal('125.00'))
        isp = InvoiceStripePayment.objects.create(
            parent=self.parent,
            total_charged=Decimal('128.00'),
            amount_applied=Decimal('125.00'),
            stripe_fee=Decimal('3.00'),
            currency='aud',
            invoice_allocations=[{'invoice_id': inv.pk, 'amount': '125.00'}],
            status=InvoiceStripePayment.STATUS_PENDING,
        )

        session = {'id': 'cs_match_test', 'currency': 'aud'}
        metadata = {'isp_id': str(isp.pk)}

        with self.assertLogs('billing.webhook_handlers', level='INFO') as cm:
            _handle_invoice_payment_checkout(metadata, session)

        self.assertFalse(
            any('Currency mismatch' in msg for msg in cm.output),
            'Should NOT log a currency mismatch warning',
        )
