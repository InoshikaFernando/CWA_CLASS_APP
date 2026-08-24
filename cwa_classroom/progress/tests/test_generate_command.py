"""The nightly generator: idempotency, notification and the term email (CPP-388)."""

from datetime import date, datetime, time

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.utils import timezone
from io import StringIO

from classroom.models import AcademicYear, Notification, Term
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import (
    enrol, link_parent, make_classroom, make_homework, make_school, make_user,
    submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)
MONDAY_AFTER = date(2026, 8, 24)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


def run(*args, **options):
    out = StringIO()
    call_command('generate_progress_reports', *args, stdout=out, **options)
    return out.getvalue()


class GenerateBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('gen_student')
        cls.parent = make_user('gen_parent', 'parent')
        enrol(cls.classroom, cls.student)
        link_parent(cls.parent, cls.student, cls.school)

        cls.homework = make_homework(cls.classroom, due=at(date(2026, 8, 21)))

    def with_activity(self):
        submit(self.homework, self.student, 1, 4, when=at(date(2026, 8, 18)))
        submit(self.homework, self.student, 2, 9, when=at(date(2026, 8, 19)))


class WeeklyGenerationTests(GenerateBase):
    def test_a_monday_run_generates_the_week_that_closed(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())

        report = PeriodReport.objects.get(
            student=self.student, period_type=periods.WEEKLY,
        )
        self.assertEqual(report.period_start, START)
        self.assertEqual(report.period_end, END)
        self.assertEqual(report.totals['avg_best_pct'], 90)
        self.assertEqual(report.school, self.school)

    def test_a_midweek_run_generates_nothing_and_says_so(self):
        self.with_activity()
        output = run('--date', '2026-08-26')

        self.assertEqual(PeriodReport.objects.count(), 0)
        self.assertIn('No period closed', output)

    def test_rerunning_does_not_duplicate_or_re_notify(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())
        first_count = Notification.objects.filter(
            notification_type='progress_report').count()

        run('--date', MONDAY_AFTER.isoformat())

        self.assertEqual(PeriodReport.objects.count(), 1)
        self.assertEqual(
            Notification.objects.filter(notification_type='progress_report').count(),
            first_count,
        )

    def test_force_recomputes_the_snapshot_without_re_notifying(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())
        report = PeriodReport.objects.get(student=self.student)
        notified_at = report.notified_at

        # A late third attempt lands inside the same window (e.g. a grading fix).
        submit(self.homework, self.student, 3, 10, when=at(date(2026, 8, 20)))
        run('--date', MONDAY_AFTER.isoformat(), '--force')

        report.refresh_from_db()
        self.assertEqual(report.totals['avg_best_pct'], 100)
        self.assertEqual(report.notified_at, notified_at)

    def test_dry_run_writes_nothing(self):
        self.with_activity()
        output = run('--date', MONDAY_AFTER.isoformat(), '--dry-run')

        self.assertEqual(PeriodReport.objects.count(), 0)
        self.assertIn('Would generate', output)

    def test_no_notify_generates_the_report_but_stays_quiet(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat(), '--no-notify')

        report = PeriodReport.objects.get(student=self.student)
        self.assertIsNone(report.notified_at)
        self.assertEqual(Notification.objects.count(), 0)

    def test_an_explicit_period_reports_the_last_closed_window(self):
        self.with_activity()
        run('--period', periods.WEEKLY, '--date', '2026-08-26')  # a Wednesday

        report = PeriodReport.objects.get(student=self.student)
        self.assertEqual(report.period_start, date(2026, 8, 17))

    def test_a_bad_date_is_rejected_rather_than_guessed_at(self):
        with self.assertRaises(CommandError):
            run('--date', '24/08/2026')


class NotificationTests(GenerateBase):
    def test_both_the_student_and_the_parent_are_notified(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())

        recipients = set(
            Notification.objects
            .filter(notification_type='progress_report')
            .values_list('user_id', flat=True)
        )
        self.assertEqual(recipients, {self.student.id, self.parent.id})

    def test_the_notification_links_to_the_report(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())

        report = PeriodReport.objects.get(student=self.student)
        notification = Notification.objects.filter(user=self.student).first()
        self.assertEqual(notification.link, f'/progress/reports/{report.id}/')

    def test_a_weekly_report_sends_no_email(self):
        self.with_activity()
        run('--date', MONDAY_AFTER.isoformat())
        self.assertEqual(len(mail.outbox), 0)

    def test_an_empty_period_still_gets_a_report_but_no_notification(self):
        run('--date', MONDAY_AFTER.isoformat())

        report = PeriodReport.objects.get(student=self.student)
        self.assertFalse(report.has_activity)
        self.assertIsNone(report.notified_at)
        self.assertEqual(Notification.objects.count(), 0)


@override_settings(SITE_URL='https://example.test', DAILY_EMAIL_LIMIT=0)
class TermReportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('term_student')
        cls.parent = make_user('term_parent', 'parent')
        enrol(cls.classroom, cls.student)
        link_parent(cls.parent, cls.student, cls.school)

        cls.year = AcademicYear.objects.create(
            school=cls.school, year=2026,
            start_date=date(2026, 2, 1), end_date=date(2026, 12, 15),
        )
        cls.term = Term.objects.create(
            school=cls.school, academic_year=cls.year, name='Term 3',
            start_date=date(2026, 7, 20), end_date=date(2026, 9, 25),
        )
        homework = make_homework(cls.classroom, due=at(date(2026, 8, 21)))
        submit(homework, cls.student, 1, 5, when=at(date(2026, 8, 18)))
        submit(homework, cls.student, 2, 9, when=at(date(2026, 8, 19)))

    def test_the_term_report_is_generated_the_day_after_it_ends(self):
        run('--date', '2026-09-26')

        report = PeriodReport.objects.get(
            student=self.student, period_type=periods.TERM,
        )
        self.assertEqual(report.term, self.term)
        self.assertEqual(report.period_start, self.term.start_date)
        self.assertEqual(report.period_end, self.term.end_date)

    def test_the_parent_is_emailed_at_term_end(self):
        run('--date', '2026-09-26')

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, [self.parent.email])
        self.assertIn('Term 3 2026', message.subject)

    def test_the_email_is_sent_once_even_if_the_cron_repeats(self):
        run('--date', '2026-09-26')
        run('--date', '2026-09-26')
        self.assertEqual(len(mail.outbox), 1)

    def test_the_email_carries_the_report_and_pdf_links(self):
        run('--date', '2026-09-26')

        report = PeriodReport.objects.get(period_type=periods.TERM)
        body = mail.outbox[0].alternatives[0][0]
        self.assertIn(f'https://example.test/progress/reports/{report.id}/', body)
        self.assertIn(f'/progress/reports/{report.id}/pdf/', body)

    def test_asking_for_a_term_before_any_has_ended_is_an_error_not_a_silent_no_op(self):
        with self.assertRaises(CommandError):
            run('--period', periods.TERM, '--date', '2026-03-01')

    def test_a_term_with_no_submissions_sends_no_email(self):
        # "0% across 0 homework" reads as a broken system, not as news.
        quiet = make_user('term_quiet')
        quiet_parent = make_user('term_quiet_parent', 'parent')
        enrol(self.classroom, quiet)
        link_parent(quiet_parent, quiet, self.school)

        run('--date', '2026-09-26')

        report = PeriodReport.objects.get(student=quiet, period_type=periods.TERM)
        self.assertFalse(report.has_activity)
        self.assertIsNone(report.parent_emailed_at)
        self.assertNotIn(quiet_parent.email, [to for m in mail.outbox for to in m.to])

    def test_a_student_with_no_parent_link_is_not_a_failure(self):
        orphan = make_user('term_orphan')
        enrol(self.classroom, orphan)

        run('--date', '2026-09-26')

        report = PeriodReport.objects.get(student=orphan, period_type=periods.TERM)
        self.assertIsNotNone(report)


class CohortCacheTests(GenerateBase):
    """The cohort figures behind the awards are shared across a class.

    Without the shared cache, a class of 25 recomputes the identical cohort 25
    times on every nightly run — invisible in correctness, expensive at scale.
    """

    def test_a_class_cohort_is_computed_once_per_run(self):
        from unittest.mock import patch

        classmates = [make_user(f'gen_mate{i}') for i in range(3)]
        for mate in classmates:
            enrol(self.classroom, mate)
            submit(self.homework, mate, 1, 6, when=at(date(2026, 8, 18)))
        self.with_activity()

        from progress import reports

        with patch.object(
            reports, '_compute_cohort_stats',
            wraps=reports._compute_cohort_stats,
        ) as computed:
            run('--date', MONDAY_AFTER.isoformat())

        self.assertEqual(PeriodReport.objects.count(), 4)
        self.assertEqual(computed.call_count, 1)
