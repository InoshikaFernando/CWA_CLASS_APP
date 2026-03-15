from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, Subject, Level, DepartmentLevel,
)


class DepartmentManageLevelsTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'testadmin', 'admin@test.com', 'pass1234',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin_user.roles.add(admin_role)

        cls.school = School.objects.create(
            name='Test School', slug='test-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.create(
            school=cls.school, teacher=cls.admin_user, role='admin',
        )

        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.coding = Subject.objects.get_or_create(
            slug='coding',
            defaults={'name': 'Coding', 'is_active': True},
        )[0]

        # Year levels 1-9 (global, subject=Mathematics)
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

        # Basic facts level (should never appear)
        cls.bf_level, _ = Level.objects.get_or_create(
            level_number=100,
            defaults={'display_name': 'Addition L1', 'subject': cls.maths},
        )

        # School custom level
        cls.custom_level, _ = Level.objects.get_or_create(
            level_number=200,
            defaults={'display_name': 'CWA Level 01', 'school': cls.school},
        )

        cls.dept_maths = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths',
            subject=cls.maths,
        )
        cls.dept_coding = Department.objects.create(
            school=cls.school, name='Coding', slug='coding',
            subject=cls.coding,
        )
        cls.dept_custom = Department.objects.create(
            school=cls.school, name='Custom', slug='custom',
        )


class DepartmentManageLevelsViewTest(DepartmentManageLevelsTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='testadmin', password='pass1234')

    def test_page_loads(self):
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Manage Curriculum Levels')

    def test_maths_dept_shows_year_levels_only(self):
        """Maths department should show Year 1-9, not Basic Facts."""
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.get(url)
        self.assertContains(resp, 'Year 1')
        self.assertContains(resp, 'Year 9')
        self.assertNotContains(resp, 'Addition L1')

    def test_custom_dept_shows_school_levels(self):
        """Custom department (no subject) should show school custom levels."""
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_custom.id])
        resp = self.client.get(url)
        self.assertContains(resp, 'CWA Level 01')
        # Year levels should not appear as checkboxes (Level 1 text in form)
        self.assertNotContains(resp, 'Level 1</p>')

    def test_post_adds_level_mapping(self):
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.post(url, {
            'level_ids': [str(self.year_levels[0].id), str(self.year_levels[1].id)],
        })
        self.assertEqual(resp.status_code, 302)
        count = DepartmentLevel.objects.filter(department=self.dept_maths).count()
        self.assertEqual(count, 2)

    def test_post_removes_unchecked_levels(self):
        """Unchecking a level should remove its DepartmentLevel row."""
        # Pre-create mappings for Year 1, 2, 3
        for lv in self.year_levels[:3]:
            DepartmentLevel.objects.create(
                department=self.dept_maths, level=lv, order=lv.level_number,
            )
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        # POST with only Year 1 selected → Year 2 and 3 should be removed
        resp = self.client.post(url, {
            'level_ids': [str(self.year_levels[0].id)],
        })
        self.assertEqual(resp.status_code, 302)
        remaining = DepartmentLevel.objects.filter(department=self.dept_maths)
        self.assertEqual(remaining.count(), 1)
        self.assertEqual(remaining.first().level, self.year_levels[0])

    def test_post_saves_local_display_name(self):
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        lv = self.year_levels[1]  # Year 2
        resp = self.client.post(url, {
            'level_ids': [str(lv.id)],
            f'local_name_{lv.id}': 'Year 1 (AU)',
        })
        self.assertEqual(resp.status_code, 302)
        dl = DepartmentLevel.objects.get(department=self.dept_maths, level=lv)
        self.assertEqual(dl.local_display_name, 'Year 1 (AU)')

    def test_post_updates_existing_local_display_name(self):
        """Changing a local name on an already-mapped level should update it."""
        lv = self.year_levels[0]
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=lv,
            local_display_name='Old Name', order=1,
        )
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.post(url, {
            'level_ids': [str(lv.id)],
            f'local_name_{lv.id}': 'New Name',
        })
        self.assertEqual(resp.status_code, 302)
        dl = DepartmentLevel.objects.get(department=self.dept_maths, level=lv)
        self.assertEqual(dl.local_display_name, 'New Name')

    def test_cannot_map_basic_facts_to_maths_dept(self):
        """Even if someone manually submits a Basic Facts level ID, it should be rejected."""
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.post(url, {
            'level_ids': [str(self.bf_level.id)],
        })
        self.assertEqual(resp.status_code, 302)
        count = DepartmentLevel.objects.filter(
            department=self.dept_maths, level=self.bf_level,
        ).count()
        self.assertEqual(count, 0)

    def test_auth_required(self):
        self.client.logout()
        url = reverse('admin_department_levels', args=[self.school.id, self.dept_maths.id])
        resp = self.client.get(url)
        self.assertNotEqual(resp.status_code, 200)


class DepartmentDetailLevelsTest(DepartmentManageLevelsTestBase):
    """Test that department detail page shows mapped levels."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='testadmin', password='pass1234')

    def test_detail_shows_mapped_levels(self):
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[0], order=1,
        )
        DepartmentLevel.objects.create(
            department=self.dept_maths, level=self.year_levels[1], order=2,
            local_display_name='Year 1 (AU)',
        )
        url = reverse('admin_department_detail', args=[self.school.id, self.dept_maths.id])
        resp = self.client.get(url)
        self.assertContains(resp, 'Year 1')
        self.assertContains(resp, 'Year 1 (AU)')
        self.assertContains(resp, 'Manage Levels')

    def test_detail_shows_no_levels_message(self):
        url = reverse('admin_department_detail', args=[self.school.id, self.dept_maths.id])
        resp = self.client.get(url)
        self.assertContains(resp, 'No levels mapped')
