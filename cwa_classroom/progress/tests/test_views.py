"""Access control and rendering for the report pages (CPP-388)."""

from datetime import date, datetime, time

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from classroom.models import ClassStudent, ParentStudent, SchoolTeacher
from progress import periods
from progress.models import PeriodReport
from progress.reports import build_report_data
from progress.tests.factories import (
    add_teacher, enrol, link_parent, make_classroom, make_homework, make_school,
    make_user, submit,
)

START = date(2026, 8, 17)
END = date(2026, 8, 23)


def at(day, hour=10):
    return timezone.make_aware(
        datetime.combine(day, time(hour, 0)), timezone.get_current_timezone(),
    )


class ReportViewBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)

        cls.student = make_user('v_student')
        cls.other_student = make_user('v_other')
        cls.parent = make_user('v_parent', 'parent')
        cls.other_parent = make_user('v_other_parent', 'parent')
        cls.teacher = make_user('v_teacher', 'teacher')
        cls.stranger_teacher = make_user('v_stranger_teacher', 'teacher')

        enrol(cls.classroom, cls.student)
        enrol(cls.classroom, cls.other_student)
        add_teacher(cls.classroom, cls.teacher)
        link_parent(cls.parent, cls.student, cls.school)
        link_parent(cls.other_parent, cls.other_student, cls.school)

        homework = make_homework(cls.classroom, due=at(date(2026, 8, 21)))
        submit(homework, cls.student, 1, 4, when=at(date(2026, 8, 18)))
        submit(homework, cls.student, 2, 9, when=at(date(2026, 8, 19)))

        cls.report = PeriodReport.objects.create(
            student=cls.student, school=cls.school,
            period_type=periods.WEEKLY, period_start=START, period_end=END,
            data=build_report_data(cls.student, periods.WEEKLY, START, END),
        )

    def login(self, user):
        self.client.force_login(user)

    def detail_url(self):
        return reverse('progress:period_report_detail',
                       kwargs={'report_id': self.report.id})

    def pdf_url(self):
        return reverse('progress:period_report_pdf',
                       kwargs={'report_id': self.report.id})


class DetailAccessTests(ReportViewBase):
    def test_the_student_can_read_their_own_report(self):
        self.login(self.student)
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Progress Report')

    def test_a_linked_parent_can_read_it(self):
        self.login(self.parent)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)

    def test_another_familys_parent_gets_a_404_not_a_403(self):
        # A 403 would confirm that this child's report exists.
        self.login(self.other_parent)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_a_teacher_of_the_class_can_read_it(self):
        self.login(self.teacher)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)

    def test_a_teacher_from_another_class_cannot(self):
        self.login(self.stranger_teacher)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_another_student_cannot(self):
        self.login(self.other_student)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_a_parent_link_that_was_deactivated_loses_access(self):
        ParentStudent.objects.filter(
            parent=self.parent, student=self.student).update(is_active=False)
        self.login(self.parent)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_a_teacher_who_left_the_class_loses_access(self):
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student).update(is_active=False)
        self.login(self.teacher)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_the_head_of_institute_can_read_their_own_schools_reports(self):
        hoi = make_user('v_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=self.school, teacher=hoi, role='head_of_institute',
        )
        self.login(hoi)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 200)

    def test_a_head_of_another_institute_cannot(self):
        other_school = make_school(slug='other-school', name='Other School')
        hoi = make_user('v_other_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=other_school, teacher=hoi, role='head_of_institute',
        )
        self.login(hoi)
        self.assertEqual(self.client.get(self.detail_url()).status_code, 404)

    def test_anonymous_users_are_sent_to_log_in(self):
        response = self.client.get(self.detail_url())
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)


class DetailRenderTests(ReportViewBase):
    def test_the_page_carries_the_chart_data_and_the_pdf_link(self):
        self.login(self.student)
        response = self.client.get(self.detail_url())

        self.assertContains(response, 'report-charts-data')
        self.assertContains(response, self.pdf_url())
        self.assertEqual(response.context['totals']['avg_best_pct'], 90)

    def test_the_chart_payload_mirrors_the_stored_snapshot(self):
        import json

        self.login(self.student)
        response = self.client.get(self.detail_url())
        charts = json.loads(response.context['charts_json'])

        self.assertEqual(
            charts['firstVsBest']['first'],
            [row['first_pct'] for row in self.report.attempts['items']],
        )

    def test_an_empty_report_says_so_rather_than_showing_zeros(self):
        empty = PeriodReport.objects.create(
            student=self.student, school=self.school,
            period_type=periods.MONTHLY,
            period_start=date(2026, 7, 1), period_end=date(2026, 7, 31),
            data=build_report_data(
                self.student, periods.MONTHLY, date(2026, 7, 1), date(2026, 7, 31),
            ),
        )
        self.login(self.student)
        response = self.client.get(reverse(
            'progress:period_report_detail', kwargs={'report_id': empty.id}))

        self.assertContains(response, 'No homework was submitted in this period')


class ListViewTests(ReportViewBase):
    def test_a_student_sees_their_own_reports(self):
        self.login(self.student)
        response = self.client.get(reverse('progress:period_report_list'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(response.context['reports']), [self.report])
        self.assertTrue(response.context['is_self'])

    def test_a_parent_sees_the_child_they_have_selected(self):
        self.login(self.parent)
        response = self.client.get(reverse('progress:period_report_list'))

        self.assertEqual(response.context['student'], self.student)
        self.assertEqual(list(response.context['reports']), [self.report])

    def test_a_parent_with_no_children_gets_an_empty_page_not_an_error(self):
        childless = make_user('v_childless', 'parent')
        self.login(childless)
        response = self.client.get(reverse('progress:period_report_list'))

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context['student'])

    def test_a_teacher_can_request_a_specific_student(self):
        self.login(self.teacher)
        response = self.client.get(
            reverse('progress:period_report_list'),
            {'student': self.student.id},
        )
        self.assertEqual(response.context['student'], self.student)
        self.assertFalse(response.context['is_self'])

    def test_requesting_a_student_you_cannot_see_is_a_404(self):
        self.login(self.stranger_teacher)
        response = self.client.get(
            reverse('progress:period_report_list'),
            {'student': self.student.id},
        )
        self.assertEqual(response.status_code, 404)


class PdfViewTests(ReportViewBase):
    def test_the_pdf_downloads_as_a_pdf(self):
        self.login(self.student)
        response = self.client.get(self.pdf_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_the_filename_identifies_the_student_and_period(self):
        self.login(self.student)
        response = self.client.get(self.pdf_url())

        self.assertIn('v_student-weekly-2026-08-17.pdf',
                      response['Content-Disposition'])

    def test_the_pdf_is_behind_the_same_access_rule_as_the_page(self):
        self.login(self.other_parent)
        self.assertEqual(self.client.get(self.pdf_url()).status_code, 404)
