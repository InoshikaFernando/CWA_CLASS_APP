from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.models import CustomUser
from classroom.models import (
    School, Department, DepartmentSubject, Subject, Level, DepartmentLevel,
)


class BackfillDepartmentLevelsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            'admin', 'wlhtestmails+admin@gmail.com', 'password1!',
        )
        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin,
        )
        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]

        cls.year_levels = []
        for i in range(1, 10):
            lv, _ = Level.objects.get_or_create(
                level_number=i,
                defaults={'display_name': f'Year {i}', 'subject': cls.maths},
            )
            if not lv.subject:
                lv.subject = cls.maths
                lv.save(update_fields=['subject'])
            cls.year_levels.append(lv)

        # Basic Facts level (should NOT be backfilled)
        Level.objects.get_or_create(
            level_number=100,
            defaults={'display_name': 'Addition L1', 'subject': cls.maths},
        )

        # Department WITHOUT existing DepartmentLevel rows
        cls.dept = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths',
        )
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.maths)

    def test_backfill_creates_rows(self):
        """Running backfill should create DepartmentLevel rows for Year 1-9."""
        self.assertEqual(DepartmentLevel.objects.filter(department=self.dept).count(), 0)
        out = StringIO()
        call_command('backfill_department_levels', stdout=out)
        count = DepartmentLevel.objects.filter(department=self.dept).count()
        self.assertEqual(count, 9)
        self.assertIn('9 levels mapped', out.getvalue())

    def test_backfill_idempotent(self):
        """Running backfill twice should not create duplicates."""
        call_command('backfill_department_levels', stdout=StringIO())
        count1 = DepartmentLevel.objects.filter(department=self.dept).count()
        call_command('backfill_department_levels', stdout=StringIO())
        count2 = DepartmentLevel.objects.filter(department=self.dept).count()
        self.assertEqual(count1, count2)

    def test_backfill_excludes_basic_facts(self):
        """Basic Facts levels (100-199) should not be backfilled."""
        call_command('backfill_department_levels', stdout=StringIO())
        bf_mapped = DepartmentLevel.objects.filter(
            department=self.dept, level__level_number__gte=100, level__level_number__lt=200,
        ).count()
        self.assertEqual(bf_mapped, 0)

    def test_dry_run(self):
        """--dry-run should not create any rows."""
        out = StringIO()
        call_command('backfill_department_levels', dry_run=True, stdout=out)
        count = DepartmentLevel.objects.filter(department=self.dept).count()
        self.assertEqual(count, 0)
        self.assertIn('DRY RUN', out.getvalue())
        self.assertIn('9 levels would be mapped', out.getvalue())

    def test_skips_dept_without_subject(self):
        """Departments without a subject should be skipped."""
        dept_custom = Department.objects.create(
            school=self.school, name='Custom', slug='custom',
        )
        call_command('backfill_department_levels', stdout=StringIO())
        count = DepartmentLevel.objects.filter(department=dept_custom).count()
        self.assertEqual(count, 0)
