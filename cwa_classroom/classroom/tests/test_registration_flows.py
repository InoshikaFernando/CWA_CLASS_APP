"""
Tests for enhanced registration flows (CPP-55):
- Institute registration with company/address details
- Individual student registration with address + Stripe Checkout
- School student profile completion with address + subscription
- Discount code → Stripe coupon integration
"""

from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from billing.models import (
    InstitutePlan, SchoolSubscription, Package, Subscription,
    InstituteDiscountCode,
)
from classroom.models import School, SchoolStudent


def _create_role(name, display_name=None):
    role, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return role


def _create_user(username, password='password1!', **kwargs):
    return CustomUser.objects.create_user(
        username=username, password=password,
        email=kwargs.pop('email', f'wlhtestmails+{username}@gmail.com'),
        **kwargs,
    )


# ---------------------------------------------------------------------------
# 1. Institute Registration with Company Details
# ---------------------------------------------------------------------------

class InstituteRegistrationCompanyDetailsTest(TestCase):
    """Test that institute registration collects and saves company/address fields."""

    def test_register_saves_company_fields(self):
        """POST with company details should save them on the School."""
        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
            )

        resp = self.client.post(reverse('register_teacher_center'), {
            'center_name': 'Test Academy',
            'username': 'testacademy',
            'email': 'admin@testacademy.com',
            'password': 'password1!',
            'confirm_password': 'password1!',
            'plan_id': plan.id,
            'abn': '12 345 678 901',
            'phone': '+64 21 123 4567',
            'street_address': '123 Main Street',
            'city': 'Auckland',
            'state_region': 'Auckland',
            'postal_code': '1010',
            'country': 'New Zealand',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)  # Redirect on success

        school = School.objects.get(name='Test Academy')
        self.assertEqual(school.abn, '12 345 678 901')
        self.assertEqual(school.phone, '+64 21 123 4567')
        self.assertEqual(school.street_address, '123 Main Street')
        self.assertEqual(school.city, 'Auckland')
        self.assertEqual(school.state_region, 'Auckland')
        self.assertEqual(school.postal_code, '1010')
        self.assertEqual(school.country, 'New Zealand')

    def test_register_without_company_fields_still_works(self):
        """Registration should work with empty company details."""
        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
            )

        resp = self.client.post(reverse('register_teacher_center'), {
            'center_name': 'Minimal School',
            'username': 'minschool',
            'email': 'admin@minschool.com',
            'password': 'password1!',
            'confirm_password': 'password1!',
            'plan_id': plan.id,
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        school = School.objects.get(name='Minimal School')
        self.assertEqual(school.abn, '')
        self.assertEqual(school.street_address, '')

    def test_register_preserves_company_fields_on_error(self):
        """On validation error, company fields should be in context."""
        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
            )

        resp = self.client.post(reverse('register_teacher_center'), {
            'center_name': 'Error School',
            'username': 'errorschool',
            'email': 'bad-email',  # Invalid
            'password': 'password1!',
            'confirm_password': 'password1!',
            'plan_id': plan.id,
            'abn': '99 999 999 999',
            'city': 'Wellington',
        })
        self.assertEqual(resp.status_code, 200)  # Re-renders form
        self.assertContains(resp, '99 999 999 999')
        self.assertContains(resp, 'Wellington')


# ---------------------------------------------------------------------------
# 2. Individual Student Registration with Address
# ---------------------------------------------------------------------------

class IndividualStudentAddressTest(TestCase):
    """Test that individual student registration collects address fields."""

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Student Basic', price=19.90, class_limit=3,
            trial_days=14, is_active=True,
        )

    def test_register_saves_address_fields(self):
        """POST with address should save them on the user."""
        resp = self.client.post(reverse('register_individual_student'), {
            'username': 'studentaddr',
            'email': 'wlhtestmails+student@gmail.com',
            'password': 'password1!',
            'confirm_password': 'password1!',
            'package_id': self.package.id,
            'first_name': 'John',
            'last_name': 'Doe',
            'phone': '+64 21 555 0000',
            'street_address': '456 Student Ave',
            'city': 'Christchurch',
            'postal_code': '8011',
            'country': 'New Zealand',
            'accept_terms': 'on',
        })
        self.assertEqual(resp.status_code, 302)

        user = CustomUser.objects.get(username='studentaddr')
        self.assertEqual(user.first_name, 'John')
        self.assertEqual(user.last_name, 'Doe')
        self.assertEqual(user.phone, '+64 21 555 0000')
        self.assertEqual(user.street_address, '456 Student Ave')
        self.assertEqual(user.city, 'Christchurch')
        self.assertEqual(user.postal_code, '8011')
        self.assertEqual(user.country, 'New Zealand')

    def test_register_creates_subscription(self):
        """Registration should create a trialing subscription."""
        self.client.post(reverse('register_individual_student'), {
            'username': 'studentsub',
            'email': 'wlhtestmails+studentsub@gmail.com',
            'password': 'password1!',
            'confirm_password': 'password1!',
            'package_id': self.package.id,
            'accept_terms': 'on',
        })
        user = CustomUser.objects.get(username='studentsub')
        self.assertTrue(hasattr(user, 'subscription'))
        self.assertEqual(user.subscription.status, Subscription.STATUS_TRIALING)


# ---------------------------------------------------------------------------
# 3. School Student Profile Completion with Subscription
# ---------------------------------------------------------------------------

class SchoolStudentProfileSubscriptionTest(TestCase):
    """Test that school students get subscription after profile completion."""

    @classmethod
    def setUpTestData(cls):
        cls.hoi = _create_user('hoi_sub', first_name='Head', last_name='Sub')
        _create_role(Role.HEAD_OF_INSTITUTE)
        UserRole.objects.create(user=cls.hoi, role=Role.objects.get(name=Role.HEAD_OF_INSTITUTE))
        cls.school = School.objects.create(name='Sub School', admin=cls.hoi, is_active=True, slug='sub-school')
        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
            )
        SchoolSubscription.objects.create(
            school=cls.school, plan=plan, status='active',
            trial_end=timezone.now() + timedelta(days=14),
        )
        cls.package = Package.objects.create(
            name='Student Plan', price=19.90, class_limit=3,
            trial_days=14, is_active=True,
        )

    def _create_new_student(self):
        student = _create_user('school_sub_student', password='temppass123')
        student.must_change_password = True
        student.profile_completed = False
        student.save(update_fields=['must_change_password', 'profile_completed'])
        _create_role(Role.STUDENT)
        UserRole.objects.create(user=student, role=Role.objects.get(name=Role.STUDENT))
        SchoolStudent.objects.create(school=self.school, student=student)
        return student

    def test_complete_profile_saves_address(self):
        """Profile completion should save address fields."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.post(reverse('complete_profile'), {
            'new_password': 'newpass12345',
            'confirm_password': 'newpass12345',
            'first_name': 'School',
            'last_name': 'Student',
            'phone': '+64 21 999 0000',
            'street_address': '789 School Rd',
            'city': 'Hamilton',
            'postal_code': '3200',
            'country': 'New Zealand',
            'region': 'Waikato',
        })
        self.assertEqual(resp.status_code, 302)

        student.refresh_from_db()
        self.assertEqual(student.phone, '+64 21 999 0000')
        self.assertEqual(student.street_address, '789 School Rd')
        self.assertEqual(student.city, 'Hamilton')
        self.assertTrue(student.profile_completed)

    def test_complete_profile_creates_subscription(self):
        """School students should get a subscription after profile completion."""
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        client.post(reverse('complete_profile'), {
            'new_password': 'newpass12345',
            'confirm_password': 'newpass12345',
            'first_name': 'Sub',
            'last_name': 'Student',
        })
        student.refresh_from_db()
        self.assertIsNotNone(student.package)

    def test_complete_profile_with_100_percent_discount(self):
        """100% discount should activate subscription immediately."""
        discount = InstituteDiscountCode.objects.create(
            code='FREESTUDENT', discount_percent=100, max_uses=10,
        )
        student = self._create_new_student()
        client = Client()
        client.force_login(student)
        resp = client.post(reverse('complete_profile'), {
            'new_password': 'newpass12345',
            'confirm_password': 'newpass12345',
            'first_name': 'Free',
            'last_name': 'Student',
            'discount_code': 'FREESTUDENT',
        })
        self.assertEqual(resp.status_code, 302)
        self.assertIn('hub', resp.url)  # Redirects to hub, not Stripe

        student.refresh_from_db()
        self.assertTrue(student.profile_completed)
        sub = Subscription.objects.filter(user=student).first()
        self.assertIsNotNone(sub)
        self.assertEqual(sub.status, Subscription.STATUS_ACTIVE)


# ---------------------------------------------------------------------------
# 4. Discount Code with Stripe Coupon
# ---------------------------------------------------------------------------

class DiscountCodeStripeCouponTest(TestCase):
    """Test that discount codes with stripe_coupon_id pass coupon to Stripe."""

    def test_discount_code_has_stripe_coupon_field(self):
        """InstituteDiscountCode should have stripe_coupon_id field."""
        code = InstituteDiscountCode.objects.create(
            code='STRIPE50', discount_percent=50, max_uses=10,
            stripe_coupon_id='coupon_abc123',
        )
        self.assertEqual(code.stripe_coupon_id, 'coupon_abc123')

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_test')
    def test_institute_checkout_passes_coupon(self, mock_customer, mock_session):
        """Stripe Checkout should include discount coupon when provided."""
        from billing.stripe_service import create_institute_checkout_session
        mock_session.return_value = MagicMock(url='https://checkout.stripe.com/test')

        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
                stripe_price_id='price_test',
            )

        user = _create_user('coupon_hoi')
        school = School.objects.create(name='Coupon School', admin=user, slug='coupon-school')

        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = user

        create_institute_checkout_session(
            school, plan, request,
            trial_period_days=14,
            stripe_coupon_id='coupon_xyz',
        )

        call_kwargs = mock_session.call_args[1]
        self.assertIn('discounts', call_kwargs)
        self.assertEqual(call_kwargs['discounts'], [{'coupon': 'coupon_xyz'}])

    @patch('billing.stripe_service.stripe.checkout.Session.create')
    @patch('billing.stripe_service.get_or_create_customer', return_value='cus_test')
    def test_checkout_without_coupon_has_no_discounts(self, mock_customer, mock_session):
        """Without coupon, Stripe session should not have discounts."""
        from billing.stripe_service import create_institute_checkout_session
        mock_session.return_value = MagicMock(url='https://checkout.stripe.com/test')

        plan = InstitutePlan.objects.filter(slug='basic').first()
        if not plan:
            plan = InstitutePlan.objects.create(
                name='Basic', slug='basic', price=89,
                class_limit=5, student_limit=100,
                invoice_limit_yearly=500, extra_invoice_rate=0.30,
                stripe_price_id='price_test',
            )

        user = _create_user('nocoupon_hoi')
        school = School.objects.create(name='NoCoupon School', admin=user, slug='nocoupon-school')

        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = user

        create_institute_checkout_session(school, plan, request, trial_period_days=14)

        call_kwargs = mock_session.call_args[1]
        self.assertNotIn('discounts', call_kwargs)


# ---------------------------------------------------------------------------
# 5. Model field tests
# ---------------------------------------------------------------------------

class UserAddressFieldsTest(TestCase):
    """Test that new address fields save correctly on CustomUser."""

    def test_save_address_fields(self):
        user = _create_user('addr_user')
        user.phone = '+64 21 000 0000'
        user.street_address = '1 Test Lane'
        user.city = 'Wellington'
        user.postal_code = '6011'
        user.save()

        user.refresh_from_db()
        self.assertEqual(user.phone, '+64 21 000 0000')
        self.assertEqual(user.street_address, '1 Test Lane')
        self.assertEqual(user.city, 'Wellington')
        self.assertEqual(user.postal_code, '6011')


class SchoolCompanyFieldsTest(TestCase):
    """Test that new company fields save correctly on School."""

    def test_save_company_fields(self):
        user = _create_user('school_admin')
        school = School.objects.create(
            name='Field Test School', admin=user, slug='field-test',
            abn='99 999 999 999',
            street_address='100 Business Rd',
            city='Sydney',
            state_region='NSW',
            postal_code='2000',
            country='Australia',
        )
        school.refresh_from_db()
        self.assertEqual(school.abn, '99 999 999 999')
        self.assertEqual(school.city, 'Sydney')
        self.assertEqual(school.country, 'Australia')
