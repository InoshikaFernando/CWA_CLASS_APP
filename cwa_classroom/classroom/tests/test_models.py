from django.db import IntegrityError
from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import (
    School, Department, DepartmentSubject, Subject, Level, DepartmentLevel,
)


class DepartmentLevelTestBase(TestCase):
    """Shared fixtures for department-level tests."""

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'testadmin', 'admin@test.com', 'pass1234',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin_user.roles.add(admin_role)

        cls.school_a = School.objects.create(
            name='School A', slug='school-a', admin=cls.admin_user,
        )
        cls.school_b = School.objects.create(
            name='School B', slug='school-b', admin=cls.admin_user,
        )

        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.coding = Subject.objects.get_or_create(
            slug='coding',
            defaults={'name': 'Coding', 'is_active': True},
        )[0]

        # Ensure year levels exist with subject=Mathematics
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

        cls.dept_a_maths = Department.objects.create(
            school=cls.school_a, name='Mathematics', slug='maths',
        )
        DepartmentSubject.objects.create(department=cls.dept_a_maths, subject=cls.maths)
        cls.dept_b_maths = Department.objects.create(
            school=cls.school_b, name='Mathematics', slug='maths',
        )
        DepartmentSubject.objects.create(department=cls.dept_b_maths, subject=cls.maths)
        cls.dept_a_coding = Department.objects.create(
            school=cls.school_a, name='Coding', slug='coding',
        )
        DepartmentSubject.objects.create(department=cls.dept_a_coding, subject=cls.coding)


class DepartmentLevelModelTest(DepartmentLevelTestBase):

    def test_create_department_level(self):
        dl = DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[0], order=1,
        )
        self.assertEqual(dl.department, self.dept_a_maths)
        self.assertEqual(dl.level, self.year_levels[0])
        self.assertEqual(dl.order, 1)

    def test_unique_constraint(self):
        DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[0], order=1,
        )
        with self.assertRaises(IntegrityError):
            DepartmentLevel.objects.create(
                department=self.dept_a_maths, level=self.year_levels[0], order=2,
            )

    def test_multiple_departments_share_same_level(self):
        """Two departments from different schools can map the same Year level."""
        dl_a = DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[2], order=3,
        )
        dl_b = DepartmentLevel.objects.create(
            department=self.dept_b_maths, level=self.year_levels[2], order=3,
        )
        self.assertEqual(dl_a.level, dl_b.level)
        self.assertEqual(DepartmentLevel.objects.filter(level=self.year_levels[2]).count(), 2)

    def test_effective_display_name_default(self):
        dl = DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[0], order=1,
        )
        self.assertEqual(dl.effective_display_name, 'Year 1')

    def test_effective_display_name_override(self):
        dl = DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[1], order=1,
            local_display_name='Year 1 (AU)',
        )
        self.assertEqual(dl.effective_display_name, 'Year 1 (AU)')

    def test_mapped_levels_m2m(self):
        for i, lv in enumerate(self.year_levels[:3]):
            DepartmentLevel.objects.create(
                department=self.dept_a_maths, level=lv, order=i + 1,
            )
        mapped = list(self.dept_a_maths.mapped_levels.order_by('level_number'))
        self.assertEqual(len(mapped), 3)
        self.assertEqual(mapped[0].display_name, 'Year 1')
        self.assertEqual(mapped[2].display_name, 'Year 3')

    def test_ordering(self):
        DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[2], order=1,
        )
        DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[0], order=2,
        )
        dls = list(
            DepartmentLevel.objects.filter(department=self.dept_a_maths),
        )
        self.assertEqual(dls[0].level.level_number, 3)  # order=1
        self.assertEqual(dls[1].level.level_number, 1)  # order=2

    def test_level_subject_fk(self):
        """Year levels have subject=Mathematics, custom levels have subject=None."""
        for lv in self.year_levels:
            self.assertEqual(lv.subject, self.maths)

    def test_str(self):
        dl = DepartmentLevel.objects.create(
            department=self.dept_a_maths, level=self.year_levels[0], order=1,
        )
        self.assertIn('Mathematics', str(dl))
        self.assertIn('Year 1', str(dl))
