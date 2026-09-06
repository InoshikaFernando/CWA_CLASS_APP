"""Stripe moved two fields; we read both shapes now.

Recent Stripe API versions do not merely deprecate these keys — they REMOVE
them from the object we were reading, and put them somewhere else:

    invoice.subscription          -> invoice.parent.subscription_details.subscription
    subscription.current_period_* -> subscription.items.data[].current_period_*

A ``.get()`` on a key that is gone returns None rather than raising, so both
changes landed silently and stayed that way. Production, before this fix:

  * 41 of 41 ``invoice.payment_failed`` events processed with
    ``stripe_subscription_id: None`` — no subscription resolved, so no user,
    so NO EMAIL to any of them, while the app correctly locked those students
    out. Six families were never told why.
  * 0 of 129 subscriptions carried a period date, while 88 had a live Stripe
    subscription — 390 ``customer.subscription.updated`` events each writing
    None over a field nothing else could supply.

These tests pin both shapes. The old-shape cases are not legacy trivia: an
account can be moved back, and a fixture written against either shape must
keep working.
"""
from django.test import TestCase

from billing.webhook_handlers import (
    subscription_id_from_invoice, subscription_period,
)


class InvoiceSubscriptionIdTests(TestCase):
    def test_the_new_nested_location_is_read(self):
        invoice = {'parent': {'subscription_details': {'subscription': 'sub_new'}}}

        self.assertEqual(subscription_id_from_invoice(invoice), 'sub_new')

    def test_the_old_top_level_key_still_works(self):
        self.assertEqual(
            subscription_id_from_invoice({'subscription': 'sub_old'}), 'sub_old')

    def test_the_new_location_wins_when_both_are_present(self):
        invoice = {
            'subscription': 'sub_old',
            'parent': {'subscription_details': {'subscription': 'sub_new'}},
        }

        self.assertEqual(subscription_id_from_invoice(invoice), 'sub_new')

    def test_an_invoice_belonging_to_no_subscription_is_none(self):
        """A one-off invoice genuinely has no subscription. None here must mean
        that, not "we looked in the wrong place"."""
        self.assertIsNone(subscription_id_from_invoice({'id': 'in_1'}))

    def test_an_empty_parent_does_not_raise(self):
        self.assertIsNone(subscription_id_from_invoice({'parent': None}))
        self.assertIsNone(subscription_id_from_invoice({'parent': {}}))
        self.assertIsNone(subscription_id_from_invoice(
            {'parent': {'subscription_details': None}}))

    def test_a_parent_that_is_not_a_dict_does_not_raise(self):
        """Stripe expands some fields to a bare id string."""
        self.assertIsNone(subscription_id_from_invoice({'parent': 'in_parent_1'}))

    def test_the_real_production_payload_resolves(self):
        """Shape taken verbatim from a stored invoice.payment_failed event."""
        invoice = {
            'object': 'invoice',
            'subscription': None,
            'parent': {'subscription_details': {
                'subscription': 'sub_1Tza6RFILwrEyytieK9drcEg'}},
            'lines': {'data': [{'parent': {
                'type': 'subscription_item_details',
                'subscription_item_details': {}}}]},
        }

        self.assertEqual(subscription_id_from_invoice(invoice),
                         'sub_1Tza6RFILwrEyytieK9drcEg')


class SubscriptionPeriodTests(TestCase):
    # 2026-10-04 02:09:55Z and 2026-09-04 02:09:55Z
    END = 1791079795
    START = 1788487795

    def test_the_new_item_level_location_is_read(self):
        start, end = subscription_period({
            'items': {'data': [{'current_period_start': self.START,
                                'current_period_end': self.END}]},
        })

        self.assertEqual(end.year, 2026)
        self.assertEqual(end.month, 10)
        self.assertEqual(end.day, 4)
        self.assertIsNotNone(start)

    def test_the_old_top_level_keys_still_work(self):
        start, end = subscription_period({
            'current_period_start': self.START, 'current_period_end': self.END,
        })

        self.assertEqual(end.month, 10)
        self.assertIsNotNone(start)

    def test_the_top_level_value_wins_when_both_are_present(self):
        _start, end = subscription_period({
            'current_period_end': self.END,
            'items': {'data': [{'current_period_end': 1}]},
        })

        self.assertEqual(end.year, 2026)

    def test_a_subscription_with_no_period_anywhere_is_none_not_an_error(self):
        self.assertEqual(subscription_period({'id': 'sub_1'}), (None, None))

    def test_no_items_does_not_raise(self):
        self.assertEqual(subscription_period({'items': {}}), (None, None))
        self.assertEqual(subscription_period({'items': {'data': []}}), (None, None))

    def test_a_half_present_top_level_is_completed_from_the_items(self):
        """Belt and braces: whichever half is missing is filled from the item,
        so a transitional payload carrying only one of the pair still lands."""
        start, end = subscription_period({
            'current_period_start': self.START,
            'items': {'data': [{'current_period_end': self.END}]},
        })

        self.assertIsNotNone(start)
        self.assertEqual(end.month, 10)


class PaymentFailedReachesTheFamilyTests(TestCase):
    """Who hears about a failed payment.

    The student is locked out, so they need to know why. The parent usually
    holds the card, so they need to know too — and writing only to the student
    tells the child and leaves the person who can fix it unaware.
    """

    @classmethod
    def setUpTestData(cls):
        from accounts.models import CustomUser
        from classroom.models import ParentStudent
        cls.student = CustomUser.objects.create_user(
            'pf_student', 'child@example.test', 'TestPass123!')
        cls.parent = CustomUser.objects.create_user(
            'pf_parent', 'payer@example.test', 'TestPass123!')
        ParentStudent.objects.create(
            parent=cls.parent, student=cls.student, is_active=True)

    def _send(self, **kw):
        from django.core import mail
        from billing.email_utils import notify_payment_failed
        mail.outbox = []
        notify_payment_failed(detail={'amount_cents': 1990}, **kw)
        return mail.outbox

    def test_both_the_student_and_the_parent_are_written_to(self):
        sent = self._send(user=self.student)

        self.assertEqual(len(sent), 1)
        self.assertCountEqual(sent[0].to,
                              ['child@example.test', 'payer@example.test'])

    def test_a_student_with_no_parent_still_gets_the_mail(self):
        from accounts.models import CustomUser
        alone = CustomUser.objects.create_user(
            'pf_alone', 'alone@example.test', 'TestPass123!')

        sent = self._send(user=alone)

        self.assertEqual(sent[0].to, ['alone@example.test'])

    def test_a_student_with_no_address_is_reached_through_their_parent(self):
        """A bulk-imported student often has no email of their own. That must
        not silence the notification — the payer still has an address."""
        from accounts.models import CustomUser
        from classroom.models import ParentStudent
        child = CustomUser.objects.create_user(
            'pf_noemail', None, 'TestPass123!')
        ParentStudent.objects.create(
            parent=self.parent, student=child, is_active=True)

        sent = self._send(user=child)

        self.assertEqual(sent[0].to, ['payer@example.test'])

    def test_an_inactive_parent_link_is_not_written_to(self):
        from accounts.models import CustomUser
        from classroom.models import ParentStudent
        ex = CustomUser.objects.create_user(
            'pf_ex', 'ex@example.test', 'TestPass123!')
        ParentStudent.objects.create(
            parent=ex, student=self.student, is_active=False)

        self.assertNotIn('ex@example.test', self._send(user=self.student)[0].to)

    def test_reaching_nobody_is_recorded_rather_than_only_logged(self):
        """This is how 41 failed payments went unnoticed: a logger.warning and
        nothing else. An audit event puts it somewhere a person looks."""
        from accounts.models import CustomUser
        from audit.models import AuditLog
        nobody = CustomUser.objects.create_user(
            'pf_nobody', None, 'TestPass123!')

        self.assertEqual(self._send(user=nobody), [])
        self.assertTrue(AuditLog.objects.filter(
            action='payment_failed_unreachable', user=nobody).exists())

    def test_an_institute_failure_still_goes_to_the_school_admin(self):
        from accounts.models import CustomUser
        from classroom.models import School
        admin = CustomUser.objects.create_user(
            'pf_admin', 'admin@example.test', 'TestPass123!')
        school = School.objects.create(
            name='PF School', slug='pf-school', admin=admin)

        sent = self._send(school=school)

        self.assertEqual(sent[0].to, ['admin@example.test'])
