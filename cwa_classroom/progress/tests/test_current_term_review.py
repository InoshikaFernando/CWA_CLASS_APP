"""Reviewing a term that is still running (CPP-425).

CPP-388 only ever resolved "the term that just finished", so a school in the
middle of a term had nothing to open and a teacher could not see how a class was
tracking until it was too late to act on it.

The load-bearing rule here is the one that keeps this safe: a running term can
be *reviewed* as often as anyone likes and can never be *sent*. A term report
keys on the term's START date, so a row stored mid-term is the row the real
end-of-term report needs — ``generate_report`` would find it and hand it back
untouched, and both delivery stamps are no-ops once set. The family would simply
never receive their end-of-term report.
"""

from datetime import date, datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from classroom.models import AcademicYear, SchoolTeacher, Term
from progress import periods
from progress.models import PeriodReport
from progress.services import PartialWindowError, generate_report, run_period
from progress.tests.factories import (
    enable_reports, enrol, link_parent, make_classroom, make_homework,
    make_school, make_user, submit,
)

URL = '/progress/reports/preview/'
DETAIL_URL = '/progress/reports/preview/report/'


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class CurrentTermBase(TestCase):
    """A school mid-term, with one finished term behind it."""

    @classmethod
    def setUpTestData(cls):
        cls.today = periods.today()
        cls.school = make_school(slug='term-school', name='Term School')
        cls.classroom = make_classroom(cls.school, code='TERM0001')
        cls.hoi = make_user('ct_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('ct_student', first_name='Ada', last_name='A')
        cls.parent = make_user('ct_parent', 'parent')
        enrol(cls.classroom, cls.student)
        link_parent(cls.parent, cls.student, cls.school)

        cls.year = AcademicYear.objects.create(
            school=cls.school, year=cls.today.year,
            start_date=cls.today - timedelta(days=300),
            end_date=cls.today + timedelta(days=65),
        )
        cls.finished = Term.objects.create(
            school=cls.school, academic_year=cls.year, name='Term 1', order=1,
            start_date=cls.today - timedelta(days=120),
            end_date=cls.today - timedelta(days=40),
        )
        cls.running = Term.objects.create(
            school=cls.school, academic_year=cls.year, name='Term 2', order=2,
            start_date=cls.today - timedelta(days=30),
            end_date=cls.today + timedelta(days=30),
        )

        # Work inside the running term, a fortnight ago.
        homework = make_homework(
            cls.classroom, due=at(cls.today - timedelta(days=14)),
        )
        submit(
            homework, cls.student, 1, 7,
            when=at(cls.today - timedelta(days=14)),
        )

    def setUp(self):
        self.client.force_login(self.hoi)
        enable_reports(self.school, kind='school', term=True)


class WindowTests(CurrentTermBase):
    def test_a_running_term_is_reviewable(self):
        terms = periods.reviewable_terms(self.school, self.today)

        self.assertEqual(terms, [self.running, self.finished])

    def test_a_term_that_has_not_started_is_not(self):
        Term.objects.create(
            school=self.school, academic_year=self.year, name='Term 3', order=3,
            start_date=self.today + timedelta(days=40),
            end_date=self.today + timedelta(days=100),
        )

        terms = periods.reviewable_terms(self.school, self.today)

        self.assertNotIn('Term 3', [t.name for t in terms])

    def test_a_running_term_stops_at_today_not_at_its_end_date(self):
        """A window running into the future would report every child as behind."""
        start, end, partial = periods.term_window(self.running, self.today)

        self.assertEqual(start, self.running.start_date)
        self.assertEqual(end, self.today)
        self.assertTrue(partial)

    def test_a_finished_term_reports_its_own_dates(self):
        start, end, partial = periods.term_window(self.finished, self.today)

        self.assertEqual((start, end), (self.finished.start_date,
                                        self.finished.end_date))
        self.assertFalse(partial)

    def test_the_default_is_the_term_that_just_finished(self):
        terms = periods.reviewable_terms(self.school, self.today)

        self.assertEqual(periods.default_term(terms, self.today), self.finished)

    def test_with_no_finished_term_the_default_is_the_running_one(self):
        """A school in its first term used to get a dead end."""
        self.finished.delete()
        terms = periods.reviewable_terms(self.school, self.today)

        self.assertEqual(periods.default_term(terms, self.today), self.running)

    def test_the_label_says_a_partial_term_is_partial(self):
        label = periods.label_for(
            periods.TERM, self.running.start_date, self.today,
            term=self.running, partial=True,
        )

        self.assertIn('Term 2', label)
        self.assertIn('(to date)', label)

    def test_a_finished_term_label_is_unchanged(self):
        self.assertEqual(
            periods.label_for(
                periods.TERM, self.finished.start_date, self.finished.end_date,
                term=self.finished,
            ),
            f'Term 1 {self.year.year}',
        )


class GeneratorRefusalTests(CurrentTermBase):
    """The line that makes "review only" structural rather than a habit."""

    def test_storing_a_running_term_is_refused(self):
        with self.assertRaises(PartialWindowError):
            generate_report(
                self.student, periods.TERM, self.running.start_date,
                self.today, term=self.running,
            )

        self.assertEqual(PeriodReport.objects.count(), 0)

    def test_the_refusal_names_both_dates(self):
        with self.assertRaises(PartialWindowError) as caught:
            generate_report(
                self.student, periods.TERM, self.running.start_date,
                self.today, term=self.running,
            )

        message = str(caught.exception)
        self.assertIn(f'{self.running.end_date:%d %b %Y}', message)
        self.assertIn(f'{self.today:%d %b %Y}', message)

    def test_the_full_term_window_is_still_generated(self):
        """The guard is about the window, not about the clock.

        The command can legitimately be asked to regenerate a term that closed
        months ago; only a window stopping short of the term's end is refused.
        """
        report, created = generate_report(
            self.student, periods.TERM, self.finished.start_date,
            self.finished.end_date, term=self.finished,
        )

        self.assertTrue(created)
        self.assertEqual(report.period_end, self.finished.end_date)

    def test_a_run_over_the_finished_term_is_unaffected(self):
        counts = run_period(
            periods.TERM, self.finished.start_date, self.finished.end_date,
            term=self.finished, school=self.school,
        )

        self.assertEqual(counts['generated'], 1)


class PreviewTests(CurrentTermBase):
    def query(self, **extra):
        params = {'school': self.school.id, 'period': periods.TERM}
        params.update(extra)
        return URL + '?' + '&'.join(f'{k}={v}' for k, v in params.items())

    def test_the_page_opens_on_the_finished_term_as_before(self):
        response = self.client.get(self.query())

        self.assertEqual(response.context['term'], self.finished)
        self.assertFalse(response.context['term_partial'])

    def test_the_running_term_can_be_chosen(self):
        response = self.client.get(self.query(term=self.running.id))

        self.assertEqual(response.context['term'], self.running)
        self.assertTrue(response.context['term_partial'])
        self.assertEqual(response.context['end'], self.today)
        self.assertIn('(to date)', response.context['period_label'])

    def test_it_shows_the_work_done_so_far(self):
        response = self.client.get(self.query(term=self.running.id))

        row = next(
            r for r in response.context['rows'] if r['student'] == self.student
        )
        self.assertTrue(row['has_activity'])
        self.assertEqual(row['totals']['avg_best_pct'], 70)

    def test_a_running_term_offers_no_send_button(self):
        response = self.client.get(self.query(term=self.running.id))

        self.assertContains(response, 'Review only')
        self.assertNotContains(response, 'data-testid="preview-send"')

    def test_a_finished_term_still_offers_one(self):
        response = self.client.get(self.query())

        self.assertContains(response, 'data-testid="preview-send"')
        self.assertNotContains(response, 'Review only')

    def test_the_page_says_why_it_cannot_be_sent(self):
        response = self.client.get(self.query(term=self.running.id))

        self.assertContains(response, 'progress check, not a result')
        self.assertContains(response, 'would take its place')

    def test_previewing_a_running_term_stores_nothing(self):
        self.client.get(self.query(term=self.running.id))

        self.assertEqual(PeriodReport.objects.count(), 0)

    def test_a_term_from_another_school_falls_back_to_the_default(self):
        other = make_school(slug='other-term-school', name='Other')
        foreign = Term.objects.create(
            school=other, name='Term 9', order=9,
            start_date=self.today - timedelta(days=10),
            end_date=self.today + timedelta(days=10),
        )

        response = self.client.get(self.query(term=foreign.id))

        self.assertEqual(response.context['term'], self.finished)

    def test_a_nonsense_term_id_falls_back_rather_than_500ing(self):
        response = self.client.get(self.query(term='abc'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['term'], self.finished)


class SendRefusalTests(CurrentTermBase):
    """The button is not offered; a hand-made POST is still refused."""

    def test_posting_a_running_term_sends_nothing(self):
        response = self.client.post(URL, {
            'school_id': self.school.id, 'period': periods.TERM,
            'term_id': self.running.id,
        }, follow=True)

        self.assertEqual(PeriodReport.objects.count(), 0)
        self.assertContains(response, 'has not ended yet')

    def test_the_refusal_explains_the_cost(self):
        response = self.client.post(URL, {
            'school_id': self.school.id, 'period': periods.TERM,
            'term_id': self.running.id,
        }, follow=True)

        self.assertContains(response, 'take the place of')
        self.assertContains(response, 'it sends once the term closes')

    def test_posting_the_finished_term_still_works(self):
        self.client.post(URL, {
            'school_id': self.school.id, 'period': periods.TERM,
            'term_id': self.finished.id,
        })

        self.assertEqual(
            PeriodReport.objects.filter(term=self.finished).count(), 1,
        )

    def test_the_send_covers_the_term_that_was_reviewed(self):
        """Not merely "the most recent one", which is what it used to assume."""
        older = Term.objects.create(
            school=self.school, academic_year=self.year, name='Term 0', order=0,
            start_date=self.today - timedelta(days=260),
            end_date=self.today - timedelta(days=200),
        )

        self.client.post(URL, {
            'school_id': self.school.id, 'period': periods.TERM,
            'term_id': older.id,
        })

        self.assertTrue(PeriodReport.objects.filter(term=older).exists())
        self.assertFalse(PeriodReport.objects.filter(term=self.finished).exists())


class DetailTests(CurrentTermBase):
    def test_one_student_can_be_opened_for_the_running_term(self):
        response = self.client.get(DETAIL_URL, {
            'school': self.school.id, 'period': periods.TERM,
            'term': self.running.id, 'student': self.student.id,
        })

        self.assertEqual(response.status_code, 200)
        report = response.context['report']
        self.assertTrue(report.is_partial)
        self.assertIn('(to date)', report.label)

    def test_the_detail_page_says_the_term_is_not_over(self):
        response = self.client.get(DETAIL_URL, {
            'school': self.school.id, 'period': periods.TERM,
            'term': self.running.id, 'student': self.student.id,
        })

        self.assertContains(response, 'not the end of the term')

    def test_the_links_back_keep_the_term(self):
        """Opening a chosen term and coming back must not switch terms."""
        response = self.client.get(DETAIL_URL, {
            'school': self.school.id, 'period': periods.TERM,
            'term': self.running.id, 'student': self.student.id,
        })

        self.assertContains(response, f'term={self.running.id}')

    def test_a_finished_term_report_is_not_marked_partial(self):
        response = self.client.get(DETAIL_URL, {
            'school': self.school.id, 'period': periods.TERM,
            'term': self.finished.id, 'student': self.student.id,
        })

        self.assertFalse(response.context['report'].is_partial)

    def test_the_pdf_renders_for_a_running_term(self):
        response = self.client.get(
            '/progress/reports/preview/report/pdf/', {
                'school': self.school.id, 'period': periods.TERM,
                'term': self.running.id, 'student': self.student.id,
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')


class LegacyReportTests(CurrentTermBase):
    def test_a_report_written_before_the_key_existed_is_not_partial(self):
        report = PeriodReport.objects.create(
            student=self.student, school=self.school, term=self.finished,
            period_type=periods.TERM, period_start=self.finished.start_date,
            period_end=self.finished.end_date,
            data={'period': {'label': 'Term 1', 'type': 'term'}},
        )

        self.assertFalse(report.is_partial)

    def test_a_report_with_no_data_at_all_is_not_partial(self):
        report = PeriodReport(
            student=self.student, period_type=periods.TERM,
            period_start=date(2026, 1, 1), period_end=date(2026, 3, 1),
        )

        self.assertFalse(report.is_partial)
