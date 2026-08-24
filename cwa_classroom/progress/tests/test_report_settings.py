"""The opt-in cascade: school → department → class (CPP-388 follow-up).

Reports notify families, so the thing worth testing hardest is that nothing
happens until somebody says it should — and that turning one level on does not
quietly turn a neighbouring flag on with it.
"""

from django.test import TestCase

from progress import report_settings
from progress.models import ProgressReportSetting
from progress.tests.factories import (
    enable_reports, make_classroom, make_department, make_school,
)


class CascadeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.dept = make_department(cls.school)
        cls.classroom = make_classroom(cls.school)
        cls.classroom.department = cls.dept
        cls.classroom.save(update_fields=['department'])

    def effective(self):
        return report_settings.effective(self.classroom)

    def source(self, field):
        return report_settings.resolve(self.classroom)[field][1]

    # -- the default ------------------------------------------------------

    def test_nothing_is_enabled_until_someone_enables_it(self):
        values = self.effective()
        self.assertEqual(
            {field: values[field] for field in (
                'weekly', 'monthly', 'term',
                'notify_student', 'notify_parents', 'email_parents_at_term',
            )},
            {
                'weekly': False, 'monthly': False, 'term': False,
                'notify_student': False, 'notify_parents': False,
                'email_parents_at_term': False,
            },
        )
        self.assertEqual(self.source('weekly'), 'default')

    def test_the_default_mode_is_manual(self):
        """Nothing sends on a schedule a school did not ask for."""
        self.assertEqual(self.effective()['mode'], 'manual')
        self.assertEqual(self.source('mode'), 'default')

    def test_the_schedule_defaults_match_the_close_of_each_window(self):
        values = self.effective()
        self.assertEqual(values['send_weekly_on'], 0)          # Monday
        self.assertEqual(values['send_monthly_on'], 1)         # the 1st
        self.assertEqual(values['send_term_after_days'], 1)    # day after term end

    def test_mode_and_schedule_cascade_like_everything_else(self):
        enable_reports(self.school, kind='school', weekly=True, mode='auto')
        self.assertEqual(self.effective()['mode'], 'auto')
        self.assertEqual(self.source('mode'), 'school')

        enable_reports(
            self.school, self.classroom, kind='class', mode='manual',
            send_weekly_on=4,
        )
        values = self.effective()
        self.assertEqual(values['mode'], 'manual')
        self.assertEqual(self.source('mode'), 'class')
        self.assertEqual(values['send_weekly_on'], 4)

    # -- school level -----------------------------------------------------

    def test_a_school_setting_applies_to_its_classes(self):
        enable_reports(self.school, kind='school', weekly=True)

        self.assertTrue(self.effective()['weekly'])
        self.assertEqual(self.source('weekly'), 'school')

    def test_enabling_one_period_does_not_enable_the_others(self):
        enable_reports(self.school, kind='school', weekly=True)

        values = self.effective()
        self.assertTrue(values['weekly'])
        self.assertFalse(values['monthly'])
        self.assertFalse(values['term'])

    def test_delivery_defaults_on_only_once_something_generates(self):
        # Nothing enabled → nobody is notified about anything.
        self.assertFalse(self.effective()['notify_parents'])

        enable_reports(self.school, kind='school', weekly=True)
        self.assertTrue(self.effective()['notify_parents'])

    # -- department overrides school --------------------------------------

    def test_a_department_overrides_the_school(self):
        enable_reports(self.school, kind='school', weekly=True)
        enable_reports(self.school, self.dept, kind='department', weekly=False)

        self.assertFalse(self.effective()['weekly'])
        self.assertEqual(self.source('weekly'), 'department')

    def test_a_department_can_enable_what_the_school_left_alone(self):
        enable_reports(self.school, self.dept, kind='department', term=True)

        values = self.effective()
        self.assertTrue(values['term'])
        self.assertFalse(values['weekly'])
        self.assertEqual(self.source('term'), 'department')

    def test_a_department_setting_does_not_touch_other_departments(self):
        other_dept = make_department(self.school, name='Science', slug='science')
        other_class = make_classroom(self.school, name='Sci 1', code='SET00002')
        other_class.department = other_dept
        other_class.save(update_fields=['department'])

        enable_reports(self.school, self.dept, kind='department', weekly=True)

        self.assertTrue(self.effective()['weekly'])
        self.assertFalse(report_settings.effective(other_class)['weekly'])

    # -- class overrides department ---------------------------------------

    def test_a_class_overrides_its_department(self):
        enable_reports(self.school, self.dept, kind='department', weekly=True)
        enable_reports(self.school, self.classroom, kind='class', weekly=False)

        self.assertFalse(self.effective()['weekly'])
        self.assertEqual(self.source('weekly'), 'class')

    def test_a_class_overrides_the_school_when_no_department_says_anything(self):
        enable_reports(self.school, kind='school', weekly=False)
        enable_reports(self.school, self.classroom, kind='class', weekly=True)

        self.assertTrue(self.effective()['weekly'])
        self.assertEqual(self.source('weekly'), 'class')

    def test_each_flag_inherits_independently(self):
        enable_reports(self.school, kind='school', weekly=True, term=True)
        enable_reports(self.school, self.classroom, kind='class', weekly=False)

        values = self.effective()
        self.assertFalse(values['weekly'])           # class said so
        self.assertTrue(values['term'])              # still the school's
        self.assertEqual(self.source('term'), 'school')

    def test_a_class_with_no_department_still_inherits_the_school(self):
        loose = make_classroom(self.school, name='Loose', code='SET00003')
        enable_reports(self.school, kind='school', monthly=True)

        self.assertTrue(report_settings.effective(loose)['monthly'])


class SettingRowTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.classroom = make_classroom(cls.school)

    def test_a_row_that_says_nothing_is_deleted_rather_than_kept(self):
        enable_reports(self.school, kind='school', weekly=True)
        self.assertEqual(ProgressReportSetting.objects.count(), 1)

        enable_reports(self.school, kind='school')  # everything back to inherit
        self.assertEqual(ProgressReportSetting.objects.count(), 0)

    def test_saving_the_same_scope_twice_updates_rather_than_duplicates(self):
        enable_reports(self.school, kind='school', weekly=True)
        enable_reports(self.school, kind='school', weekly=False)

        self.assertEqual(ProgressReportSetting.objects.count(), 1)
        self.assertFalse(report_settings.effective(self.classroom)['weekly'])


class EnabledClassroomTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = make_school()
        cls.other_school = make_school(slug='other', name='Other School')
        cls.classroom = make_classroom(cls.school)
        cls.other_classroom = make_classroom(
            cls.other_school, name='Other Class', code='SET00010',
        )

    def test_an_unconfigured_install_enables_nothing(self):
        self.assertEqual(report_settings.enabled_classrooms('weekly'), [])

    def test_only_the_configured_school_is_returned(self):
        enable_reports(self.school, kind='school', weekly=True)

        enabled = report_settings.enabled_classrooms('weekly')
        self.assertEqual([c.id for c in enabled], [self.classroom.id])

    def test_a_period_nobody_enabled_returns_nothing(self):
        enable_reports(self.school, kind='school', weekly=True)
        self.assertEqual(report_settings.enabled_classrooms('term'), [])
