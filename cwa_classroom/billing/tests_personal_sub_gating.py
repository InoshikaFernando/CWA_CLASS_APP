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
from django.test import TestCase, RequestFactory

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

    # -- the payment wall itself stays reachable so they can fix the card ------

    def test_blocked_student_can_reach_billing_paths(self):
        student = _user('stu_billing', Role.STUDENT)
        self._enrol(student)
        Subscription.objects.create(
            user=student, package=self.package, status=Subscription.STATUS_PAST_DUE,
        )
        self._assert_allowed(self._run(student, path='/billing/'))
        self._assert_allowed(self._run(student, path='/accounts/trial-expired/'))
