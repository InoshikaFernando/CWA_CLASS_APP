"""Opening one student's report from the preview list (CPP-388 follow-up).

The preview table answers "how did they do"; it could not answer "what will
they actually receive". These pages render the real report and the real PDF
from a report that is never saved, so a school can read exactly what a family
would get before deciding to send it.

Two properties carry the weight here:

* **Nothing is written.** Same reason the list writes nothing — a preview that
  created rows would stamp delivery state and leave the real send with nothing
  to do.
* **Access is the list's access.** The student must be in the same plan that
  builds the table, so the link can never open a report the table would not
  have shown this user.
"""

from datetime import datetime, time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.tests.factories import (
    enable_reports, enrol, make_classroom, make_homework, make_school,
    make_user, submit,
)

DETAIL_URL = '/progress/reports/preview/report/'
PDF_URL = '/progress/reports/preview/report/pdf/'


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class PreviewDetailBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.hoi = make_user('pd_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.student = make_user('pd_student', first_name='Ada', last_name='B')
        enrol(cls.classroom, cls.student)

        last_monday = periods.previous_week(periods.today())[0]
        cls.window_start = last_monday
        homework = make_homework(
            cls.classroom, due=at(last_monday), title='Practice',
        )
        submit(homework, cls.student, 1, 4, when=at(last_monday))
        submit(homework, cls.student, 2, 9, when=at(last_monday))

    def setUp(self):
        self.client.force_login(self.hoi)
        enable_reports(self.school, kind='school', weekly=True)

    def scope(self, student=None, **overrides):
        params = {
            'school': self.school.id,
            'period': periods.WEEKLY,
            'student': (student or self.student).id,
        }
        params.update(overrides)
        return '&'.join(f'{k}={v}' for k, v in params.items())


class PreviewDetailTests(PreviewDetailBase):
    def test_it_renders_the_report_the_family_would_receive(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['preview'])
        self.assertEqual(response.context['student'], self.student)
        # The real figures, not a placeholder: best of 4/10 and 9/10.
        self.assertEqual(response.context['totals']['avg_best_pct'], 90)

    def test_it_says_the_report_has_not_been_sent(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertContains(response, 'has not been generated or sent')

    def test_opening_the_preview_saves_nothing(self):
        self.client.get(f'{DETAIL_URL}?{self.scope()}')
        self.client.get(f'{PDF_URL}?{self.scope()}')

        self.assertFalse(PeriodReport.objects.exists())

    def test_the_pdf_is_the_same_report_as_a_download(self):
        response = self.client.get(f'{PDF_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_list_links_to_it_for_a_student_with_activity(self):
        response = self.client.get(
            f'/progress/reports/preview/?school={self.school.id}'
            f'&period={periods.WEEKLY}'
        )

        self.assertContains(response, 'preview-view-report')
        self.assertContains(response, f'student={self.student.id}')

    def test_a_student_with_nothing_to_show_gets_no_link(self):
        quiet = make_user('pd_quiet', first_name='Quiet', last_name='One')
        enrol(self.classroom, quiet)

        response = self.client.get(
            f'/progress/reports/preview/?school={self.school.id}'
            f'&period={periods.WEEKLY}'
        )

        self.assertNotContains(response, f'student={quiet.id}')

    def test_no_template_syntax_leaks_into_the_page(self):
        # A multi-line {# … #} ends at the first line break and renders the
        # rest as body text. This has now happened twice.
        body = self.client.get(
            f'{DETAIL_URL}?{self.scope()}'
        ).content.decode()
        # Opening tokens only, matching the sibling test: a closing brace is
        # ordinary CSS, and base.html is full of it.
        for token in ('{#', '{%', '{{'):
            self.assertNotIn(token, body, f'unrendered {token} in the page')


class PreviewDetailAccessTests(PreviewDetailBase):
    def test_a_student_outside_the_scope_is_not_found(self):
        outsider = make_user('pd_outsider', first_name='Else', last_name='Where')
        other_school = make_school(name='Other Institute', slug='other-institute')
        enrol(make_classroom(other_school, code='RPT00002'), outsider)

        response = self.client.get(f'{DETAIL_URL}?{self.scope(student=outsider)}')

        self.assertEqual(response.status_code, 404)

    def test_a_head_of_another_institute_is_not_found(self):
        other_school = make_school(name='Rival Institute', slug='rival-institute')
        rival = make_user('pd_rival', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=other_school, teacher=rival, role='head_of_institute',
        )
        self.client.force_login(rival)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 404)

    def test_a_student_cannot_open_the_staff_preview(self):
        self.client.force_login(self.student)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertNotEqual(response.status_code, 200)

    def test_a_class_with_reports_switched_off_has_nothing_to_preview(self):
        # Access follows the plan that builds the table: switch reporting off
        # and the row disappears, so the link must stop working too.
        enable_reports(self.school, kind='school', weekly=False)

        response = self.client.get(f'{DETAIL_URL}?{self.scope()}')

        self.assertEqual(response.status_code, 404)

    def test_the_bare_url_goes_back_to_the_list_rather_than_dead_ending(self):
        # Naming no student is not the same as naming one you may not see.
        # A truncated link or a bookmark should land on the page with the
        # links on it; test_url_sitemap walks every route with no arguments
        # and treats a 404 there as a missing route, which it would be.
        for url in (DETAIL_URL, PDF_URL):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertEqual(response.status_code, 302)
                self.assertEqual(response['Location'], '/progress/reports/preview/')

    def test_a_hand_edited_student_id_is_not_found_rather_than_a_500(self):
        response = self.client.get(
            f'{DETAIL_URL}?school={self.school.id}'
            f'&period={periods.WEEKLY}&student=abc'
        )

        self.assertEqual(response.status_code, 404)

    def test_an_unknown_period_is_not_found(self):
        response = self.client.get(f'{DETAIL_URL}?{self.scope(period="decade")}')

        self.assertEqual(response.status_code, 404)
