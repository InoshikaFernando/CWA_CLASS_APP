"""Who counts as unsubscribed — the one definition both lists are built from.

``filter_subscribed`` and ``filter_unsubscribed`` have to partition the school
exactly: every student in one or the other, nobody in both, nobody in neither.
That is easy to state and easy to get wrong in a way that returns rows and
looks fine.

The failure worth naming is the never-subscribed student. Writing the
complement as ``filter(status__in=<the other statuses>)`` reads correct, joins
the subscription table, and therefore quietly reaches only students who
subscribed once and lapsed — dropping everyone who has no subscription row at
all. For a promotion aimed at people who have never paid, that is precisely the
half you were trying to reach, and the query still returns a plausible-looking
list.
"""
from django.contrib.auth import get_user_model
from django.test import TestCase

from billing.models import Package, Subscription
from billing.selectors import filter_subscribed, filter_unsubscribed
from classroom.models import School, SchoolStudent

User = get_user_model()


class WhoCountsAsUnsubscribed(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.package = Package.objects.create(
            name='Wizard', price=19.90, stripe_price_id='price_sel_test')
        admin = User.objects.create_user(
            username='sel_admin', email='sel_admin@test.local',
            password='TestPass123!')
        cls.school = School.objects.create(
            name='Selector School', slug='selector-school', admin=admin)

    def _student(self, username, status=None):
        user = User.objects.create_user(
            username=username, email=f'{username}@test.local',
            password='TestPass123!')
        SchoolStudent.objects.create(
            school=self.school, student=user, is_active=True)
        if status is not None:
            Subscription.objects.create(
                user=user, package=self.package, status=status)
        return user

    def _enrolments(self):
        return SchoolStudent.objects.filter(school=self.school, is_active=True)

    def _unsubscribed_usernames(self):
        return set(
            filter_unsubscribed(
                self._enrolments(), path='student__subscription',
            ).values_list('student__username', flat=True))

    # -- the one that gets dropped ------------------------------------------

    def test_a_student_who_never_subscribed_is_unsubscribed(self):
        """No Subscription row at all. The largest group, and the easy miss."""
        self._student('never_had_one')
        self.assertIn('never_had_one', self._unsubscribed_usernames())

    def test_the_naive_complement_would_have_missed_them(self):
        """Pins WHY ``exclude`` is used, so nobody 'tidies' it into a filter.

        The tidier spelling joins, so it can only return students who hold a
        subscription row in some other status.
        """
        self._student('never_had_one')
        self._student('lapsed', Subscription.STATUS_EXPIRED)

        naive = set(
            self._enrolments().filter(
                student__subscription__status__in=[
                    Subscription.STATUS_EXPIRED,
                    Subscription.STATUS_CANCELLED,
                    Subscription.STATUS_PAST_DUE,
                ],
            ).values_list('student__username', flat=True))

        self.assertEqual(naive, {'lapsed'})
        self.assertEqual(self._unsubscribed_usernames(),
                         {'lapsed', 'never_had_one'})

    # -- the rest of the partition ------------------------------------------

    def test_expired_cancelled_and_past_due_are_all_unsubscribed(self):
        self._student('expired', Subscription.STATUS_EXPIRED)
        self._student('cancelled', Subscription.STATUS_CANCELLED)
        self._student('past_due', Subscription.STATUS_PAST_DUE)

        self.assertEqual(
            self._unsubscribed_usernames(),
            {'expired', 'cancelled', 'past_due'})

    def test_active_and_trialing_students_are_left_out(self):
        """The people you must not send a "start paying" email to."""
        self._student('paying', Subscription.STATUS_ACTIVE)
        self._student('on_trial', Subscription.STATUS_TRIALING)

        self.assertEqual(self._unsubscribed_usernames(), set())

    def test_the_two_selectors_partition_the_school_exactly(self):
        for name, status in [
            ('paying', Subscription.STATUS_ACTIVE),
            ('on_trial', Subscription.STATUS_TRIALING),
            ('expired', Subscription.STATUS_EXPIRED),
            ('cancelled', Subscription.STATUS_CANCELLED),
            ('past_due', Subscription.STATUS_PAST_DUE),
            ('never_had_one', None),
        ]:
            self._student(name, status)

        subscribed = set(filter_subscribed(
            self._enrolments(), path='student__subscription',
        ).values_list('student__username', flat=True))
        unsubscribed = self._unsubscribed_usernames()
        everyone = set(self._enrolments().values_list(
            'student__username', flat=True))

        self.assertEqual(subscribed & unsubscribed, set(), 'nobody in both')
        self.assertEqual(subscribed | unsubscribed, everyone, 'nobody in neither')

    def test_a_student_on_the_mhm_promotion_counts_as_unsubscribed_once_it_lapses(self):
        """The case this was built for.

        During the free fortnight they are trialing, so they are NOT on the
        list — sending them the offer they are already using would be absurd.
        The middleware marks them expired when it ends, and they appear.
        """
        student = self._student('mhm_kid', Subscription.STATUS_TRIALING)
        self.assertNotIn('mhm_kid', self._unsubscribed_usernames())

        Subscription.objects.filter(user=student).update(
            status=Subscription.STATUS_EXPIRED)
        self.assertIn('mhm_kid', self._unsubscribed_usernames())
