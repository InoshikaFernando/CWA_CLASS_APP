"""The "Subscribed only" filter on the Manage Students list.

Subscribed means the student's OWN subscription is active or trialing. A
school-wide plan is not consulted: every student of a subscribed institute
would then match, and a filter that matches everybody is not a filter.
"""

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing.models import Subscription
from classroom.models import School, SchoolStudent


def _role(name):
    role, _ = Role.objects.get_or_create(
        name=name, defaults={'display_name': name},
    )
    return role


class ManageStudentsBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.hoi = CustomUser.objects.create_user('sf_hoi', 'sf_hoi@t.com', 'pass1234')
        cls.hoi.roles.add(_role(Role.HEAD_OF_INSTITUTE))
        cls.school = School.objects.create(name='CWA', slug='cwa-sf', admin=cls.hoi)

        cls.active = cls._student('sf_active', 'Ada', status=Subscription.STATUS_ACTIVE)
        cls.trialing = cls._student('sf_trial', 'Bea', status=Subscription.STATUS_TRIALING)
        cls.cancelled = cls._student('sf_cancelled', 'Cal', status=Subscription.STATUS_CANCELLED)
        cls.expired = cls._student('sf_expired', 'Eve', status=Subscription.STATUS_EXPIRED)
        cls.never = cls._student('sf_never', 'Dee')

    @classmethod
    def _student(cls, username, first_name, status=None, is_active=True):
        user = CustomUser.objects.create_user(
            username, f'{username}@t.com', 'pass1234', first_name=first_name,
            last_name='X',
        )
        user.roles.add(_role(Role.STUDENT))
        SchoolStudent.objects.create(
            school=cls.school, student=user, is_active=is_active,
        )
        if status is not None:
            Subscription.objects.create(user=user, status=status)
        return user

    def setUp(self):
        self.client.force_login(self.hoi)

    @property
    def url(self):
        return reverse('admin_school_students', kwargs={'school_id': self.school.id})

    def listed(self, response):
        return {ss.student for ss in response.context['school_students']}


class SubscribedFilterTests(ManageStudentsBase):
    def test_unfiltered_lists_every_active_student(self):
        response = self.client.get(self.url)

        self.assertFalse(response.context['subscribed_only'])
        self.assertEqual(len(self.listed(response)), 5)

    def test_subscribed_only_keeps_active_and_trialing(self):
        response = self.client.get(self.url, {'subscribed': '1'})

        self.assertTrue(response.context['subscribed_only'])
        self.assertEqual(self.listed(response), {self.active, self.trialing})

    def test_cancelled_and_expired_are_not_subscribed(self):
        response = self.client.get(self.url, {'subscribed': '1'})

        self.assertNotIn(self.cancelled, self.listed(response))
        self.assertNotIn(self.expired, self.listed(response))

    def test_a_student_with_no_subscription_row_drops_out(self):
        response = self.client.get(self.url, {'subscribed': '1'})
        self.assertNotIn(self.never, self.listed(response))

    def test_the_count_follows_the_filter(self):
        response = self.client.get(self.url, {'subscribed': '1'})

        self.assertEqual(response.context['total_count'], 2)
        # …and stops calling itself the total, which would read as the school
        # having lost three students.
        self.assertContains(response, 'Subscribed Students')

    def test_any_other_value_leaves_the_list_alone(self):
        response = self.client.get(self.url, {'subscribed': 'true'})

        self.assertFalse(response.context['subscribed_only'])
        self.assertEqual(len(self.listed(response)), 5)

    def test_it_combines_with_the_search(self):
        response = self.client.get(self.url, {'subscribed': '1', 'q': 'Ada'})

        self.assertEqual(self.listed(response), {self.active})

    def test_it_combines_with_show_inactive(self):
        removed = self._student(
            'sf_removed', 'Fay', status=Subscription.STATUS_ACTIVE,
            is_active=False,
        )

        self.assertNotIn(
            removed, self.listed(self.client.get(self.url, {'subscribed': '1'})),
        )
        self.assertIn(removed, self.listed(self.client.get(
            self.url, {'subscribed': '1', 'show_inactive': '1'},
        )))

    def test_an_empty_result_names_the_filter(self):
        """"No students found" under an active chip reads as "this school has
        no students", which sends staff looking for a data-loss bug."""
        Subscription.objects.all().update(status=Subscription.STATUS_CANCELLED)

        response = self.client.get(self.url, {'subscribed': '1'})

        self.assertEqual(len(self.listed(response)), 0)
        self.assertContains(
            response, 'No students with an active or trialing subscription',
        )


class FilterToggleLinkTests(ManageStudentsBase):
    """The chip switches one filter and keeps the rest — a toggle that dropped
    the current search would list a different set than the one it narrows."""

    def test_the_chip_turns_the_filter_on(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['toggle_subscribed_url'], '?subscribed=1')

    def test_the_chip_turns_the_filter_off_again(self):
        response = self.client.get(self.url, {'subscribed': '1'})
        self.assertEqual(response.context['toggle_subscribed_url'], '')

    def test_the_chip_keeps_the_search_and_sort(self):
        response = self.client.get(self.url, {'q': 'Ada', 'order_by': '-name'})

        url = response.context['toggle_subscribed_url']
        self.assertIn('q=Ada', url)
        self.assertIn('order_by=-name', url)
        self.assertIn('subscribed=1', url)

    def test_the_inactive_chip_keeps_the_subscribed_filter(self):
        response = self.client.get(self.url, {'subscribed': '1'})

        url = response.context['toggle_inactive_url']
        self.assertIn('subscribed=1', url)
        self.assertIn('show_inactive=1', url)

    def test_the_htmx_search_carries_the_filter(self):
        # The panel is swapped on each keystroke while the page around it is
        # not, so the flag has to live in the page, not in the panel.
        response = self.client.get(self.url, {'subscribed': '1'})
        self.assertContains(response, 'id="subscribed-flag"')
        self.assertContains(response, '#subscribed-flag')

    def test_the_htmx_sort_links_carry_the_filter(self):
        response = self.client.get(
            self.url, {'subscribed': '1'}, headers={'hx-request': 'true'},
        )
        self.assertContains(response, 'subscribed=1')
