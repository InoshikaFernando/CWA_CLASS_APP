"""CPP-371 — Locations for classes.

Covers the Location model, the institute Locations management view
(list / create / edit / delete), and the class create/edit flows wiring a
location and the online flag onto a class.
"""

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, DepartmentTeacher,
    DepartmentLevel, Subject, Level, ClassRoom, Location,
)


class LocationTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'loc_admin', 'wlhtestmails+locadmin@gmail.com', 'password1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.admin_user.roles.add(admin_role, owner_role)

        cls.school = School.objects.create(
            name='Loc School', slug='loc-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.admin_user, defaults={'role': 'admin'})

        # A second, unrelated institute (for scoping checks)
        cls.other_admin = CustomUser.objects.create_user(
            'loc_other', 'wlhtestmails+locother@gmail.com', 'password1!',
        )
        cls.other_admin.roles.add(admin_role, owner_role)
        cls.other_school = School.objects.create(
            name='Other School', slug='other-school', admin=cls.other_admin,
        )

        cls.maths = Subject.objects.get_or_create(
            slug='mathematics',
            defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=1,
            defaults={'display_name': 'Year 1', 'subject': cls.maths},
        )[0]

        cls.dept = Department.objects.create(
            school=cls.school, name='Mathematics', slug='maths', head=cls.admin_user,
        )
        DepartmentSubject.objects.create(department=cls.dept, subject=cls.maths)
        DepartmentTeacher.objects.create(department=cls.dept, teacher=cls.admin_user)
        DepartmentLevel.objects.create(department=cls.dept, level=cls.level, order=1)


class LocationModelTest(LocationTestBase):

    def test_str_and_defaults(self):
        loc = Location.objects.create(school=self.school, name='Main Campus')
        self.assertEqual(str(loc), 'Main Campus')
        self.assertEqual(loc.address, '')
        self.assertFalse(loc.is_online)
        self.assertTrue(loc.is_active)

    def test_delivery_mode_in_person(self):
        loc = Location.objects.create(school=self.school, name='Room 3')
        cls = ClassRoom.objects.create(name='C1', school=self.school, location=loc)
        self.assertEqual(cls.delivery_mode, 'in_person')
        self.assertEqual(cls.get_delivery_mode_display(), 'In-person')

    def test_delivery_mode_online(self):
        cls = ClassRoom.objects.create(name='C2', school=self.school, is_online=True)
        self.assertEqual(cls.delivery_mode, 'online')
        self.assertEqual(cls.get_delivery_mode_display(), 'Online')

    def test_delivery_mode_hybrid(self):
        loc = Location.objects.create(school=self.school, name='Room 3')
        cls = ClassRoom.objects.create(
            name='C3', school=self.school, location=loc, is_online=True,
        )
        self.assertEqual(cls.delivery_mode, 'hybrid')

    def test_delivery_mode_unset(self):
        cls = ClassRoom.objects.create(name='C4', school=self.school)
        self.assertEqual(cls.delivery_mode, '')
        self.assertEqual(cls.get_delivery_mode_display(), '')

    def test_deleting_location_nulls_class_field(self):
        """SET_NULL keeps the class but clears its location."""
        loc = Location.objects.create(school=self.school, name='Temp')
        cls = ClassRoom.objects.create(name='C5', school=self.school, location=loc)
        loc.delete()
        cls.refresh_from_db()
        self.assertIsNone(cls.location)
        self.assertTrue(ClassRoom.objects.filter(id=cls.id).exists())


class LocationManageViewTest(LocationTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='loc_admin', password='password1!')
        self.url = reverse('admin_school_locations', kwargs={'school_id': self.school.id})

    def test_list_page_renders(self):
        Location.objects.create(school=self.school, name='Campus A')
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Campus A')

    def test_create_location_with_address(self):
        resp = self.client.post(self.url, {
            'action': 'create',
            'name': 'North Branch',
            'address': '12 King St',
            'is_online': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        loc = Location.objects.get(name='North Branch')
        self.assertEqual(loc.school, self.school)
        self.assertEqual(loc.address, '12 King St')
        self.assertTrue(loc.is_online)

    def test_create_location_address_optional(self):
        self.client.post(self.url, {'action': 'create', 'name': 'No Address Loc'})
        loc = Location.objects.get(name='No Address Loc')
        self.assertEqual(loc.address, '')
        self.assertFalse(loc.is_online)

    def test_create_requires_name(self):
        self.client.post(self.url, {'action': 'create', 'name': '   '})
        self.assertFalse(Location.objects.filter(school=self.school).exists())

    def test_edit_location(self):
        loc = Location.objects.create(school=self.school, name='Old', is_online=False)
        self.client.post(self.url, {
            'action': 'edit',
            'location_id': loc.id,
            'name': 'New Name',
            'address': 'Updated address',
            'is_online': 'on',
        })
        loc.refresh_from_db()
        self.assertEqual(loc.name, 'New Name')
        self.assertEqual(loc.address, 'Updated address')
        self.assertTrue(loc.is_online)

    def test_edit_unchecking_online(self):
        loc = Location.objects.create(school=self.school, name='L', is_online=True)
        # Omitting is_online mimics an unchecked checkbox.
        self.client.post(self.url, {
            'action': 'edit', 'location_id': loc.id, 'name': 'L',
        })
        loc.refresh_from_db()
        self.assertFalse(loc.is_online)

    def test_delete_location(self):
        loc = Location.objects.create(school=self.school, name='Delete Me')
        self.client.post(self.url, {'action': 'delete', 'location_id': loc.id})
        self.assertFalse(Location.objects.filter(id=loc.id).exists())

    def test_cannot_edit_other_schools_location(self):
        other = Location.objects.create(school=self.other_school, name='Foreign')
        resp = self.client.post(self.url, {
            'action': 'edit', 'location_id': other.id, 'name': 'Hacked',
        })
        self.assertEqual(resp.status_code, 404)
        other.refresh_from_db()
        self.assertEqual(other.name, 'Foreign')


class ClassCreationWithLocationTest(LocationTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='loc_admin', password='password1!')
        self.loc = Location.objects.create(school=self.school, name='Campus A')

    def test_create_class_with_location_and_online(self):
        resp = self.client.post(reverse('create_class'), {
            'name': 'Located Class',
            'department': str(self.dept.id),
            'levels': [str(self.level.id)],
            'location': str(self.loc.id),
            'is_online': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='Located Class')
        self.assertEqual(cls.location, self.loc)
        self.assertTrue(cls.is_online)
        self.assertEqual(cls.delivery_mode, 'hybrid')

    def test_create_class_without_location(self):
        resp = self.client.post(reverse('create_class'), {
            'name': 'No Loc Class',
            'department': str(self.dept.id),
            'levels': [str(self.level.id)],
        })
        self.assertEqual(resp.status_code, 302)
        cls = ClassRoom.objects.get(name='No Loc Class')
        self.assertIsNone(cls.location)
        self.assertFalse(cls.is_online)

    def test_create_rejects_foreign_location(self):
        foreign = Location.objects.create(school=self.other_school, name='Foreign')
        self.client.post(reverse('create_class'), {
            'name': 'Foreign Loc Class',
            'department': str(self.dept.id),
            'levels': [str(self.level.id)],
            'location': str(foreign.id),
        })
        cls = ClassRoom.objects.get(name='Foreign Loc Class')
        self.assertIsNone(cls.location)

    def test_edit_class_sets_and_clears_location(self):
        cls = ClassRoom.objects.create(
            name='Editable', school=self.school, department=self.dept,
            subject=self.maths,
        )
        edit_url = reverse('edit_class', kwargs={'class_id': cls.id})
        # Set location + online
        self.client.post(edit_url, {
            'name': 'Editable',
            'levels': [str(self.level.id)],
            'location': str(self.loc.id),
            'is_online': 'on',
        })
        cls.refresh_from_db()
        self.assertEqual(cls.location, self.loc)
        self.assertTrue(cls.is_online)
        # Clear location + online (omit both)
        self.client.post(edit_url, {
            'name': 'Editable',
            'levels': [str(self.level.id)],
        })
        cls.refresh_from_db()
        self.assertIsNone(cls.location)
        self.assertFalse(cls.is_online)
