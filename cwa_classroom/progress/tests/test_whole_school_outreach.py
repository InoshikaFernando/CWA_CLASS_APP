"""Whole-school report sending, and the note for families with nothing (CPP-422).

The point of the feature is that nobody in a covered school is silently
skipped, so most of what is worth asserting here is about the people the old
run left out: the student in no reporting class, the one whose subscription was
never activated, and the one who simply did nothing. Each of them has to end up
with a note that says which of those it was.
"""

from datetime import datetime, time, timedelta

from django.core import mail
from django.test import TestCase
from django.utils import timezone

from billing.models import DiscountCode, Subscription
from classroom.models import SchoolTeacher
from progress import outreach, periods, report_settings
from progress.models import PeriodReportNotice, ProgressReportSetting
from progress.services import run_period
from progress.tests.factories import (
    enable_reports, enrol, join_school, link_parent, make_classroom,
    make_homework, make_school, make_user, submit,
)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


def subscribe(student, status=Subscription.STATUS_ACTIVE):
    return Subscription.objects.create(user=student, status=status)


class OutreachBase(TestCase):
    """One school, one reporting class, four kinds of student.

    * ``worker`` — subscribed, in the class, did homework. Gets a real report.
    * ``idle`` — subscribed, in the class, did nothing.
    * ``unpaid`` — in the class, never subscribed.
    * ``classless`` — at the school, in no class at all.
    """

    @classmethod
    def setUpTestData(cls):
        cls.school = make_school(slug='ws-school', name='Whole School')
        cls.classroom = make_classroom(cls.school, code='WS000001')
        cls.hoi = make_user('ws_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )

        cls.worker = make_user('ws_worker', first_name='Ada', last_name='A')
        cls.idle = make_user('ws_idle', first_name='Bea', last_name='B')
        cls.unpaid = make_user('ws_unpaid', first_name='Cal', last_name='C')
        cls.classless = make_user('ws_classless', first_name='Dee', last_name='D')

        for student in (cls.worker, cls.idle, cls.unpaid, cls.classless):
            join_school(cls.school, student)
            parent = make_user(f'{student.username}_parent', 'parent')
            link_parent(parent, student, school=cls.school)

        for student in (cls.worker, cls.idle, cls.unpaid):
            enrol(cls.classroom, student)

        subscribe(cls.worker)
        subscribe(cls.idle)
        # cls.unpaid and cls.classless deliberately have no Subscription row.

        cls.start, cls.end = periods.previous_week(periods.today())
        homework = make_homework(cls.classroom, due=at(cls.start + timedelta(days=2)))
        submit(
            homework, cls.worker, attempt=1, score=8,
            when=at(cls.start + timedelta(days=1)),
        )

    def run_week(self, **kwargs):
        return run_period(
            periods.WEEKLY, self.start, self.end, school=self.school, **kwargs,
        )

    def cover(self, **flags):
        """Switch the weekly report on, and whole-school coverage with it."""
        values = {'weekly': True, 'whole_school': True}
        values.update(flags)
        return enable_reports(self.school, **values)


class CoverageSettingTests(OutreachBase):
    def test_off_by_default(self):
        """An install that says nothing covers nobody extra."""
        enable_reports(self.school, weekly=True)

        flags = report_settings.outreach(self.school)
        self.assertFalse(flags['whole_school'])
        self.assertFalse(flags['email_parents_no_data'])

    def test_email_defaults_on_with_coverage(self):
        self.cover()

        flags = report_settings.outreach(self.school)
        self.assertTrue(flags['whole_school'])
        self.assertTrue(flags['email_parents_no_data'])

    def test_email_can_be_switched_off_on_its_own(self):
        self.cover(email_parents_no_data=False)

        flags = report_settings.outreach(self.school)
        self.assertTrue(flags['whole_school'])
        self.assertFalse(flags['email_parents_no_data'])

    def test_email_flag_is_meaningless_without_coverage(self):
        """A tick left behind on a school that turned coverage back off."""
        enable_reports(
            self.school, weekly=True,
            whole_school=False, email_parents_no_data=True,
        )

        self.assertEqual(
            report_settings.outreach(self.school),
            {'whole_school': False, 'email_parents_no_data': False},
        )

    def test_read_from_the_school_row_only(self):
        """A class-level tick is not how coverage is decided."""
        enable_reports(self.school, weekly=True)
        enable_reports(
            self.school, scope=self.classroom, kind='class',
            whole_school=True,
        )

        self.assertFalse(report_settings.covers_whole_school(self.school))

    def test_unknown_school_covers_nobody(self):
        self.assertEqual(
            report_settings.outreach(None),
            {'whole_school': False, 'email_parents_no_data': False},
        )


class ReasonTests(OutreachBase):
    def test_no_subscription_beats_no_activity(self):
        """A family who never got through the paywall was not merely idle."""
        self.assertEqual(
            outreach.reason_for(self.unpaid), outreach.REASON_NO_SUBSCRIPTION,
        )

    def test_cancelled_subscription_is_not_a_subscription(self):
        subscribe(self.classless, status=Subscription.STATUS_CANCELLED)

        self.assertEqual(
            outreach.reason_for(self.classless),
            outreach.REASON_NO_SUBSCRIPTION,
        )

    def test_trialing_counts_as_subscribed(self):
        student = make_user('ws_trial')
        subscribe(student, status=Subscription.STATUS_TRIALING)

        self.assertEqual(
            outreach.reason_for(student), outreach.REASON_NO_ACTIVITY,
        )

    def test_cohort_is_everyone_with_nothing_to_show(self):
        cohort = dict(outreach.no_data_cohort(self.school, {self.worker.id}))

        self.assertEqual(
            {student.username for student in cohort},
            {'ws_idle', 'ws_unpaid', 'ws_classless'},
        )
        self.assertEqual(cohort[self.idle], outreach.REASON_NO_ACTIVITY)
        self.assertEqual(cohort[self.unpaid], outreach.REASON_NO_SUBSCRIPTION)
        self.assertEqual(cohort[self.classless], outreach.REASON_NO_SUBSCRIPTION)

    def test_inactive_enrolment_is_left_alone(self):
        """A leaver the school deactivated stays left alone."""
        from classroom.models import SchoolStudent

        SchoolStudent.objects.filter(
            school=self.school, student=self.classless,
        ).update(is_active=False)

        cohort = dict(outreach.no_data_cohort(self.school, {self.worker.id}))
        self.assertNotIn(self.classless, cohort)


class RunTests(OutreachBase):
    def test_coverage_off_changes_nothing(self):
        enable_reports(self.school, weekly=True)
        mail.outbox = []

        counts = self.run_week()

        self.assertEqual(counts['notices'], 0)
        self.assertEqual(PeriodReportNotice.objects.count(), 0)
        self.assertEqual(mail.outbox, [])

    def test_coverage_reaches_everyone_with_nothing_to_show(self):
        self.cover()
        mail.outbox = []

        counts = self.run_week()

        self.assertEqual(counts['notices'], 3)
        self.assertEqual(counts['notices_emailed'], 3)
        self.assertEqual(counts['notices_recipients'], 3)
        self.assertEqual(
            counts['notices_by_reason'],
            {outreach.REASON_NO_SUBSCRIPTION: 2, outreach.REASON_NO_ACTIVITY: 1},
        )
        self.assertEqual(
            set(PeriodReportNotice.objects.values_list(
                'student__username', flat=True)),
            {'ws_idle', 'ws_unpaid', 'ws_classless'},
        )

    def test_the_student_with_a_real_report_gets_no_note(self):
        self.cover()

        self.run_week()

        self.assertFalse(
            PeriodReportNotice.objects.filter(student=self.worker).exists()
        )

    def test_one_note_per_student_not_per_subject(self):
        """A second reporting class must not double the note."""
        second = make_classroom(self.school, name='Year 5 Coding', code='WS000002')
        enrol(second, self.idle)
        self.cover()
        mail.outbox = []

        self.run_week()

        self.assertEqual(
            PeriodReportNotice.objects.filter(student=self.idle).count(), 1,
        )
        self.assertEqual(
            len([m for m in mail.outbox if 'Bea' in m.subject]), 1,
        )

    def test_rerunning_re_mails_nobody(self):
        self.cover()
        self.run_week()
        mail.outbox = []

        counts = self.run_week()

        self.assertEqual(counts['notices'], 3)
        self.assertEqual(counts['notices_emailed'], 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(PeriodReportNotice.objects.count(), 3)

    def test_email_off_records_the_cohort_and_writes_to_nobody(self):
        self.cover(email_parents_no_data=False)
        mail.outbox = []

        counts = self.run_week()

        self.assertEqual(counts['notices'], 3)
        self.assertEqual(counts['notices_emailed'], 0)
        self.assertEqual(mail.outbox, [])
        self.assertEqual(PeriodReportNotice.objects.count(), 3)

    def test_no_notify_silences_the_notes_too(self):
        self.cover()
        mail.outbox = []

        counts = self.run_week(notify=False)

        self.assertEqual(counts['notices'], 3)
        self.assertEqual(counts['notices_emailed'], 0)
        self.assertEqual(mail.outbox, [])

    def test_a_single_class_run_is_not_a_whole_school_run(self):
        self.cover()

        counts = self.run_week(classroom=self.classroom)

        self.assertEqual(counts['notices'], 0)
        self.assertEqual(PeriodReportNotice.objects.count(), 0)

    def test_subscribed_only_run_does_not_write_to_the_unsubscribed(self):
        """The filter's entire purpose is to leave them out."""
        self.cover()

        counts = self.run_week(subscribed_only=True)

        self.assertEqual(counts['notices'], 0)
        self.assertEqual(PeriodReportNotice.objects.count(), 0)

    def test_a_family_with_no_email_is_counted_not_crashed_on(self):
        from classroom.models import ParentStudent

        ParentStudent.objects.filter(student=self.classless).update(is_active=False)
        self.cover()

        counts = self.run_week()

        self.assertEqual(counts['notices'], 3)
        self.assertEqual(counts['notices_emailed'], 2)
        self.assertEqual(counts['notices_undelivered'], 1)
        notice = PeriodReportNotice.objects.get(student=self.classless)
        self.assertEqual(notice.recipients, 0)

    def test_dry_run_writes_nothing(self):
        self.cover()
        mail.outbox = []

        counts = self.run_week(dry_run=True)

        self.assertEqual(PeriodReportNotice.objects.count(), 0)
        self.assertEqual(mail.outbox, [])
        # The classless student is the one no enabled class holds, so the
        # dry-run floor finds exactly them.
        self.assertEqual(counts['notices'], 1)

    def test_a_school_that_reports_nothing_tonight_is_not_mailed(self):
        """Coverage widens a send that is happening; it does not create one."""
        enable_reports(self.school, whole_school=True)

        counts = self.run_week()

        self.assertEqual(counts['classes'], 0)
        self.assertEqual(counts['notices'], 0)
        self.assertEqual(PeriodReportNotice.objects.count(), 0)


class EmailContentTests(OutreachBase):
    #: The reason sentence, as one line. The template wraps it across three
    #: source lines, so an assertion on the raw body has to be whitespace-blind
    #: or it tests the indentation rather than the wording.
    NO_SUBSCRIPTION_PHRASE = 'their subscription isn\u2019t active yet'
    NO_ACTIVITY_PHRASE = 'no homework, quizzes or practice were completed'

    def _body_for(self, student):
        """This student's note, whitespace-collapsed, HTML part included."""
        name = student.get_full_name()
        for message in mail.outbox:
            if name in message.subject:
                raw = message.body + ''.join(
                    str(alt[0]) for alt in getattr(message, 'alternatives', [])
                )
                return ' '.join(raw.replace('<strong>', '')
                                   .replace('</strong>', '').split())
        return ''

    def test_unsubscribed_family_gets_the_reason_and_the_code(self):
        DiscountCode.objects.create(code='WSFAM50', discount_percent=50)
        self.school.subscription_discount_code = 'WSFAM50'
        self.school.save(update_fields=['subscription_discount_code'])
        self.cover()
        mail.outbox = []

        self.run_week()

        body = self._body_for(self.unpaid)
        self.assertIn(self.NO_SUBSCRIPTION_PHRASE, body)
        self.assertIn('WSFAM50', body)
        self.assertIn('50% off', body)

    def test_idle_family_gets_no_discount_code(self):
        DiscountCode.objects.create(code='WSFAM51', discount_percent=50)
        self.school.subscription_discount_code = 'WSFAM51'
        self.school.save(update_fields=['subscription_discount_code'])
        self.cover()
        mail.outbox = []

        self.run_week()

        body = self._body_for(self.idle)
        self.assertNotIn('WSFAM51', body)
        self.assertNotIn(self.NO_SUBSCRIPTION_PHRASE, body)
        self.assertIn(self.NO_ACTIVITY_PHRASE, body)

    def test_an_expired_code_is_not_offered(self):
        DiscountCode.objects.create(
            code='WSOLD50', discount_percent=50,
            expires_at=timezone.now() - timedelta(days=1),
        )
        self.school.subscription_discount_code = 'WSOLD50'
        self.school.save(update_fields=['subscription_discount_code'])
        self.cover()
        mail.outbox = []

        self.run_week()

        body = self._body_for(self.unpaid)
        self.assertNotIn('WSOLD50', body)
        # The note still goes, and still gives the reason: a dead code costs
        # the offer, never the email.
        self.assertIn(self.NO_SUBSCRIPTION_PHRASE, body)

    def test_an_exhausted_code_is_not_offered(self):
        DiscountCode.objects.create(
            code='WSUSED50', discount_percent=50, max_uses=1, uses=1,
        )
        self.school.subscription_discount_code = 'WSUSED50'
        self.school.save(update_fields=['subscription_discount_code'])

        self.assertEqual(
            outreach.notice_context(
                self.unpaid, self.school, 'Week', outreach.REASON_NO_SUBSCRIPTION,
            )['discount_code'],
            '',
        )

    def test_no_code_configured_still_sends_the_note(self):
        self.cover()
        mail.outbox = []

        self.run_week()

        context = outreach.notice_context(
            self.unpaid, self.school, 'Week', outreach.REASON_NO_SUBSCRIPTION,
        )
        self.assertEqual(context['discount_code'], '')
        self.assertTrue(self._body_for(self.unpaid))


class SettingsFormTests(OutreachBase):
    """The two switches are offered where they are read, and nowhere else."""

    def setUp(self):
        self.client.force_login(self.hoi)

    def test_school_form_offers_coverage(self):
        response = self.client.get(
            f'/progress/reports/settings/?school={self.school.id}')

        self.assertEqual(response.status_code, 200)
        fields = [
            switch['field']
            for group in response.context['school_switch_groups']
            for switch in group['switches']
        ]
        self.assertIn('whole_school', fields)
        self.assertIn('email_parents_no_data', fields)

    def test_class_and_department_forms_do_not(self):
        response = self.client.get(
            f'/progress/reports/settings/?school={self.school.id}')

        fields = [
            switch['field']
            for group in response.context['switch_groups']
            for switch in group['switches']
        ]
        self.assertNotIn('whole_school', fields)
        self.assertNotIn('email_parents_no_data', fields)

    def test_saving_the_school_form_switches_coverage_on(self):
        response = self.client.post('/progress/reports/settings/', {
            'scope': 'school', 'school_id': self.school.id,
            'weekly': 'on', 'whole_school': 'on',
            'email_parents_no_data': 'on',
        })

        self.assertEqual(response.status_code, 302)
        self.assertTrue(report_settings.covers_whole_school(self.school))

    def test_a_class_post_cannot_set_coverage(self):
        self.client.post('/progress/reports/settings/', {
            'scope': 'class', 'school_id': self.school.id,
            'classroom_id': self.classroom.id,
            'weekly': 'on', 'whole_school': 'on',
        })

        row = ProgressReportSetting.objects.get(classroom=self.classroom)
        self.assertIsNone(row.whole_school)
        self.assertFalse(report_settings.covers_whole_school(self.school))


class PreviewTests(OutreachBase):
    URL = '/progress/reports/preview/'

    def setUp(self):
        self.client.force_login(self.hoi)

    def query(self, **extra):
        params = {'school': self.school.id, 'period': periods.WEEKLY}
        params.update(extra)
        return self.URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

    def test_cohort_is_listed_with_its_reason(self):
        self.cover()

        response = self.client.get(self.query())

        rows = {
            row['student'].username: row['reason']
            for row in response.context['no_data_rows']
        }
        self.assertEqual(rows, {
            'ws_idle': outreach.REASON_NO_ACTIVITY,
            'ws_unpaid': outreach.REASON_NO_SUBSCRIPTION,
            'ws_classless': outreach.REASON_NO_SUBSCRIPTION,
        })

    def test_nothing_listed_when_coverage_is_off(self):
        enable_reports(self.school, weekly=True)

        response = self.client.get(self.query())

        self.assertEqual(response.context['no_data_rows'], [])

    def test_the_page_and_the_send_agree_on_a_filtered_scope(self):
        """Both skip the cohort for a single class and for subscribed-only."""
        self.cover()

        by_class = self.client.get(self.query(classroom=self.classroom.id))
        subscribed = self.client.get(self.query(subscribed='1'))

        self.assertEqual(by_class.context['no_data_rows'], [])
        self.assertEqual(subscribed.context['no_data_rows'], [])

    def test_already_sent_is_marked(self):
        self.cover()
        self.run_week()

        response = self.client.get(self.query())

        self.assertTrue(
            all(row['already_sent'] for row in response.context['no_data_rows'])
        )

    def test_sending_from_the_page_covers_the_school(self):
        self.cover()
        mail.outbox = []

        self.client.post(self.URL, {
            'school_id': self.school.id, 'period': periods.WEEKLY,
        })

        self.assertEqual(PeriodReportNotice.objects.count(), 3)


class EmptyRowWordingTests(OutreachBase):
    """What the main table says about a student whose report is empty (CPP-426).

    The table is one row per student per subject; the cohort panel below it is
    one row per student. They are built from the same computed cohort here
    precisely so they cannot say opposite things about the same evening — the
    table used to read "nothing will be sent" for a family whose note was
    already queued.
    """

    URL = '/progress/reports/preview/'

    def setUp(self):
        self.client.force_login(self.hoi)

    def rows(self, **extra):
        params = {'school': self.school.id, 'period': periods.WEEKLY}
        params.update(extra)
        query = '&'.join(f'{k}={v}' for k, v in params.items())
        response = self.client.get(f'{self.URL}?{query}')
        return response, {
            row['student'].username: row for row in response.context['rows']
        }

    def test_coverage_off_keeps_the_old_wording(self):
        enable_reports(self.school, weekly=True)

        response, rows = self.rows()

        self.assertIsNone(rows['ws_idle'].get('notice_reason'))
        self.assertContains(response, 'nothing will be sent')

    def test_an_idle_student_says_their_parents_get_a_note(self):
        self.cover()

        response, rows = self.rows()

        self.assertEqual(
            rows['ws_idle']['notice_reason'], outreach.REASON_NO_ACTIVITY,
        )
        self.assertContains(response, 'their parents will be sent a')
        self.assertNotContains(response, 'nothing will be sent')

    def test_an_unsubscribed_student_says_which_reason(self):
        self.cover()

        _response, rows = self.rows()

        self.assertEqual(
            rows['ws_unpaid']['notice_reason'],
            outreach.REASON_NO_SUBSCRIPTION,
        )
        self.assertTrue(rows['ws_unpaid']['notice_no_subscription'])

    def test_the_will_send_to_column_names_the_parents(self):
        """The one column a reader checks to answer exactly this."""
        self.cover()

        _response, rows = self.rows()

        self.assertEqual(rows['ws_idle']['audience'], 'Parents (note)')

    def test_with_the_note_switched_off_the_row_says_nobody_is_written_to(self):
        self.cover(email_parents_no_data=False)

        response, rows = self.rows()

        self.assertEqual(
            rows['ws_idle']['notice_reason'], outreach.REASON_NO_ACTIVITY,
        )
        # Covered, but silent — and the row says which, rather than implying
        # a note that is not coming.
        self.assertEqual(rows['ws_idle']['audience'], '—')
        self.assertContains(response, 'the note is')

    def test_an_already_sent_note_is_marked_on_the_row(self):
        self.cover()
        self.run_week()

        response, rows = self.rows()

        self.assertTrue(rows['ws_idle']['notice_already_sent'])
        self.assertContains(response, 'already sent')

    def test_a_student_with_activity_is_untouched(self):
        self.cover()

        _response, rows = self.rows()

        self.assertTrue(rows['ws_worker']['has_activity'])
        self.assertIsNone(rows['ws_worker'].get('notice_reason'))

    def test_an_empty_subject_for_an_active_student_still_sends_nothing(self):
        """Empty row, but the student has something to show elsewhere.

        A child with maths activity and an empty coding report is not in the
        cohort — no note goes out — so that coding row must keep the original
        wording rather than promise one.
        """
        from classroom.models import Subject

        coding, _ = Subject.objects.get_or_create(
            slug='coding', school=None, defaults={'name': 'Coding'},
        )
        second = make_classroom(self.school, name='Y5 Coding', code='WS000003')
        second.subject = coding
        second.save(update_fields=['subject'])
        enrol(second, self.worker)
        self.cover()

        _response, rows = self.rows()

        empty = [
            row for row in _response.context['rows']
            if row['student'] == self.worker and not row['has_activity']
        ]
        self.assertTrue(empty, 'expected an empty coding row for the worker')
        for row in empty:
            self.assertIsNone(row.get('notice_reason'))
