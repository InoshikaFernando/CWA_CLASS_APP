"""Tests for the 0118 / 0119 subject-repair data migrations.

The migration functions are imported and called directly against the real
models. That keeps the tests readable and — more importantly — lets them assert
the *rules*, which is what makes this repair safe to run on production: it must
never guess an ambiguous class, and every change it does make must be
recoverable from the audit trail.
"""

from decimal import Decimal
from importlib import import_module

from django.apps import apps as django_apps
from django.test import TestCase

from audit.models import AuditLog
from classroom.models import (
    ClassRoom, Department, DepartmentLevel, DepartmentSubject, Level, School,
    Subject,
)

_backfill = import_module('classroom.migrations.0118_backfill_level_subject')
_repair = import_module('classroom.migrations.0119_repair_classroom_subject')


class BackfillLevelSubjectTests(TestCase):
    def setUp(self):
        self.maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        self.school = School.objects.create(name='S', slug='s')

    def _run(self):
        _backfill.set_maths_subject(django_apps, None)

    def test_year_levels_get_mathematics(self):
        y5 = Level.objects.create(level_number=5, display_name='Year 5')
        self._run()
        y5.refresh_from_db()
        self.assertEqual(y5.subject, self.maths)

    def test_basic_facts_levels_get_mathematics(self):
        bf = Level.objects.create(level_number=150, display_name='BF Addition')
        self._run()
        bf.refresh_from_db()
        self.assertEqual(bf.subject, self.maths)

    def test_school_custom_levels_are_left_alone(self):
        """200+ carries no promise about its subject — guessing would be worse."""
        custom = Level.objects.create(
            level_number=250, display_name='Scholarship', school=self.school)
        self._run()
        custom.refresh_from_db()
        self.assertIsNone(custom.subject)

    def test_a_level_that_already_names_a_subject_is_untouched(self):
        coding = Subject.objects.create(
            name='Coding', slug='coding', is_active=True)
        lv = Level.objects.create(
            level_number=300, display_name='Beginner', subject=coding)
        self._run()
        lv.refresh_from_db()
        self.assertEqual(lv.subject, coding)

    def test_no_department_level_mapping_is_disturbed(self):
        dept = Department.objects.create(school=self.school, name='D', slug='d')
        y5 = Level.objects.create(level_number=5, display_name='Year 5')
        DepartmentLevel.objects.create(department=dept, level=y5, order=5)
        before = set(DepartmentLevel.objects.values_list('id', flat=True))

        self._run()

        self.assertEqual(
            set(DepartmentLevel.objects.values_list('id', flat=True)), before)

    def test_no_maths_subject_is_a_no_op(self):
        Subject.objects.filter(slug='mathematics').delete()
        y5 = Level.objects.create(level_number=5, display_name='Year 5')
        self._run()
        y5.refresh_from_db()
        self.assertIsNone(y5.subject)

    def test_reverse_leaves_year_10_to_its_own_migration(self):
        y5 = Level.objects.create(level_number=5, display_name='Year 5')
        y10 = Level.objects.create(
            level_number=10, display_name='Year 10', subject=self.maths)
        self._run()

        _backfill.clear_maths_subject(django_apps, None)

        y5.refresh_from_db()
        y10.refresh_from_db()
        self.assertIsNone(y5.subject)
        self.assertEqual(y10.subject, self.maths, '0101 owns Year 10')


class RepairClassroomSubjectTests(TestCase):
    def setUp(self):
        self.school = School.objects.create(name='S2', slug='s2')
        self.dept = Department.objects.create(
            school=self.school, name='STEM', slug='stem')
        self.maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        self.coding, _ = Subject.objects.get_or_create(
            slug='coding', school=None,
            defaults={'name': 'Coding', 'is_active': True})
        DepartmentSubject.objects.create(
            department=self.dept, subject=self.maths, order=0)
        DepartmentSubject.objects.create(
            department=self.dept, subject=self.coding, order=1)

        self.maths_lv = Level.objects.create(
            level_number=5, display_name='Year 5', subject=self.maths)
        self.coding_lv = Level.objects.create(
            level_number=300, display_name='Beginner', subject=self.coding)

    def _class(self, name, subject, levels=()):
        classroom = ClassRoom.objects.create(
            name=name, school=self.school, department=self.dept, subject=subject)
        for level in levels:
            classroom.levels.add(level)
        return classroom

    def _run(self):
        _repair.repair(django_apps, None)

    def test_mislabelled_class_is_corrected(self):
        classroom = self._class('Coding 101', self.maths, [self.coding_lv])
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

    def test_ambiguous_class_is_never_guessed(self):
        classroom = self._class(
            'Mixed', self.maths, [self.maths_lv, self.coding_lv])
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(
            classroom.subject, self.maths, 'left exactly as found')
        self.assertFalse(
            AuditLog.objects.filter(action='class_subject_repaired').exists())

    def test_unresolvable_level_is_never_guessed(self):
        orphan_level = Level.objects.create(
            level_number=260, display_name='Custom', school=self.school)
        classroom = self._class('Custom Class', self.maths, [orphan_level])
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.maths)

    def test_correct_class_is_not_rewritten(self):
        self._class('Already Right', self.coding, [self.coding_lv])
        self._run()
        self.assertFalse(
            AuditLog.objects.filter(action='class_subject_repaired').exists())

    def test_class_with_no_levels_and_no_subject_takes_department_first(self):
        classroom = self._class('Unlabelled', None)
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.maths)

    def test_class_with_no_levels_but_a_subject_is_left_alone(self):
        classroom = self._class('No Levels', self.coding)
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

    def test_change_is_recorded_with_the_previous_subject(self):
        classroom = self._class('Coding 101', self.maths, [self.coding_lv])
        self._run()

        entry = AuditLog.objects.get(action='class_subject_repaired')
        self.assertEqual(entry.detail['classroom_id'], classroom.id)
        self.assertEqual(entry.detail['previous_subject_id'], self.maths.id)
        self.assertEqual(entry.detail['new_subject_id'], self.coding.id)

    def test_reverse_restores_every_repaired_class(self):
        classroom = self._class('Coding 101', self.maths, [self.coding_lv])
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.coding)

        _repair.unrepair(django_apps, None)

        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.maths)
        self.assertFalse(
            AuditLog.objects.filter(action='class_subject_repaired').exists())

    def test_levels_are_never_touched(self):
        classroom = self._class('Coding 101', self.maths, [self.coding_lv])
        before = set(classroom.levels.values_list('id', flat=True))
        self._run()
        self.assertEqual(
            set(classroom.levels.values_list('id', flat=True)), before)

    def test_inactive_classes_are_skipped(self):
        classroom = self._class('Archived', self.maths, [self.coding_lv])
        ClassRoom.objects.filter(pk=classroom.pk).update(is_active=False)
        self._run()
        classroom.refresh_from_db()
        self.assertEqual(classroom.subject, self.maths)
