"""CPP-373 — Per-location colour + colour-coded class tile borders.

Covers:
  - the ``Location.color`` field (default, save, server-side validation);
  - the Locations management view create/edit flows storing/validating a
    colour and surfacing an invalid colour as a form error;
  - the Classes page tile rendering a location-coloured left border, and the
    graceful fallback for classes with no location / no colour.
"""

from django.core.exceptions import ValidationError
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolTeacher, Department, DepartmentSubject, DepartmentTeacher,
    DepartmentLevel, Subject, Level, ClassRoom, Location,
)


class ColorTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.admin_user = CustomUser.objects.create_user(
            'color_admin', 'wlhtestmails+coloradmin@gmail.com', 'password1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'},
        )
        cls.admin_user.roles.add(admin_role, owner_role)

        cls.school = School.objects.create(
            name='Colour School', slug='colour-school', admin=cls.admin_user,
        )
        SchoolTeacher.objects.update_or_create(
            school=cls.school, teacher=cls.admin_user, defaults={'role': 'admin'})

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


class LocationColorModelTest(ColorTestBase):

    def test_color_defaults_to_blank(self):
        loc = Location.objects.create(school=self.school, name='No Colour')
        self.assertEqual(loc.color, '')

    def test_color_saves(self):
        loc = Location.objects.create(
            school=self.school, name='Blue Room', color='#4f46e5',
        )
        loc.refresh_from_db()
        self.assertEqual(loc.color, '#4f46e5')

    def test_valid_color_passes_full_clean(self):
        loc = Location(school=self.school, name='Green', color='#00ff00')
        loc.full_clean()  # should not raise

    def test_blank_color_passes_full_clean(self):
        loc = Location(school=self.school, name='Plain', color='')
        loc.full_clean()  # blank is allowed

    def test_invalid_color_rejected_by_full_clean(self):
        loc = Location(school=self.school, name='Bad', color='blue')
        with self.assertRaises(ValidationError) as ctx:
            loc.full_clean()
        self.assertIn('color', ctx.exception.message_dict)

    def test_short_hex_rejected(self):
        loc = Location(school=self.school, name='Short', color='#fff')
        with self.assertRaises(ValidationError):
            loc.full_clean()


class LocationColorManageViewTest(ColorTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='color_admin', password='password1!')
        self.url = reverse('admin_school_locations', kwargs={'school_id': self.school.id})

    def test_create_location_with_color(self):
        resp = self.client.post(self.url, {
            'action': 'create',
            'name': 'Coloured Campus',
            'use_color': 'on',
            'color': '#4f46e5',
        })
        self.assertEqual(resp.status_code, 302)
        loc = Location.objects.get(name='Coloured Campus')
        self.assertEqual(loc.color, '#4f46e5')

    def test_create_without_use_color_stores_blank(self):
        # The native colour input always submits a value; without the
        # ``use_color`` checkbox that value is ignored.
        self.client.post(self.url, {
            'action': 'create',
            'name': 'Uncoloured',
            'color': '#123456',
        })
        loc = Location.objects.get(name='Uncoloured')
        self.assertEqual(loc.color, '')

    def test_create_invalid_color_surfaces_error(self):
        resp = self.client.post(self.url, {
            'action': 'create',
            'name': 'Bad Colour',
            'use_color': 'on',
            'color': 'not-a-colour',
        }, follow=True)
        # Location is not created and an error message is shown.
        self.assertFalse(Location.objects.filter(name='Bad Colour').exists())
        msgs = [m.message for m in resp.context['messages']]
        self.assertTrue(any('not a valid colour' in m for m in msgs), msgs)

    def test_edit_sets_and_clears_color(self):
        loc = Location.objects.create(school=self.school, name='Editable')
        # Set a colour.
        self.client.post(self.url, {
            'action': 'edit', 'location_id': loc.id, 'name': 'Editable',
            'use_color': 'on', 'color': '#ff8800',
        })
        loc.refresh_from_db()
        self.assertEqual(loc.color, '#ff8800')
        # Clear it (omit use_color, mimicking an unchecked box).
        self.client.post(self.url, {
            'action': 'edit', 'location_id': loc.id, 'name': 'Editable',
            'color': '#ff8800',
        })
        loc.refresh_from_db()
        self.assertEqual(loc.color, '')

    def test_edit_invalid_color_surfaces_error_and_keeps_old(self):
        loc = Location.objects.create(
            school=self.school, name='Keep', color='#4f46e5',
        )
        resp = self.client.post(self.url, {
            'action': 'edit', 'location_id': loc.id, 'name': 'Keep',
            'use_color': 'on', 'color': '#zzzzzz',
        }, follow=True)
        loc.refresh_from_db()
        self.assertEqual(loc.color, '#4f46e5')  # unchanged
        msgs = [m.message for m in resp.context['messages']]
        self.assertTrue(any('not a valid colour' in m for m in msgs), msgs)

    def test_color_swatch_renders_on_list(self):
        Location.objects.create(
            school=self.school, name='Swatched', color='#abcdef',
        )
        resp = self.client.get(self.url)
        self.assertContains(resp, 'background-color: #abcdef')


class ClassTileBorderColorTest(ColorTestBase):
    """The Classes page tile borders are tinted by the class location colour."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='color_admin', password='password1!')
        self.url = reverse('hod_manage_classes')

    def test_tile_renders_location_border_color(self):
        loc = Location.objects.create(
            school=self.school, name='Purple Hall', color='#4f46e5',
        )
        ClassRoom.objects.create(
            name='Coloured Class', school=self.school, department=self.dept,
            subject=self.maths, location=loc,
        )
        resp = self.client.get(self.url)
        self.assertContains(resp, 'border-left-color: #4f46e5')
        self.assertContains(resp, 'data-location-color="#4f46e5"')

    def test_tile_without_location_has_no_border_color(self):
        ClassRoom.objects.create(
            name='Plain Class', school=self.school, department=self.dept,
            subject=self.maths,
        )
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'data-location-color')

    def test_tile_with_colorless_location_falls_back(self):
        loc = Location.objects.create(school=self.school, name='No Colour Loc')
        ClassRoom.objects.create(
            name='Fallback Class', school=self.school, department=self.dept,
            subject=self.maths, location=loc,
        )
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'data-location-color')
