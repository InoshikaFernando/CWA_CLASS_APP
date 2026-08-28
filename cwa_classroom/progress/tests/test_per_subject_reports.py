"""One report per student per subject per period (CPP-395).

The properties here are the ones that would hurt a family if they broke:
a student taking two subjects gets one report about each, a student in two
classes of ONE subject gets one report rather than two, and splitting an
already-sent report never re-notifies anybody.
"""

from datetime import timedelta

from django.core import mail
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from classroom.models import Notification, ProgressReportComment, Subject
from progress import periods
from progress.models import PeriodReport, ProgressReportSetting
from progress.services import run_period, students_for_period
from progress.tests.factories import (
    enable_reports, enrol, make_classroom, make_homework, make_school,
    make_user, submit,
)


def _subject(slug, name):
    subject, _ = Subject.objects.get_or_create(
        slug=slug, school=None, defaults={'name': name},
    )
    return subject


class PerSubjectBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.student = make_user('ps_student', first_name='Avisha', last_name='M')
        cls.maths = _subject('mathematics', 'Mathematics')
        cls.coding = _subject('coding', 'Coding')

        cls.maths_class = cls._class('Maths year 4', 'PS000001', cls.maths)
        cls.coding_tue = cls._class('Web Programing (Tue)', 'PS000002', cls.coding)
        cls.coding_wed = cls._class('Web Programing (Wed)', 'PS000003', cls.coding)
        for room in (cls.maths_class, cls.coding_tue, cls.coding_wed):
            enrol(room, cls.student)

        cls.start, cls.end = periods.previous_week(periods.today())
        cls.when = timezone.make_aware(timezone.datetime.combine(
            cls.start + timedelta(days=1),
            timezone.datetime.min.time().replace(hour=10),
        ))

        maths_hw = make_homework(cls.maths_class, due=cls.when, title='Fractions')
        submit(maths_hw, cls.student, 1, 8, when=cls.when)

        coding_hw = make_homework(cls.coding_tue, due=cls.when, title='Loops')
        coding_hw.subject_slug = 'coding'
        coding_hw.save(update_fields=['subject_slug'])
        submit(coding_hw, cls.student, 1, 9, when=cls.when)

    @classmethod
    def _class(cls, name, code, subject):
        room = make_classroom(cls.school, name=name, code=code)
        room.subject = subject
        room.save(update_fields=['subject'])
        return room


class SubjectSplitTests(PerSubjectBase):
    def test_two_subjects_produce_two_reports(self):
        enable_reports(self.school, kind='school', weekly=True)

        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        reports = PeriodReport.objects.filter(student=self.student)
        self.assertEqual(
            {r.subject.slug for r in reports}, {'mathematics', 'coding'},
        )
        self.assertEqual(reports.count(), 2)

    def test_two_classes_of_one_subject_produce_one_report(self):
        """The trap the class dropdown makes easy to fall into.

        Avisha is in Web Programing on Tuesday AND Wednesday. That is two
        classes but one subject, and her family should get one coding report.
        """
        enable_reports(self.school, kind='school', weekly=True)

        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        coding = PeriodReport.objects.filter(
            student=self.student, subject=self.coding,
        )
        self.assertEqual(coding.count(), 1)
        self.assertEqual(
            sorted(coding.first().data['scope']['classrooms']),
            ['Web Programing (Tue)', 'Web Programing (Wed)'],
        )

    def test_each_report_carries_only_its_own_subjects_homework(self):
        enable_reports(self.school, kind='school', weekly=True)
        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        coding = PeriodReport.objects.get(
            student=self.student, subject=self.coding,
        )
        maths = PeriodReport.objects.get(
            student=self.student, subject=self.maths,
        )
        self.assertEqual(coding.data['totals']['homework_attempted'], 1)
        self.assertEqual(maths.data['totals']['homework_attempted'], 1)
        self.assertEqual(coding.data['subject']['name'], 'Coding')

    def test_a_rerun_creates_nothing_further(self):
        """The widened key is still the cron's idempotency guarantee."""
        enable_reports(self.school, kind='school', weekly=True)
        run_period(periods.WEEKLY, self.start, self.end, notify=False)
        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        self.assertEqual(
            PeriodReport.objects.filter(student=self.student).count(), 2,
        )

    def test_the_plan_groups_classes_by_subject(self):
        enable_reports(self.school, kind='school', weekly=True)

        plan = students_for_period(periods.WEEKLY, school=self.school)

        by_subject = plan[self.student]['by_subject']
        self.assertEqual(len(by_subject), 2)
        self.assertEqual(len(by_subject[self.coding.id]), 2)


class MissingTeacherWorkTests(PerSubjectBase):
    """A report must never wait on manual work that nobody has done."""

    def test_a_report_generates_and_sends_with_no_teacher_comment(self):
        self.assertFalse(ProgressReportComment.objects.exists())
        enable_reports(
            self.school, kind='school', weekly=True,
            notify_student=True, notify_parents=True,
        )

        counts = run_period(periods.WEEKLY, self.start, self.end)

        self.assertEqual(counts['generated'], 2)
        self.assertTrue(counts['notified'])
        self.assertTrue(Notification.objects.exists())

    def test_the_snapshot_records_which_sections_it_carried(self):
        enable_reports(self.school, kind='school', weekly=True)
        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        report = PeriodReport.objects.filter(subject=self.coding).first()
        self.assertIn('sections_included', report.data)
        self.assertTrue(report.data['sections_included']['include_homework'])

    def test_a_section_switched_off_is_absent_from_the_snapshot(self):
        enable_reports(
            self.school, kind='school', weekly=True, include_awards=False,
        )
        run_period(periods.WEEKLY, self.start, self.end, notify=False)

        report = PeriodReport.objects.filter(subject=self.coding).first()
        self.assertFalse(report.data['sections_included']['include_awards'])
        self.assertEqual(report.data['awards'], [])

    def test_switching_a_section_off_later_does_not_rewrite_a_sent_report(self):
        """The snapshot is what the family read; settings move on, it does not."""
        enable_reports(self.school, kind='school', weekly=True)
        run_period(periods.WEEKLY, self.start, self.end, notify=False)
        report = PeriodReport.objects.filter(subject=self.coding).first()

        enable_reports(
            self.school, kind='school', weekly=True, include_homework=False,
        )
        report.refresh_from_db()

        self.assertTrue(report.sections_included['include_homework'])


class BackfillTests(PerSubjectBase):
    """Splitting history must not re-notify anybody."""

    def _legacy(self, notified=True):
        return PeriodReport.objects.create(
            student=self.student, school=self.school, subject=None,
            period_type=periods.WEEKLY,
            period_start=self.start, period_end=self.end,
            data={'scope': {'classroom_ids': [
                self.maths_class.id, self.coding_tue.id, self.coding_wed.id,
            ]}, 'totals': {'homework_attempted': 2}},
            notified_at=timezone.now() if notified else None,
        )

    def test_it_splits_a_legacy_report_by_subject(self):
        self._legacy()

        call_command('split_period_reports', verbosity=0)

        split = PeriodReport.objects.filter(
            student=self.student, subject__isnull=False,
        )
        self.assertEqual(
            {r.subject.slug for r in split}, {'mathematics', 'coding'},
        )

    def test_delivery_timestamps_carry_onto_every_child_row(self):
        """Without this, splitting one sent report re-notifies the family."""
        legacy = self._legacy(notified=True)

        call_command('split_period_reports', verbosity=0)

        for row in PeriodReport.objects.filter(subject__isnull=False):
            self.assertIsNotNone(
                row.notified_at,
                'a report split out of a sent one must not look unsent',
            )
            self.assertEqual(row.notified_at, legacy.notified_at)

    def test_the_original_is_left_intact(self):
        legacy = self._legacy()
        before = dict(legacy.data)

        call_command('split_period_reports', verbosity=0)

        legacy.refresh_from_db()
        self.assertEqual(legacy.data, before)
        self.assertIsNone(legacy.subject)

    def test_a_dry_run_writes_nothing(self):
        self._legacy()

        call_command('split_period_reports', '--dry-run', verbosity=0)

        self.assertEqual(
            PeriodReport.objects.filter(subject__isnull=False).count(), 0,
        )

    def test_running_twice_creates_nothing_further(self):
        self._legacy()

        call_command('split_period_reports', verbosity=0)
        call_command('split_period_reports', verbosity=0)

        self.assertEqual(
            PeriodReport.objects.filter(subject__isnull=False).count(), 2,
        )

    def test_no_email_is_sent_by_the_backfill(self):
        self._legacy()
        mail.outbox = []

        call_command('split_period_reports', verbosity=0)

        self.assertEqual(len(mail.outbox), 0)


class ContentCascadeTests(TestCase):
    def test_content_defaults_on_once_a_period_is_enabled(self):
        school = make_school()
        room = make_classroom(school, code='PS000020')
        enable_reports(school, kind='school', weekly=True)

        from progress import report_settings
        resolved = report_settings.effective(room)

        for field in ProgressReportSetting.CONTENT_FIELDS:
            self.assertTrue(resolved[field], f'{field} should default on')

    def test_content_resolves_off_for_a_class_that_generates_nothing(self):
        school = make_school()
        room = make_classroom(school, code='PS000021')

        from progress import report_settings
        resolved = report_settings.effective(room)

        for field in ProgressReportSetting.CONTENT_FIELDS:
            self.assertFalse(resolved[field])

    def test_a_class_can_opt_out_of_one_section(self):
        school = make_school()
        room = make_classroom(school, code='PS000022')
        enable_reports(school, kind='school', weekly=True)
        enable_reports(school, scope=room, kind='class', include_rubric=False)

        from progress import report_settings
        resolved = report_settings.effective(room)

        self.assertFalse(resolved['include_rubric'])
        self.assertTrue(resolved['include_homework'])
