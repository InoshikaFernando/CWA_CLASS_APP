"""
Unit tests for the ``reset_individual_billing`` management command.

The command resets ONE student hit by the legacy one-off PaymentIntent charge
(succeeded Payment + active Subscription with an EMPTY stripe_subscription_id)
so they walk back through the current Checkout flow and end up on a real
recurring subscription. It must:

  * cancel the stale local subscription but KEEP stripe_customer_id,
  * never touch succeeded Payment rows (the financial record),
  * swap STUDENT -> INDIVIDUAL_STUDENT only when asked,
  * re-gate profile_completed only for a student who stays a school student,
  * be dry-run by default and idempotent,
  * refuse to run while Stripe still holds a live subscription.
"""
from decimal import Decimal
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from accounts.models import CustomUser, Role, UserRole
from billing.models import Package, Payment, Subscription


def _make_user(username, role_name, profile_completed=True, email=None):
    user = CustomUser.objects.create_user(
        username=username,
        email=email if email is not None else f'{username}@example.local',
        password='TestPass123!',
        profile_completed=profile_completed,
    )
    role, _ = Role.objects.get_or_create(
        name=role_name, defaults={'display_name': role_name.title()},
    )
    UserRole.objects.create(user=user, role=role)
    return user


def _run(**kwargs):
    """Call the command, returning stdout. kwargs map to CLI flags."""
    out = StringIO()
    args = ['reset_individual_billing']
    for flag in ('email', 'username'):
        if kwargs.get(flag):
            args.extend([f'--{flag}', kwargs[flag]])
    for flag in ('make_individual', 'apply', 'force'):
        if kwargs.get(flag):
            args.append('--' + flag.replace('_', '-'))
    call_command(*args, stdout=out)
    return out.getvalue()


class ResetIndividualBillingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Student Monthly', price=Decimal('19.90'),
            stripe_price_id='price_reset_indv', is_default=True,
        )

    def _legacy_victim(self, username='siheli.test', role=Role.INDIVIDUAL_STUDENT):
        """A user in the legacy one-off state: paid once, no recurring sub."""
        user = _make_user(username, role)
        sub = Subscription.objects.create(
            user=user, package=self.package,
            status=Subscription.STATUS_ACTIVE,
            stripe_subscription_id='',          # the tell-tale
            stripe_customer_id='cus_legacy123',
        )
        payment = Payment.objects.create(
            user=user, amount=Decimal('19.90'),
            status=Payment.STATUS_SUCCEEDED,
        )
        return user, sub, payment

    # -- the core reset -------------------------------------------------

    def test_apply_cancels_stale_subscription(self):
        user, sub, _ = self._legacy_victim()
        _run(username=user.username, apply=True)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)
        self.assertIsNotNone(sub.cancelled_at)

    def test_stripe_customer_id_is_preserved(self):
        """The next checkout must reuse the same Stripe customer."""
        user, sub, _ = self._legacy_victim()
        _run(username=user.username, apply=True)
        sub.refresh_from_db()
        self.assertEqual(sub.stripe_customer_id, 'cus_legacy123')

    def test_succeeded_payment_is_never_touched(self):
        user, _, payment = self._legacy_victim()
        _run(username=user.username, apply=True)
        payment.refresh_from_db()
        self.assertEqual(payment.status, Payment.STATUS_SUCCEEDED)
        self.assertEqual(payment.amount, Decimal('19.90'))
        self.assertEqual(Payment.objects.filter(user=user).count(), 1)

    def test_individual_student_keeps_profile_completed(self):
        """TrialExpiryMiddleware gates individuals; the profile flag would be a
        dead step because CompleteProfileView has no individual payment branch."""
        user, _, _ = self._legacy_victim()
        _run(username=user.username, apply=True)
        user.refresh_from_db()
        self.assertTrue(user.profile_completed)

    # -- dry run --------------------------------------------------------

    def test_dry_run_writes_nothing(self):
        user, sub, _ = self._legacy_victim()
        out = _run(username=user.username)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)
        self.assertIn('Dry run', out)

    def test_dry_run_lists_the_planned_changes(self):
        user, _, _ = self._legacy_victim()
        out = _run(username=user.username)
        self.assertIn('active -> cancelled', out)

    # -- role swap ------------------------------------------------------

    def test_make_individual_swaps_the_role(self):
        user, _, _ = self._legacy_victim(username='school.stu', role=Role.STUDENT)
        _run(username=user.username, make_individual=True, apply=True)
        user.refresh_from_db()
        self.assertTrue(user.has_role(Role.INDIVIDUAL_STUDENT))
        self.assertFalse(user.has_role(Role.STUDENT))

    def test_make_individual_is_a_noop_when_already_individual(self):
        user, _, _ = self._legacy_victim()
        out = _run(username=user.username, make_individual=True, apply=True)
        user.refresh_from_db()
        self.assertTrue(user.has_role(Role.INDIVIDUAL_STUDENT))
        self.assertIn('already INDIVIDUAL_STUDENT', out)

    def test_school_student_left_as_student_is_re_gated(self):
        """Without --make-individual a school student goes back through the
        CompleteProfileView payment gate."""
        user, _, _ = self._legacy_victim(username='stays.school', role=Role.STUDENT)
        _run(username=user.username, apply=True)
        user.refresh_from_db()
        self.assertFalse(user.profile_completed)

    def test_converted_student_is_not_re_gated(self):
        user, _, _ = self._legacy_victim(username='converted.stu', role=Role.STUDENT)
        _run(username=user.username, make_individual=True, apply=True)
        user.refresh_from_db()
        self.assertTrue(user.profile_completed)

    # -- idempotency ----------------------------------------------------

    def test_second_run_changes_nothing(self):
        user, sub, _ = self._legacy_victim()
        _run(username=user.username, apply=True)
        sub.refresh_from_db()
        first_cancelled_at = sub.cancelled_at

        out = _run(username=user.username, apply=True)
        sub.refresh_from_db()
        self.assertIn('already reset', out)
        self.assertEqual(sub.cancelled_at, first_cancelled_at)

    def test_user_with_no_subscription_is_reported_not_crashed(self):
        user = _make_user('nosub.stu', Role.INDIVIDUAL_STUDENT)
        out = _run(username=user.username, apply=True)
        self.assertIn('No Subscription row', out)

    # -- resolution errors ----------------------------------------------

    def test_unknown_user_is_an_error(self):
        with self.assertRaises(CommandError) as ctx:
            _run(username='nobody.here')
        self.assertIn('No user with', str(ctx.exception))

    def test_neither_selector_is_an_error(self):
        with self.assertRaises(CommandError) as ctx:
            _run()
        self.assertIn('exactly one', str(ctx.exception))

    def test_both_selectors_is_an_error(self):
        user, _, _ = self._legacy_victim()
        with self.assertRaises(CommandError) as ctx:
            _run(username=user.username, email=user.email)
        self.assertIn('exactly one', str(ctx.exception))

    def test_ambiguous_email_is_an_error_not_a_guess(self):
        """CustomUser.email is unique, but that uniqueness is case-SENSITIVE on
        SQLite/Postgres — so a case-insensitive lookup can still hit two rows.
        Resolve to an error rather than picking one at random."""
        _make_user('twin.a', Role.INDIVIDUAL_STUDENT, email='Twin@example.local')
        _make_user('twin.b', Role.INDIVIDUAL_STUDENT, email='twin@example.local')
        with self.assertRaises(CommandError) as ctx:
            _run(email='twin@example.local')
        self.assertIn('share', str(ctx.exception))

    def test_lookup_is_case_insensitive(self):
        user, sub, _ = self._legacy_victim(username='Siheli.Case')
        _run(username='siheli.case', apply=True)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)

    # -- Stripe guard ---------------------------------------------------

    @override_settings(STRIPE_SECRET_KEY='sk_test_guard')
    def test_refuses_when_stripe_has_a_live_subscription(self):
        user, sub, _ = self._legacy_victim()
        with patch('stripe.Subscription.list') as m_subs, \
                patch('stripe.PaymentMethod.list') as m_cards:
            m_subs.return_value = {'data': [{'id': 'sub_live', 'status': 'active'}]}
            m_cards.return_value = {'data': []}
            with self.assertRaises(CommandError) as ctx:
                _run(username=user.username, apply=True)
        self.assertIn('reconcile_subscription', str(ctx.exception))
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)

    @override_settings(STRIPE_SECRET_KEY='sk_test_guard')
    def test_force_overrides_the_stripe_guard(self):
        user, sub, _ = self._legacy_victim()
        with patch('stripe.Subscription.list') as m_subs, \
                patch('stripe.PaymentMethod.list') as m_cards:
            m_subs.return_value = {'data': [{'id': 'sub_live', 'status': 'active'}]}
            m_cards.return_value = {'data': []}
            _run(username=user.username, apply=True, force=True)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)

    @override_settings(STRIPE_SECRET_KEY='sk_test_guard')
    def test_proceeds_when_stripe_confirms_the_orphan(self):
        user, sub, _ = self._legacy_victim()
        with patch('stripe.Subscription.list') as m_subs, \
                patch('stripe.PaymentMethod.list') as m_cards:
            m_subs.return_value = {'data': []}
            m_cards.return_value = {'data': []}
            out = _run(username=user.username, apply=True)
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_CANCELLED)
        self.assertIn('live subs=0', out)

    @override_settings(STRIPE_SECRET_KEY='sk_test_guard')
    def test_stripe_error_stops_rather_than_guessing(self):
        user, sub, _ = self._legacy_victim()
        with patch('stripe.Subscription.list', side_effect=Exception('boom')):
            with self.assertRaises(CommandError) as ctx:
                _run(username=user.username, apply=True)
        self.assertIn('Stripe lookup failed', str(ctx.exception))
        sub.refresh_from_db()
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)

    def test_missing_stripe_key_is_surfaced_not_silent(self):
        user, _, _ = self._legacy_victim()
        with override_settings(STRIPE_SECRET_KEY=''):
            out = _run(username=user.username)
        self.assertIn('SKIPPED', out)
