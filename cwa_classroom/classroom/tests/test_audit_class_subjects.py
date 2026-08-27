"""Tests for ``manage.py audit_class_subjects``.

The command exists to be trusted before a repair runs, so these tests pin two
things above all: it reports the right rows, and it changes nothing.
"""

from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from classroom.models import (
    ClassRoom, Department, DepartmentLevel, DepartmentSubject, Level, School,
    Subject,
)


def _run(**kwargs):
    out = StringIO()
    call_command('audit_class_subjects', stdout=out, stderr=out, **kwargs)
    return out.getvalue()


class AuditClassSubjectsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.school = School.objects.create(name='Test School', slug='test-school')
        cls.dept = Department.objects.create(
            school=cls.school, name='STEM', slug='stem')

        cls.maths, _ = Subject.objects.get_or_create(
            slug='mathematics', school=None,
            defaults={'name': 'Mathematics', 'is_active': True})
        cls.coding, _ = Subject.objects.get_or_create(
            slug='coding', school=None,
            defaults={'name': 'Coding', 'is_active': True})
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.maths, order=0)
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.coding, order=1)

        # A Year level exactly as setup_dev creates it: no subject.
        cls.year5 = Level.objects.create(level_number=5, display_name='Year 5')
        # A coding level as seed_subject_levels creates it: numbered 300+.
        cls.coding_lv = Level.objects.create(
            level_number=300, display_name='Beginner', subject=cls.coding)
        # A school custom level with no subject — not inferable.
        cls.custom_lv = Level.objects.create(
            level_number=250, display_name='Custom Tier', school=cls.school)
        for level in (cls.year5, cls.coding_lv, cls.custom_lv):
            DepartmentLevel.objects.create(
                department=cls.dept, level=level, order=level.level_number)

    # -- the headline guarantee ----------------------------------------

    def test_command_writes_nothing(self):
        """The whole point: an audit that mutates is not an audit."""
        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        before = {
            'class_subject': wrong.subject_id,
            'level_subjects': dict(Level.objects.values_list('id', 'subject_id')),
            'class_count': ClassRoom.objects.count(),
            'level_count': Level.objects.count(),
            'subject_count': Subject.objects.count(),
        }

        _run()

        wrong.refresh_from_db()
        self.assertEqual(wrong.subject_id, before['class_subject'])
        self.assertEqual(
            dict(Level.objects.values_list('id', 'subject_id')), before['level_subjects'])
        self.assertEqual(ClassRoom.objects.count(), before['class_count'])
        self.assertEqual(Level.objects.count(), before['level_count'])
        self.assertEqual(Subject.objects.count(), before['subject_count'])

    # -- levels ---------------------------------------------------------

    def test_reports_year_level_missing_subject(self):
        out = _run()
        self.assertIn('Year 5', out)
        self.assertIn('would be set to Mathematics', out)

    def test_custom_level_is_not_assumed_to_be_maths(self):
        """A 200+ level carries no promise about its subject — never guess it."""
        out = _run()
        self.assertIn('Custom Tier', out)
        self.assertIn('cannot be inferred', out)

    # -- classes --------------------------------------------------------

    def test_detects_coding_class_mislabelled_as_maths(self):
        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        out = _run()
        self.assertIn('Coding 101', out)
        self.assertIn('Mathematics -> Coding', out)

    def test_correctly_labelled_class_is_not_reported_as_changing(self):
        right = ClassRoom.objects.create(
            name='Coding 202', school=self.school, department=self.dept,
            subject=self.coding)
        right.levels.add(self.coding_lv)

        out = _run()
        self.assertNotIn('Coding 202:', out)

    def test_mixed_subject_levels_are_ambiguous_not_guessed(self):
        mixed = ClassRoom.objects.create(
            name='Mixed Class', school=self.school, department=self.dept,
            subject=self.maths)
        mixed.levels.add(self.year5, self.coding_lv)

        out = _run()
        self.assertIn('Mixed Class', out)
        self.assertIn('AMBIGUOUS', out)
        # An ambiguous class must never appear as a proposed change.
        self.assertNotIn('Mixed Class: Mathematics ->', out)

    def test_class_with_null_subject_gets_a_proposal(self):
        orphan = ClassRoom.objects.create(
            name='Orphan Class', school=self.school, department=self.dept,
            subject=None)
        orphan.levels.add(self.coding_lv)

        out = _run()
        self.assertIn('Orphan Class', out)
        self.assertIn('(none) -> Coding', out)

    # -- fees -----------------------------------------------------------

    def test_billing_neutral_when_no_subject_fee_overrides(self):
        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        out = _run()
        self.assertIn('The repair is billing-neutral', out)

    def test_flags_a_class_whose_fee_would_move(self):
        """The risk this command exists to surface."""
        DepartmentSubject.objects.filter(
            department=self.dept, subject=self.maths,
        ).update(fee_override=Decimal('100.00'))
        DepartmentSubject.objects.filter(
            department=self.dept, subject=self.coding,
        ).update(fee_override=Decimal('250.00'))

        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        out = _run()
        self.assertIn('FEE MOVES', out)
        self.assertIn('100.00 -> 250.00', out)
        self.assertIn('would be billed differently', out)

    def test_fee_probe_does_not_persist_the_proposed_subject(self):
        """The fee 'after' figure is computed in memory — it must not leak."""
        DepartmentSubject.objects.filter(
            department=self.dept, subject=self.coding,
        ).update(fee_override=Decimal('250.00'))
        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        _run()

        wrong.refresh_from_db()
        self.assertEqual(wrong.subject_id, self.maths.id)

    # -- department mappings --------------------------------------------

    def test_reports_maths_level_mapped_under_a_non_maths_department(self):
        coding_only = Department.objects.create(
            school=self.school, name='IT', slug='it')
        DepartmentSubject.objects.create(department=coding_only, subject=self.coding)
        DepartmentLevel.objects.create(
            department=coding_only, level=self.year5, order=5)

        out = _run()
        self.assertIn('Department level mappings to review', out)
        self.assertIn('IT', out)
        self.assertIn('Year 5', out)

    # -- scoping and output ---------------------------------------------

    def test_school_filter_excludes_other_schools(self):
        other = School.objects.create(name='Other School', slug='other-school')
        other_dept = Department.objects.create(
            school=other, name='Other STEM', slug='other-stem')
        DepartmentSubject.objects.create(department=other_dept, subject=self.coding)
        elsewhere = ClassRoom.objects.create(
            name='Elsewhere Class', school=other, department=other_dept,
            subject=self.maths)
        elsewhere.levels.add(self.coding_lv)

        out = _run(school=str(self.school.id))
        self.assertNotIn('Elsewhere Class', out)

    def test_unknown_school_is_an_error_not_a_full_report(self):
        out = _run(school='no-such-school')
        self.assertIn('No school matches', out)
        self.assertNotIn('Read-only audit complete', out)

    def test_csv_contains_the_changed_rows(self):
        import csv as _csv
        import tempfile
        import os

        wrong = ClassRoom.objects.create(
            name='Coding 101', school=self.school, department=self.dept,
            subject=self.maths)
        wrong.levels.add(self.coding_lv)

        path = os.path.join(tempfile.mkdtemp(), 'audit.csv')
        _run(csv_path=path)

        with open(path, newline='', encoding='utf-8') as handle:
            rows = list(_csv.DictReader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['name'], 'Coding 101')
        self.assertEqual(rows[0]['old_subject'], 'Mathematics')
        self.assertEqual(rows[0]['new_subject'], 'Coding')

    def test_runs_on_an_empty_install(self):
        ClassRoom.objects.all().delete()
        out = _run()
        self.assertIn('Read-only audit complete', out)
