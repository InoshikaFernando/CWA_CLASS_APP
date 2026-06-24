"""
CPP-362: school subscription discount code surfaced in welcome/resend emails.

Covers:
- School settings validation: active code accepted (canonicalised), unknown/inactive rejected.
- Resend modal shows the discount checkbox only when the school has an active code.
- Resend includes the code in the email (student + parent) only when ticked.
"""
from django.core import mail
from django.urls import reverse

from accounts.models import Role
from classroom.models import ParentStudent
from billing.models import DiscountCode
from classroom.tests.test_cpp198_resend_welcome import (
    _make_user, ResendWelcomeBase,
)


class WelcomeDiscountBase(ResendWelcomeBase):
    """ResendWelcomeBase + an active discount code set on the school + a parent."""

    def setUp(self):
        super().setUp()
        DiscountCode.objects.create(code='MHMEBC75', discount_percent=75, is_active=True)
        self.school.subscription_discount_code = 'MHMEBC75'
        self.school.save(update_fields=['subscription_discount_code'])

        self.parent = _make_user('disc_parent', Role.PARENT, creation_method='institute')
        ParentStudent.objects.create(
            school=self.school, parent=self.parent, student=self.student, is_active=True,
        )

    def _modal_url(self, user_id):
        return reverse('admin_user_resend_welcome_modal', args=[self.school.id, user_id])

    def _resend_url(self, user_id):
        return reverse('admin_user_resend_welcome', args=[self.school.id, user_id])


# ---------------------------------------------------------------------------
# Settings validation
# ---------------------------------------------------------------------------

class TestDiscountSettings(ResendWelcomeBase):

    def _settings_url(self):
        return reverse('admin_school_settings', args=[self.school.id])

    def test_valid_active_code_saved_canonicalised(self):
        DiscountCode.objects.create(code='MHMEBC75', discount_percent=75, is_active=True)
        self.client.post(self._settings_url(), {
            'active_tab': 'payments', 'subscription_discount_code': 'mhmebc75',
        })
        self.school.refresh_from_db()
        self.assertEqual(self.school.subscription_discount_code, 'MHMEBC75')

    def test_unknown_code_rejected(self):
        self.client.post(self._settings_url(), {
            'active_tab': 'payments', 'subscription_discount_code': 'NOPE99',
        })
        self.school.refresh_from_db()
        self.assertEqual(self.school.subscription_discount_code, '')

    def test_inactive_code_rejected(self):
        DiscountCode.objects.create(code='OLD50', discount_percent=50, is_active=False)
        self.client.post(self._settings_url(), {
            'active_tab': 'payments', 'subscription_discount_code': 'OLD50',
        })
        self.school.refresh_from_db()
        self.assertEqual(self.school.subscription_discount_code, '')

    def test_blank_allowed(self):
        self.client.post(self._settings_url(), {
            'active_tab': 'payments', 'subscription_discount_code': '',
        })
        self.school.refresh_from_db()
        self.assertEqual(self.school.subscription_discount_code, '')

    def test_setting_exposed_via_effective_settings(self):
        DiscountCode.objects.create(code='MHMEBC75', discount_percent=75, is_active=True)
        self.school.subscription_discount_code = 'MHMEBC75'
        self.school.save(update_fields=['subscription_discount_code'])
        eff = self.school.get_effective_settings()
        self.assertEqual(eff.get('subscription_discount_code'), 'MHMEBC75')


# ---------------------------------------------------------------------------
# Modal checkbox visibility
# ---------------------------------------------------------------------------

class TestDiscountModal(WelcomeDiscountBase):

    def test_modal_shows_discount_for_student(self):
        resp = self.client.get(self._modal_url(self.student.id))
        self.assertContains(resp, 'Include subscription discount')
        self.assertContains(resp, 'MHMEBC75')

    def test_modal_shows_discount_for_parent(self):
        resp = self.client.get(self._modal_url(self.parent.id))
        self.assertContains(resp, 'Include subscription discount')
        self.assertContains(resp, 'MHMEBC75')

    def test_modal_hides_discount_when_no_code(self):
        self.school.subscription_discount_code = ''
        self.school.save(update_fields=['subscription_discount_code'])
        resp = self.client.get(self._modal_url(self.student.id))
        self.assertNotContains(resp, 'Include subscription discount')

    def test_modal_hides_discount_when_code_inactive(self):
        DiscountCode.objects.filter(code='MHMEBC75').update(is_active=False)
        resp = self.client.get(self._modal_url(self.student.id))
        self.assertNotContains(resp, 'Include subscription discount')


# ---------------------------------------------------------------------------
# Discount in the resent email
# ---------------------------------------------------------------------------

class TestDiscountInEmail(WelcomeDiscountBase):

    def test_student_resend_includes_discount_when_ticked(self):
        self.client.post(self._resend_url(self.student.id), {'include_discount': '1'})
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn('MHMEBC75', body)
        self.assertIn('75% off', body)

    def test_student_resend_omits_discount_when_unticked(self):
        self.client.post(self._resend_url(self.student.id), {})
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].alternatives[0][0]
        self.assertNotIn('MHMEBC75', body)

    def test_parent_resend_includes_discount_when_ticked(self):
        self.client.post(self._resend_url(self.parent.id), {'include_discount': '1'})
        self.assertEqual(len(mail.outbox), 1)
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn('MHMEBC75', body)
        self.assertIn('75% off', body)

    def test_no_discount_sent_when_school_has_no_code(self):
        self.school.subscription_discount_code = ''
        self.school.save(update_fields=['subscription_discount_code'])
        self.client.post(self._resend_url(self.student.id), {'include_discount': '1'})
        body = mail.outbox[0].alternatives[0][0]
        self.assertNotIn('MHMEBC75', body)
