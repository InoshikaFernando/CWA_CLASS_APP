"""The report settings page — access and the tri-state form (CPP-388 follow-up)."""

from django.test import TestCase
from django.urls import reverse

from classroom.models import SchoolTeacher
from progress import report_settings
from progress.models import ProgressReportSetting
from progress.tests.factories import (
    add_teacher, enable_reports, enrol, make_classroom, make_department,
    make_school, make_user,
)

URL = '/progress/reports/settings/'


class SettingsAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.hoi = make_user('cfg_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )
        cls.teacher = make_user('cfg_teacher', 'teacher')
        add_teacher(cls.classroom, cls.teacher)
        cls.student = make_user('cfg_student')
        enrol(cls.classroom, cls.student)

    def test_the_head_of_institute_can_open_it(self):
        self.client.force_login(self.hoi)
        response = self.client.get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['school'], self.school)

    def test_a_class_teacher_cannot(self):
        # Switching this on starts notifying families — not a per-teacher call.
        self.client.force_login(self.teacher)
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_a_student_cannot(self):
        self.client.force_login(self.student)
        self.assertEqual(self.client.get(URL).status_code, 302)

    def test_anonymous_users_are_sent_to_log_in(self):
        response = self.client.get(URL)
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.url)


class SettingsFormTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.dept = make_department(cls.school)
        cls.classroom = make_classroom(cls.school)
        cls.classroom.department = cls.dept
        cls.classroom.save(update_fields=['department'])
        cls.hoi = make_user('form_hoi', 'head_of_institute')
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.hoi, role='head_of_institute',
        )

    def setUp(self):
        self.client.force_login(self.hoi)

    def post(self, **fields):
        payload = {field: 'inherit' for field in (
            'weekly', 'monthly', 'term',
            'notify_student', 'notify_parents', 'email_parents_at_term',
        )}
        payload.update(fields)
        return self.client.post(URL, payload, follow=True)

    def test_switching_the_school_on_enables_its_classes(self):
        self.post(scope='school', school_id=self.school.id, weekly='on')

        self.assertTrue(report_settings.effective(self.classroom)['weekly'])

    def test_a_department_row_overrides_the_school_row(self):
        self.post(scope='school', school_id=self.school.id, weekly='on')
        self.post(
            scope='department', school_id=self.school.id,
            department_id=self.dept.id, weekly='off',
        )

        resolved = report_settings.resolve(self.classroom)['weekly']
        self.assertEqual(resolved, (False, 'department'))

    def test_a_class_row_overrides_the_department_row(self):
        self.post(
            scope='department', school_id=self.school.id,
            department_id=self.dept.id, weekly='off',
        )
        self.post(
            scope='class', school_id=self.school.id,
            classroom_id=self.classroom.id, weekly='on',
        )

        resolved = report_settings.resolve(self.classroom)['weekly']
        self.assertEqual(resolved, (True, 'class'))

    def test_setting_everything_back_to_inherit_removes_the_row(self):
        self.post(scope='school', school_id=self.school.id, weekly='on')
        self.assertEqual(ProgressReportSetting.objects.count(), 1)

        self.post(scope='school', school_id=self.school.id)
        self.assertEqual(ProgressReportSetting.objects.count(), 0)

    def test_a_missing_field_is_treated_as_inherit_not_as_off(self):
        """A half-posted form must not silently disable a school's reports."""
        enable_reports(self.school, kind='school', weekly=True, term=True)

        # Post only the weekly radio; everything else is absent from the body.
        self.client.post(URL, {
            'scope': 'school', 'school_id': self.school.id, 'weekly': 'on',
        }, follow=True)

        self.assertTrue(report_settings.effective(self.classroom)['weekly'])
        # `term` was absent, so it went back to inherit → off, not to a stored
        # False. The row records None, which is what "inherit" means.
        row = ProgressReportSetting.objects.get(school=self.school)
        self.assertIsNone(row.term)

    def test_another_schools_scope_is_rejected(self):
        other = make_school(slug='other-cfg', name='Other')
        other_class = make_classroom(other, name='Theirs', code='CFG00099')

        response = self.client.post(URL, {
            'scope': 'class', 'school_id': other.id,
            'classroom_id': other_class.id, 'weekly': 'on',
        })

        self.assertEqual(response.status_code, 404)
        self.assertFalse(report_settings.effective(other_class)['weekly'])

    def test_the_page_shows_which_level_decided_each_value(self):
        enable_reports(self.school, kind='school', weekly=True)

        response = self.client.get(URL)
        classroom = response.context['classrooms'][0]
        weekly = next(r for r in classroom.resolved if r['field'] == 'weekly')

        self.assertTrue(weekly['value'])
        self.assertEqual(weekly['source'], 'school')
        self.assertEqual(response.context['enabled_count'], 1)

    def test_no_template_syntax_leaks_into_the_page(self):
        response = self.client.get(URL)
        content = response.content.decode()
        for token in ('{#', '{%', '{{'):
            self.assertNotIn(token, content, f'unrendered {token} in the page')


class SidebarVisibilityTests(TestCase):
    """The "My Reports" link only appears once there is something behind it.

    A permanent link to an empty page in every unconfigured school reads as a
    broken feature rather than an unconfigured one.
    """

    @classmethod
    def setUpTestData(cls):
        from progress.tests.factories import link_parent

        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)
        cls.student = make_user('vis_student')
        cls.parent = make_user('vis_parent', 'parent')
        enrol(cls.classroom, cls.student)
        link_parent(cls.parent, cls.student, cls.school)

    def flag_for(self, user):
        self.client.force_login(user)
        response = self.client.get('/student-dashboard/', follow=True)
        return response.context.get('show_period_reports')

    def test_hidden_for_an_unconfigured_school(self):
        self.assertFalse(self.flag_for(self.student))

    def test_shown_once_the_school_switches_reports_on(self):
        enable_reports(self.school, kind='school', weekly=True)
        self.assertTrue(self.flag_for(self.student))

    def test_shown_to_a_parent_of_a_configured_child(self):
        enable_reports(self.school, kind='school', weekly=True)
        self.assertTrue(self.flag_for(self.parent))

    def test_shown_when_a_report_already_exists_even_if_since_disabled(self):
        from datetime import date

        from progress.models import PeriodReport

        PeriodReport.objects.create(
            student=self.student, school=self.school, period_type='weekly',
            period_start=date(2026, 8, 17), period_end=date(2026, 8, 23),
            data={'totals': {'submissions': 1}},
        )
        # Nothing is enabled now, but the student still has a report to read.
        self.assertTrue(self.flag_for(self.student))
