"""The staff preview and manual send (CPP-388 follow-up).

Manual is the default mode, which only means something if staff can see what
they would be sending. The load-bearing property here is that a preview writes
nothing: a preview that created rows would stamp delivery state and leave the
real send with nothing to do.
"""

from datetime import date, datetime, time, timedelta

from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import Notification, SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.services import run_period
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

    def test_a_week_of_times_tables_is_activity_on_the_preview_too(self):
        """The preview must not answer this differently from the generator.

        `quiet` submits no homework but practises times tables. The preview
        used to test `totals['submissions']` — homework submissions and
        nothing else — while PeriodReport.has_activity, which actually gates
        notification and email, counts every strand. So this row read "No
        activity this period — nothing will be sent" and hid its "View report"
        link, and then the send went out anyway.

        Wrong in the direction that matters: it understated a child's week to
        their teacher, and misreported what the button was about to do. Worst
        for coding classes, where most work is practice and worksheets rather
        than homework.
        """
        from maths.models import StudentFinalAnswer

        row = StudentFinalAnswer.objects.create(
            student=self.quiet, quiz_type='times_table', table_number=7,
            operation='multiplication', score=8, total_questions=10, points=8,
        )
        StudentFinalAnswer.objects.filter(pk=row.pk).update(
            completed_at=at(self.window_start + timedelta(days=1)),
        )
        enable_reports(self.school, kind='school', weekly=True)

        response = self.client.get(URL)
        preview_row = next(
            r for r in response.context['rows'] if r['student'] == self.quiet
        )

        self.assertTrue(preview_row['has_activity'])
        self.assertNotEqual(preview_row['audience'], 'Nobody (silent)')

    def test_the_preview_and_the_generator_agree_on_who_is_active(self):
        """The property that keeps them from drifting apart again."""
        from progress.reports import has_activity

        enable_reports(self.school, kind='school', weekly=True)
        response = self.client.get(URL)

        start, end = periods.previous_week(periods.today())
        run_period(periods.WEEKLY, start, end, notify=False)

        for preview_row in response.context['rows']:
            report = PeriodReport.objects.filter(
                student=preview_row['student'], period_type=periods.WEEKLY,
                period_start=start, subject=preview_row['subject'],
            ).first()
            if report is None:
                continue
            self.assertEqual(
                preview_row['has_activity'], report.has_activity,
                f"preview and report disagree for {preview_row['student']}",
            )
            self.assertEqual(
                report.has_activity, has_activity(report.data),
            )

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


class PreviewSchoolScopeTests(TestCase):
    """A child at two institutes must not carry one school's work into the other.

    The sibling Student Progress Report page had exactly this leak — its
    per-student query had no school scope at all — so this asserts the preview
    does not, rather than assuming it.
    """

    @classmethod
    def setUpTestData(cls):
        cls.cwa = make_school(name='CWA', slug='cwa-preview')
        cls.mhm = make_school(name='MHM', slug='mhm-preview')
        cls.cwa_class = make_classroom(cls.cwa, name='CWA Maths', code='PVS00001')
        cls.mhm_class = make_classroom(cls.mhm, name='MHM Maths', code='PVS00002')

        cls.hoi = make_user('pvs_hoi', 'head_of_institute')
        for school in (cls.cwa, cls.mhm):
            SchoolTeacher.objects.create(
                school=school, teacher=cls.hoi, role='head_of_institute',
            )

        # One child at both schools, with work at each.
        cls.child = make_user('pvs_child', first_name='Dual', last_name='Enrolled')
        enrol(cls.cwa_class, cls.child)
        enrol(cls.mhm_class, cls.child)

        monday = periods.previous_week(periods.today())[0]
        cwa_hw = make_homework(cls.cwa_class, due=at(monday), title='CWA work')
        mhm_hw = make_homework(cls.mhm_class, due=at(monday), title='MHM work')
        submit(cwa_hw, cls.child, 1, 9, when=at(monday))
        submit(mhm_hw, cls.child, 1, 2, when=at(monday))

        enable_reports(cls.cwa, kind='school', weekly=True)
        enable_reports(cls.mhm, kind='school', weekly=True)

    def setUp(self):
        self.client.force_login(self.hoi)

    def row_for(self, school):
        response = self.client.get(URL, {'school': school.id})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['school'], school)
        return next(
            r for r in response.context['rows'] if r['student'] == self.child
        )

    def test_each_school_sees_only_its_own_work(self):
        cwa = self.row_for(self.cwa)
        self.assertEqual(cwa['classes'], [self.cwa_class.name])
        self.assertEqual(cwa['totals']['avg_best_pct'], 90)

        mhm = self.row_for(self.mhm)
        self.assertEqual(mhm['classes'], [self.mhm_class.name])
        self.assertEqual(mhm['totals']['avg_best_pct'], 20)

    def test_sending_for_one_school_reports_only_that_schools_work(self):
        self.client.post(URL, {
            'school_id': self.cwa.id, 'period': periods.WEEKLY,
        }, follow=True)

        report = PeriodReport.objects.get(student=self.child)
        self.assertEqual(report.school, self.cwa)
        self.assertEqual(report.data['scope']['classrooms'], [self.cwa_class.name])
        self.assertEqual(report.totals['avg_best_pct'], 90)


class EmptyScopeReasonTests(PreviewBase):
    """An empty preview must say which of three different things happened.

    The page rendered one sentence — "No class in this scope has this report
    switched on" — for every empty result, so a head of institute whose class
    was already switched on was sent to Report Automation to turn on something
    that was already on. Found on the test site: a coding class previewed empty
    and the page named the one cause it had not checked.
    """

    def test_a_class_with_reports_off_says_to_switch_them_on(self):
        response = self.client.get(URL, {'classroom': self.classroom.id})

        self.assertEqual(response.context['rows'], [])
        self.assertEqual(response.context['empty_reason'], 'not_enabled')
        self.assertContains(response, 'has this report switched on')

    def test_an_enabled_class_with_no_students_says_so_instead(self):
        enable_reports(self.school, kind='school', weekly=True)
        empty = make_classroom(self.school, name='Web Programming', code='RPT00009')

        response = self.client.get(URL, {'classroom': empty.id})

        self.assertEqual(response.context['rows'], [])
        self.assertEqual(response.context['empty_reason'], 'no_students')
        self.assertContains(response, 'no active students')
        # The old message would have sent them to switch on what is already on.
        self.assertNotContains(response, 'has this report switched on')

    def test_a_term_that_has_not_finished_is_reported_as_the_window_it_is(self):
        """The one empty case the page already got right — pinned, not changed.

        A missing term window is shown by the ``period_label`` branch further
        up the template, which short-circuits before the empty-rows block. So
        this never wore the settings message, and must not start wearing it.
        """
        enable_reports(self.school, kind='school', term=True)

        response = self.client.get(URL, {'period': periods.TERM})

        self.assertIsNone(response.context['start'])
        self.assertEqual(response.context['empty_reason'], 'no_period')
        self.assertContains(response, 'No term has ended yet')
        self.assertNotContains(response, 'has this report switched on')

    def test_a_scope_with_rows_reports_no_reason_at_all(self):
        enable_reports(self.school, kind='school', weekly=True)

        response = self.client.get(URL)

        self.assertTrue(response.context['rows'])
        self.assertIsNone(response.context['empty_reason'])
