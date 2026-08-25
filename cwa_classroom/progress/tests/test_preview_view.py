"""The staff preview and manual send (CPP-388 follow-up).

Manual is the default mode, which only means something if staff can see what
they would be sending. The load-bearing property here is that a preview writes
nothing: a preview that created rows would stamp delivery state and leave the
real send with nothing to do.
"""

from datetime import date, datetime, time

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import Notification, SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import (
    add_teacher, enable_reports, enrol, link_parent, make_classroom,
    make_homework, make_school, make_user, submit,
)

URL = '/progress/reports/preview/'


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class PreviewBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.hoi = make_user('pv_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('pv_student', first_name='Ada', last_name='B')
        cls.quiet = make_user('pv_quiet', first_name='Quiet', last_name='One')
        cls.parent = make_user('pv_parent', 'parent')
        enrol(cls.classroom, cls.student)
        enrol(cls.classroom, cls.quiet)
        link_parent(cls.parent, cls.student, cls.school)

        # Freeze the window the preview will pick by putting the work inside
        # the week that closed most recently relative to "today".
        last_monday = periods.previous_week(periods.today())[0]
        cls.window_start = last_monday
        homework = make_homework(
            cls.classroom, due=at(last_monday), title='Practice',
        )
        submit(homework, cls.student, 1, 4, when=at(last_monday))
        submit(homework, cls.student, 2, 9, when=at(last_monday))

    def setUp(self):
        self.client.force_login(self.hoi)


class PreviewAccessTests(PreviewBase):
    def test_the_head_of_institute_can_preview(self):
        enable_reports(self.school, kind='school', weekly=True)
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['school'], self.school)

    def test_a_student_cannot(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_a_parent_cannot(self):
        self.client.force_login(self.parent)
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_anonymous_users_are_sent_to_log_in(self):
        self.client.logout()
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)


class PreviewContentTests(PreviewBase):
    def test_it_lists_every_student_in_scope(self):
        enable_reports(self.school, kind='school', weekly=True)
        response = self.client.get(URL)

        students = [row['student'] for row in response.context['rows']]
        self.assertCountEqual(students, [self.student, self.quiet])

    def test_it_shows_the_figures_that_would_be_sent(self):
        enable_reports(self.school, kind='school', weekly=True)
        response = self.client.get(URL)

        row = next(
            r for r in response.context['rows'] if r['student'] == self.student
        )
        self.assertEqual(row['totals']['avg_best_pct'], 90)
        self.assertEqual(row['totals']['avg_first_pct'], 40)
        self.assertTrue(row['has_activity'])

    def test_a_student_with_no_submissions_is_shown_as_sending_nothing(self):
        enable_reports(self.school, kind='school', weekly=True)
        response = self.client.get(URL)

        row = next(
            r for r in response.context['rows'] if r['student'] == self.quiet
        )
        self.assertFalse(row['has_activity'])
        self.assertEqual(response.context['with_activity_count'], 1)

    def test_it_says_who_each_report_would_reach(self):
        enable_reports(
            self.school, kind='school', weekly=True, notify_parents=False,
        )
        response = self.client.get(URL)

        row = next(
            r for r in response.context['rows'] if r['student'] == self.student
        )
        self.assertTrue(row['delivery']['notify_student'])
        self.assertFalse(row['delivery']['notify_parents'])
        self.assertEqual(row['audience'], 'Student')

    def test_a_silent_class_says_it_will_reach_nobody(self):
        enable_reports(
            self.school, kind='school', weekly=True,
            notify_student=False, notify_parents=False,
        )
        response = self.client.get(URL)

        row = next(
            r for r in response.context['rows'] if r['student'] == self.student
        )
        self.assertEqual(row['audience'], 'Nobody (silent)')

    def test_previewing_writes_nothing(self):
        """The load-bearing one. A preview that saved would stamp delivery
        state and leave the real send with nothing to do."""
        enable_reports(self.school, kind='school', weekly=True)

        self.client.get(URL)

        self.assertEqual(PeriodReport.objects.count(), 0)
        self.assertEqual(Notification.objects.count(), 0)
        self.assertEqual(len(mail.outbox), 0)

    def test_an_unconfigured_school_previews_an_empty_scope(self):
        response = self.client.get(URL)

        self.assertEqual(response.context['rows'], [])
        self.assertContains(response, 'has this report switched on')


class ManualSendTests(PreviewBase):
    def send(self, **extra):
        payload = {
            'school_id': self.school.id, 'period': periods.WEEKLY,
        }
        payload.update(extra)
        return self.client.post(URL, payload, follow=True)

    def test_sending_generates_and_notifies(self):
        enable_reports(self.school, kind='school', weekly=True)

        self.send()

        report = PeriodReport.objects.get(student=self.student)
        self.assertEqual(report.totals['avg_best_pct'], 90)
        recipients = set(Notification.objects.values_list('user_id', flat=True))
        self.assertEqual(recipients, {self.student.id, self.parent.id})

    def test_sending_works_for_a_manual_class_on_any_day(self):
        """Manual is a person saying "send now" — no schedule has to match."""
        enable_reports(
            self.school, kind='school', weekly=True, mode='manual',
            send_weekly_on=3,
        )

        self.send()

        self.assertEqual(PeriodReport.objects.count(), 2)

    def test_sending_twice_does_not_re_notify(self):
        enable_reports(self.school, kind='school', weekly=True)

        self.send()
        first = Notification.objects.count()
        self.send()

        self.assertEqual(Notification.objects.count(), first)

    def test_sending_with_nothing_configured_warns_rather_than_claiming_success(self):
        response = self.send()

        self.assertEqual(PeriodReport.objects.count(), 0)
        self.assertContains(response, 'nothing was sent')

    def test_an_unknown_period_is_rejected(self):
        response = self.send(period='fortnightly')
        self.assertContains(response, 'Unknown report period')

    def test_another_schools_scope_is_rejected(self):
        other = make_school(slug='pv-other', name='Other')
        response = self.client.post(URL, {
            'school_id': other.id, 'period': periods.WEEKLY,
        })
        self.assertEqual(response.status_code, 404)

    def test_the_send_is_audited(self):
        from audit.models import AuditLog

        enable_reports(self.school, kind='school', weekly=True)
        self.send()

        self.assertTrue(
            AuditLog.objects.filter(
                action='progress_reports_sent_manually',
            ).exists()
        )

    def test_no_template_syntax_leaks_into_the_page(self):
        enable_reports(self.school, kind='school', weekly=True)
        content = self.client.get(URL).content.decode()
        for token in ('{#', '{%', '{{'):
            self.assertNotIn(token, content, f'unrendered {token} in the page')
