"""The "Subscribed students only" filter on the report preview.

The filter has to bite on the *plan*, not on the rendered rows: the preview's
whole job is to show what the send would do, so a filter that narrowed the
table while "Generate and send" still mailed everybody would make the page lie
in the one way it exists to prevent.
"""

from datetime import datetime, time

from django.test import TestCase
from django.utils import timezone

from billing.models import Subscription
from classroom.models import ClassStudent, SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import (
    enable_reports, enrol, make_classroom, make_homework, make_school,
    make_user, submit,
)

URL = '/progress/reports/preview/'


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class SubscribedFilterBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school(slug='subs-school', name='Subs School')
        cls.classroom = make_classroom(cls.school, code='SUBS0001')
        cls.hoi = make_user('subs_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )

        cls.active = make_user('subs_active', first_name='Ada', last_name='A')
        cls.trialing = make_user('subs_trial', first_name='Bea', last_name='B')
        cls.cancelled = make_user('subs_cancelled', first_name='Cal', last_name='C')
        cls.never = make_user('subs_never', first_name='Dee', last_name='D')
        for student in (cls.active, cls.trialing, cls.cancelled, cls.never):
            enrol(cls.classroom, student)

        Subscription.objects.create(
            user=cls.active, status=Subscription.STATUS_ACTIVE)
        Subscription.objects.create(
            user=cls.trialing, status=Subscription.STATUS_TRIALING)
        Subscription.objects.create(
            user=cls.cancelled, status=Subscription.STATUS_CANCELLED)
        # cls.never deliberately has no Subscription row at all.

        # Activity inside the week that closed most recently, so every student
        # has a report worth sending and rows are not filtered by has_activity.
        last_monday = periods.previous_week(periods.today())[0]
        cls.window_start = last_monday
        homework = make_homework(
            cls.classroom, due=at(last_monday), title='Practice',
        )
        for student in (cls.active, cls.trialing, cls.cancelled, cls.never):
            submit(homework, student, 1, 7, when=at(last_monday))

    def setUp(self):
        self.client.force_login(self.hoi)
        enable_reports(self.school, kind='school', weekly=True)

    def students_on(self, response):
        return {row['student'] for row in response.context['rows']}


class PreviewFilterTests(SubscribedFilterBase):
    def test_without_the_filter_everyone_in_scope_is_listed(self):
        response = self.client.get(URL)

        self.assertFalse(response.context['subscribed_only'])
        self.assertEqual(
            self.students_on(response),
            {self.active, self.trialing, self.cancelled, self.never},
        )

    def test_subscribed_only_keeps_active_and_trialing(self):
        response = self.client.get(URL, {'subscribed': '1'})

        self.assertTrue(response.context['subscribed_only'])
        self.assertEqual(
            self.students_on(response), {self.active, self.trialing},
        )

    def test_a_cancelled_subscription_is_not_subscribed(self):
        # The row exists, which is exactly why "has a subscription" is the
        # wrong test — the status is what counts.
        response = self.client.get(URL, {'subscribed': '1'})
        self.assertNotIn(self.cancelled, self.students_on(response))

    def test_a_student_with_no_subscription_row_drops_out(self):
        response = self.client.get(URL, {'subscribed': '1'})
        self.assertNotIn(self.never, self.students_on(response))

    def test_any_other_value_leaves_the_scope_alone(self):
        response = self.client.get(URL, {'subscribed': 'yes'})

        self.assertFalse(response.context['subscribed_only'])
        self.assertEqual(len(self.students_on(response)), 4)

    def test_the_filter_still_writes_nothing(self):
        self.client.get(URL, {'subscribed': '1'})
        self.assertEqual(PeriodReport.objects.count(), 0)

    def test_the_checkbox_reflects_the_current_state(self):
        self.assertContains(
            self.client.get(URL, {'subscribed': '1'}),
            'data-testid="preview-subscribed"',
        )
        self.assertContains(
            self.client.get(URL, {'subscribed': '1'}), 'checked',
        )


class EmptyScopeTests(SubscribedFilterBase):
    def test_no_subscribed_student_says_so(self):
        """Not "nobody is enrolled" — the fix is to drop the filter, and a
        message naming the wrong cause sends staff to change a setting that is
        already correct."""
        Subscription.objects.all().update(status=Subscription.STATUS_CANCELLED)

        response = self.client.get(URL, {'subscribed': '1'})

        self.assertEqual(response.context['rows'], [])
        self.assertEqual(response.context['empty_reason'], 'no_subscribed')
        self.assertContains(response, 'No subscribed student is in scope')

    def test_an_empty_class_still_reports_no_students(self):
        # With nobody enrolled at all the filter is not the cause, so the
        # message must not blame it.
        ClassStudent.objects.filter(classroom=self.classroom).update(is_active=False)

        response = self.client.get(URL, {'subscribed': '1'})

        self.assertEqual(response.context['empty_reason'], 'no_students')


class SendHonoursTheFilterTests(SubscribedFilterBase):
    """The load-bearing half: what is previewed is what is sent."""

    def _send(self, **extra):
        return self.client.post(URL, {
            'school_id': self.school.id, 'period': periods.WEEKLY, **extra,
        })

    def test_sending_a_filtered_preview_only_generates_for_subscribers(self):
        self._send(subscribed='1')

        self.assertEqual(
            set(PeriodReport.objects.values_list('student_id', flat=True)),
            {self.active.id, self.trialing.id},
        )

    def test_sending_an_unfiltered_preview_still_covers_everyone(self):
        self._send()

        self.assertEqual(PeriodReport.objects.count(), 4)

    def test_the_redirect_keeps_the_filter_on(self):
        response = self._send(subscribed='1')
        self.assertIn('subscribed=1', response['Location'])
