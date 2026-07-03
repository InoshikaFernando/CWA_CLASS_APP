"""
Personal-subscription gating in TrialExpiryMiddleware.

School students and parents who self-pay hold their OWN recurring
``billing.Subscription``. Before this fix the middleware only checked the
*school* subscription for those roles, so a self-paying student whose card
failed (personal sub → past_due) kept full access by riding the school's active
plan. These tests lock in the policy: a delinquent personal subscription blocks,
unless it is an active (incl. 100%-discount) sub.

The headline regression case is a past_due school student under an ACTIVE school
subscription — the real Ovindik / Maths Hub Melbourne situation — which must now
be redirected to the payment wall.
"""
from unittest.mock import patch

from django.test import TestCase, RequestFactory
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import School, SchoolStudent
from billing.models import Package, Subscription, SchoolSubscription
from cwa_classroom.middleware import TrialExpiryMiddleware

SENTINEL = object()  # returned by get_response when the request is NOT blocked


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name.title()},
    )
    return role


def _user(username, role_name):
    user = CustomUser.objects.create_user(
        username=username, email=f'{username}@test.local',
        password='TestPass123!', profile_completed=True,
    )
    UserRole.objects.create(user=user, role=_role(role_name))
    return user


class PersonalSubscriptionGatingTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Student Monthly', price=19.90, stripe_price_id='price_gate_test',
        )
        # A school with an ACTIVE subscription — students ride this unless their
        # own personal subscription says otherwise.
        admin = CustomUser.objects.create_user(
            username='mhb_admin', email='mhb_admin@test.local', password='TestPass123!',
        )
        cls.school = School.objects.create(name='Maths Hub', slug='maths-hub', admin=admin)
        cls.school_sub = SchoolSubscription.objects.create(
            school=cls.school, status=SchoolSubscription.STATUS_ACTIVE,
        )

    def setUp(self):
        self.rf = RequestFactory()
        self.mw = TrialExpiryMiddleware(lambda request: SENTINEL)

    def _enrol(self, user):
        SchoolStudent.objects.create(school=self.school, student=user, is_active=True)

    def _run(self, user, path='/hub/'):
        request = self.rf.get(path)
        request.user = user
        return self.mw(request)

    def _assert_blocked(self, response):
        self.assertIsNot(response, SENTINEL, 'expected a redirect, got pass-through')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/accounts/trial-expired/', response.url)

    def _assert_allowed(self, response):
        self.assertIs(response, SENTINEL, 'expected pass-through, got a redirect')

    # -- the headline regression: Ovindik --------------------------------------

    def test_past_due_school_student_under_active_school_sub_is_blocked(self):
        """past_due personal sub + ACTIVE school sub → BLOCKED (the live bug)."""
        student = _user('stu_pastdue', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package,
            status=Subscription.STATUS_PAST_DUE, stripe_subscription_id='sub_pd',
        )
        self._assert_blocked(self._run(student))

    def test_cancelled_school_student_is_blocked(self):
        student = _user('stu_cancelled', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package, status=Subscription.STATUS_CANCELLED,
        )
        self._assert_blocked(self._run(student))

    # -- must NOT over-block ----------------------------------------------------

    def test_active_personal_sub_is_allowed(self):
        student = _user('stu_active', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package, status=Subscription.STATUS_ACTIVE,
        )
        self._assert_allowed(self._run(student))

    def test_hundred_percent_discount_active_sub_is_allowed(self):
        """A 100%-discount student has an active (free) sub → never blocked."""
        student = _user('stu_free', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package, status=Subscription.STATUS_ACTIVE,
            promo_code_used='CWAEBC',  # 100%-off code
        )
        self._assert_allowed(self._run(student))

    def test_student_with_no_personal_sub_rides_school_plan(self):
        """No personal sub + active school sub → allowed (legitimate rider)."""
        student = _user('stu_nosub', Role.STUDENT)
        self._enrol(student)
        self._assert_allowed(self._run(student))

    # -- parents were never checked before -------------------------------------

    def test_past_due_parent_is_blocked(self):
        parent = _user('parent_pastdue', Role.PARENT)
        Subscription.objects.create(
            user=parent, package=self.package, status=Subscription.STATUS_PAST_DUE,
        )
        self._assert_blocked(self._run(parent))

    # -- staff must NOT be locked out by a stale personal sub (scope) ----------

    def test_teacher_with_delinquent_personal_sub_not_blocked(self):
        """A teacher who happens to hold a past_due personal sub keeps access."""
        teacher = _user('tch_pastdue', Role.TEACHER)
        Subscription.objects.create(
            user=teacher, package=self.package, status=Subscription.STATUS_PAST_DUE,
        )
        self._assert_allowed(self._run(teacher))

    def test_head_of_institute_with_delinquent_personal_sub_not_blocked(self):
        hoi = _user('hoi_pastdue', Role.HEAD_OF_INSTITUTE)
        Subscription.objects.create(
            user=hoi, package=self.package, status=Subscription.STATUS_PAST_DUE,
        )
        self._assert_allowed(self._run(hoi))

    # -- the payment wall itself stays reachable so they can fix the card ------

    def test_blocked_student_can_reach_billing_paths(self):
        student = _user('stu_billing', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package, status=Subscription.STATUS_PAST_DUE,
        )
        self._assert_allowed(self._run(student, path='/billing/'))
        self._assert_allowed(self._run(student, path='/accounts/trial-expired/'))


class StripeBillingPortalAccessTests(TestCase):
    """A gated student sent to the payment wall must never reach the SCHOOL's
    Stripe billing portal (StripeBillingPortalView used to resolve the school's
    customer for any member — a student could then change/cancel school billing).
    """

    @classmethod
    def setUpTestData(cls):
        cls.pkg = Package.objects.create(
            name='Portal Pkg', price=19.90, stripe_price_id='price_portal_test',
        )
        cls.admin = CustomUser.objects.create_user(
            username='portal_hoi', email='portal_hoi@test.local', password='TestPass123!',
        )
        UserRole.objects.create(user=cls.admin, role=_role(Role.HEAD_OF_INSTITUTE))
        cls.school = School.objects.create(
            name='Portal School', slug='portal-school', admin=cls.admin,
        )
        cls.school_sub = SchoolSubscription.objects.create(
            school=cls.school, status=SchoolSubscription.STATUS_ACTIVE,
            stripe_customer_id='cus_SCHOOL_secret',
        )

    @patch('billing.stripe_service.create_billing_portal_session')
    def test_school_student_cannot_open_school_portal(self, mock_portal):
        student = _user('portal_stu', Role.STUDENT)
        SchoolStudent.objects.create(school=self.school, student=student, is_active=True)
        # Self-pays but has no own Stripe customer id (the Ovindik shape).
        Subscription.objects.create(
            user=student, package=self.pkg, status=Subscription.STATUS_PAST_DUE,
        )
        self.client.force_login(student)
        resp = self.client.get(reverse('stripe_billing_portal'))
        # Never resolved a customer → never called Stripe → bounced locally,
        # NOT off to the school's Stripe portal.
        mock_portal.assert_not_called()
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(resp.url.startswith('http'))

    @patch('billing.stripe_service.create_billing_portal_session')
    def test_school_admin_opens_own_school_portal(self, mock_portal):
        mock_portal.return_value = type('S', (), {'url': 'https://stripe.test/portal'})()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('stripe_billing_portal'))
        mock_portal.assert_called_once()
        self.assertEqual(mock_portal.call_args[0][0], 'cus_SCHOOL_secret')
        self.assertEqual(resp.status_code, 302)
