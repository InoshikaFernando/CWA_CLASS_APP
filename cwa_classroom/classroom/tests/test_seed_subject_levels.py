"""Tests for the seed_subject_levels management command."""

from io import StringIO

from django.core.management import call_command

from classroom.models import Subject, DepartmentSubject, Level, DepartmentLevel

from .test_e2e_attendance_progress import _BaseAttendanceProgressTest


class SeedSubjectLevelsTest(_BaseAttendanceProgressTest):

    def _coding_in_dept(self):
        coding = Subject.objects.create(name='Coding', slug='coding', is_active=True)
        DepartmentSubject.objects.create(department=self.department, subject=coding)
        return coding

    def test_creates_global_levels_and_links_to_department(self):
        coding = self._coding_in_dept()
        call_command('seed_subject_levels', '--subject', str(coding.id), stdout=StringIO())

        levels = list(Level.objects.filter(subject=coding).order_by('level_number'))
        self.assertEqual([lv.display_name for lv in levels],
                         ['Beginner', 'Intermediate', 'Advanced'])
        # Numbered clear of Maths (>=300) and global (school=None).
        self.assertTrue(all(lv.level_number >= 300 for lv in levels))
        self.assertTrue(all(lv.school_id is None for lv in levels))
        # Linked to the department that teaches Coding.
        for lv in levels:
            self.assertTrue(
                DepartmentLevel.objects.filter(department=self.department, level=lv).exists()
            )

    def test_idempotent(self):
        coding = self._coding_in_dept()
        call_command('seed_subject_levels', '--subject', str(coding.id), stdout=StringIO())
        call_command('seed_subject_levels', '--subject', str(coding.id), stdout=StringIO())
        self.assertEqual(Level.objects.filter(subject=coding).count(), 3)
        self.assertEqual(
            DepartmentLevel.objects.filter(level__subject=coding).count(), 3,
        )

    def test_custom_level_names(self):
        coding = self._coding_in_dept()
        call_command('seed_subject_levels', '--subject', str(coding.id),
                     '--levels', 'Novice,Pro', stdout=StringIO())
        self.assertEqual(
            list(Level.objects.filter(subject=coding).order_by('level_number')
                 .values_list('display_name', flat=True)),
            ['Novice', 'Pro'],
        )

    def test_dry_run_writes_nothing(self):
        coding = self._coding_in_dept()
        call_command('seed_subject_levels', '--subject', str(coding.id), '--dry-run',
                     stdout=StringIO())
        self.assertEqual(Level.objects.filter(subject=coding).count(), 0)
