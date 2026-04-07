"""
Tests for email CC logic: resolve_cc_email(), send_templated_email() CC wiring,
send_staff_welcome_email() CC wiring, invoice email CC, and outgoing_email validation.
"""
from decimal import Decimal

from django.core import mail
from django.core.exceptions import ValidationError
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from billing.models import InstitutePlan, SchoolSubscription
from classroom.email_service import resolve_cc_email, send_templated_email
from classroom.models import School, Department


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.replace('_', ' ').title()},
    )
    return role


def _assign_role(user, role_name):
    role = _create_role(role_name)
    UserRole.objects.get_or_create(user=user, role=role)
    return role


def _setup_school(admin_user, slug='cc-test-school', outgoing_email=''):
    school = School.objects.create(
        name='CC Test School', slug=slug, admin=admin_user,
        outgoing_email=outgoing_email,
    )
    plan = InstitutePlan.objects.create(
        name='Basic', slug=f'basic-{slug}', price=Decimal('89.00'),
        stripe_price_id=f'price_{slug}', class_limit=50, student_limit=500,
        invoice_limit_yearly=500, extra_invoice_rate=Decimal('0.30'),
    )
    sub = SchoolSubscription.objects.create(school=school, plan=plan, status='active')
    return school, sub


# ===========================================================================
# resolve_cc_email() unit tests
# ===========================================================================

class ResolveCcEmailTests(TestCase):
    """Unit tests for the resolve_cc_email() helper."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='cc_admin', password='password1!', email='wlhtestmails+cc_admin@gmail.com',
        )

    def test_returns_school_outgoing_email(self):
        school, _ = _setup_school(self.admin, slug='cc-has-email', outgoing_email='school@inst.com')
        result = resolve_cc_email(school)
        self.assertEqual(result, ['school@inst.com'])

    def test_returns_empty_when_no_outgoing_email(self):
        school, _ = _setup_school(self.admin, slug='cc-no-email', outgoing_email='')
        result = resolve_cc_email(school)
        self.assertEqual(result, [])

    def test_returns_empty_when_school_is_none(self):
        result = resolve_cc_email(None)
        self.assertEqual(result, [])

    def test_department_override(self):
        school, _ = _setup_school(self.admin, slug='cc-dept-override', outgoing_email='school@inst.com')
        dept = Department.objects.create(
            school=school, name='Maths', slug='maths-cc-override',
            outgoing_email='dept@inst.com',
        )
        result = resolve_cc_email(school, department=dept)
        self.assertEqual(result, ['dept@inst.com'])

    def test_department_without_override_falls_back_to_school(self):
        school, _ = _setup_school(self.admin, slug='cc-dept-fallback', outgoing_email='school@inst.com')
        dept = Department.objects.create(
            school=school, name='Science', slug='sci-cc-fallback',
            outgoing_email='',
        )
        result = resolve_cc_email(school, department=dept)
        self.assertEqual(result, ['school@inst.com'])


# ===========================================================================
# send_templated_email() CC integration tests
# ===========================================================================

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='info@wizardslearninghub.co.nz',
    SITE_URL='http://localhost',
)
class SendTemplatedEmailCcTests(TestCase):
    """Integration tests verifying CC is applied in send_templated_email()."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='cc_email_admin', password='password1!', email='wlhtestmails+cc_email_admin@gmail.com',
        )

    def setUp(self):
        mail.outbox.clear()

    def test_email_has_cc_when_school_provided(self):
        school, _ = _setup_school(self.admin, slug='cc-send-has', outgoing_email='cc@inst.com')
        send_templated_email(
            recipient_email='wlhtestmails+student@gmail.com',
            subject='Test CC',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'Hello', 'notification_type': 'general'},
            school=school,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, ['cc@inst.com'])

    def test_email_no_cc_when_school_not_provided(self):
        send_templated_email(
            recipient_email='wlhtestmails+student@gmail.com',
            subject='Test No CC',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'Hello', 'notification_type': 'general'},
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, [])

    def test_email_no_cc_when_outgoing_email_empty(self):
        school, _ = _setup_school(self.admin, slug='cc-send-empty', outgoing_email='')
        send_templated_email(
            recipient_email='wlhtestmails+student@gmail.com',
            subject='Test Empty CC',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'Hello', 'notification_type': 'general'},
            school=school,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, [])

    def test_department_override_cc(self):
        school, _ = _setup_school(self.admin, slug='cc-send-dept', outgoing_email='school@inst.com')
        dept = Department.objects.create(
            school=school, name='Arts', slug='arts-cc-send',
            outgoing_email='arts@inst.com',
        )
        send_templated_email(
            recipient_email='wlhtestmails+student@gmail.com',
            subject='Test Dept CC',
            template_name='email/transactional/general_notification.html',
            context={'notification_message': 'Hello', 'notification_type': 'general'},
            school=school,
            department=dept,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, ['arts@inst.com'])


# ===========================================================================
# send_staff_welcome_email() CC tests
# ===========================================================================

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    DEFAULT_FROM_EMAIL='info@wizardslearninghub.co.nz',
    SITE_URL='http://localhost',
)
class StaffWelcomeEmailCcTests(TestCase):
    """Tests for CC in send_staff_welcome_email()."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='cc_welcome_admin', password='password1!', email='wlhtestmails+cc_welcome_admin@gmail.com',
        )
        cls.staff_user = CustomUser.objects.create_user(
            username='cc_staff', password='password1!', email='wlhtestmails+staff@gmail.com',
            first_name='Test', last_name='Staff',
        )

    def setUp(self):
        mail.outbox.clear()

    def test_welcome_email_has_cc(self):
        from classroom.email_utils import send_staff_welcome_email

        school, _ = _setup_school(self.admin, slug='cc-welcome-has', outgoing_email='school@inst.com')
        send_staff_welcome_email(
            user=self.staff_user,
            plain_password='temppass123',
            role_display='Teacher',
            school=school,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, ['school@inst.com'])

    def test_welcome_email_no_cc_when_no_outgoing(self):
        from classroom.email_utils import send_staff_welcome_email

        school, _ = _setup_school(self.admin, slug='cc-welcome-none', outgoing_email='')
        send_staff_welcome_email(
            user=self.staff_user,
            plain_password='temppass123',
            role_display='Teacher',
            school=school,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, [])

    def test_welcome_email_department_override_cc(self):
        from classroom.email_utils import send_staff_welcome_email

        school, _ = _setup_school(self.admin, slug='cc-welcome-dept', outgoing_email='school@inst.com')
        dept = Department.objects.create(
            school=school, name='Music', slug='music-cc-welcome',
            outgoing_email='music@inst.com',
        )
        send_staff_welcome_email(
            user=self.staff_user,
            plain_password='temppass123',
            role_display='Head of Department',
            school=school,
            department=dept,
        )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].cc, ['music@inst.com'])


# ===========================================================================
# Outgoing email validation tests
# ===========================================================================

class OutgoingEmailValidationTests(TestCase):
    """Tests for outgoing_email field validation on the School model."""

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            username='cc_val_admin', password='password1!', email='wlhtestmails+cc_val_admin@gmail.com',
        )

    def test_valid_email_accepted(self):
        school = School(
            name='Valid Email School', slug='val-email-ok', admin=self.admin,
            outgoing_email='wlhtestmails+valid@gmail.com',
        )
        # Should not raise
        school.full_clean()

    def test_invalid_email_rejected(self):
        school = School(
            name='Invalid Email School', slug='val-email-bad', admin=self.admin,
            outgoing_email='not-an-email',
        )
        with self.assertRaises(ValidationError):
            school.full_clean()

    def test_blank_email_accepted(self):
        school = School(
            name='Blank Email School', slug='val-email-blank', admin=self.admin,
            outgoing_email='',
        )
        # Should not raise
        school.full_clean()


# ===========================================================================
# Settings view validation tests
# ===========================================================================

@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
)
class SettingsViewValidationTests(TestCase):
    """Tests for outgoing_email validation in SchoolSettingsView."""

    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user(
            username='cc_settings_admin', password='password1!', email='wlhtestmails+cc_settings@gmail.com',
        )
        _assign_role(cls.user, Role.ADMIN)
        cls.school, cls.sub = _setup_school(cls.user, slug='cc-settings-school')

    def setUp(self):
        self.client.login(username='cc_settings_admin', password='password1!')

    def test_valid_outgoing_email_saves(self):
        url = reverse('admin_school_settings', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'active_tab': 'contact',
            'outgoing_email': 'wlhtestmails+valid@gmail.com',
            'abn': '', 'gst_number': '', 'street_address': '', 'city': '',
            'state_region': '', 'postal_code': '', 'country': '',
            'bank_name': '', 'bank_bsb': '', 'bank_account_number': '',
            'bank_account_name': '', 'invoice_terms': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.outgoing_email, 'wlhtestmails+valid@gmail.com')

    def test_invalid_outgoing_email_rejected(self):
        url = reverse('admin_school_settings', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'active_tab': 'contact',
            'outgoing_email': 'not-valid-email',
            'abn': '', 'gst_number': '', 'street_address': '', 'city': '',
            'state_region': '', 'postal_code': '', 'country': '',
            'bank_name': '', 'bank_bsb': '', 'bank_account_number': '',
            'bank_account_name': '', 'invoice_terms': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        # Should NOT have saved the invalid email
        self.assertNotEqual(self.school.outgoing_email, 'not-valid-email')

    def test_blank_outgoing_email_saves(self):
        # First set a valid email
        self.school.outgoing_email = 'wlhtestmails+old@gmail.com'
        self.school.save()

        url = reverse('admin_school_settings', kwargs={'school_id': self.school.id})
        resp = self.client.post(url, {
            'active_tab': 'contact',
            'outgoing_email': '',
            'abn': '', 'gst_number': '', 'street_address': '', 'city': '',
            'state_region': '', 'postal_code': '', 'country': '',
            'bank_name': '', 'bank_bsb': '', 'bank_account_number': '',
            'bank_account_name': '', 'invoice_terms': '',
        })
        self.assertEqual(resp.status_code, 302)
        self.school.refresh_from_db()
        self.assertEqual(self.school.outgoing_email, '')
