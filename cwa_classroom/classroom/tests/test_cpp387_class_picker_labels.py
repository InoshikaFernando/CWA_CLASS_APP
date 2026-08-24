"""
test_cpp387_class_picker_labels.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
A class picked while adding a student must show when it runs and where
(CPP-387). Two classes can share a name and a subject, so name-only rows in the
picker made it impossible to tell the Tuesday class from the Thursday one.

Coverage:
  ClassRoom.schedule_label:
    - day + start + end, day only, times only, start only, nothing set
  ClassRoom.venue_label:
    - a location, online, hybrid (location + online), nothing set
  ClassRoom.picker_label (one-line <select> label):
    - names schedule and venue; says so when either is missing

  Rendered pickers (the time and location reach the page, not just the model):
    - Add Student modal            (admin_school_students)
    - Student edit modal classes   (admin_school_student_edit_modal)
    - Add Parent inline student    (admin_school_add_parent)
    - Move-to-class dropdown       (class_detail)
"""

from datetime import time

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    ClassRoom, ClassStudent, Location, School, SchoolStudent, Subject,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role(name, display_name=None):
    r, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return r


def _make_owner(username):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@test.com', first_name='Owner', last_name='User',
    )
    UserRole.objects.create(user=u, role=_role(Role.INSTITUTE_OWNER, 'Institute Owner'))
    return u


def _make_student(username, school):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@student.test', first_name='Test', last_name='Student',
    )
    UserRole.objects.create(user=u, role=_role(Role.STUDENT, 'Student'))
    SchoolStudent.objects.create(school=school, student=u)
    return u


# ---------------------------------------------------------------------------
# Model labels
# ---------------------------------------------------------------------------

class TestScheduleLabel(TestCase):

    def _cls(self, **kwargs):
        return ClassRoom(name='Year 10 Maths', **kwargs)

    def test_day_and_time_range(self):
        c = self._cls(day='tuesday', start_time=time(16, 0), end_time=time(17, 30))
        self.assertEqual(c.schedule_label, 'Tuesday 4:00 PM – 5:30 PM')

    def test_day_only(self):
        self.assertEqual(self._cls(day='saturday').schedule_label, 'Saturday')

    def test_times_without_a_day(self):
        c = self._cls(start_time=time(9, 0), end_time=time(10, 0))
        self.assertEqual(c.schedule_label, '9:00 AM – 10:00 AM')

    def test_start_time_only(self):
        c = self._cls(day='monday', start_time=time(18, 15))
        self.assertEqual(c.schedule_label, 'Monday 6:15 PM')

    def test_blank_when_nothing_scheduled(self):
        self.assertEqual(self._cls().schedule_label, '')


class TestVenueLabel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.owner = _make_owner('io_venue_label')
        cls.school = School.objects.create(name='Venue School', admin=cls.owner, is_active=True)
        cls.location = Location.objects.create(school=cls.school, name='Hamilton Campus')

    def test_location_name(self):
        c = ClassRoom.objects.create(name='A', school=self.school, location=self.location)
        self.assertEqual(c.venue_label, 'Hamilton Campus')

    def test_online_only(self):
        c = ClassRoom.objects.create(name='B', school=self.school, is_online=True)
        self.assertEqual(c.venue_label, 'Online')

    def test_hybrid_names_both(self):
        c = ClassRoom.objects.create(
            name='C', school=self.school, location=self.location, is_online=True,
        )
        self.assertEqual(c.venue_label, 'Hamilton Campus + Online')

    def test_blank_when_no_venue(self):
        c = ClassRoom.objects.create(name='D', school=self.school)
        self.assertEqual(c.venue_label, '')


class TestPickerLabel(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.owner = _make_owner('io_picker_label')
        cls.school = School.objects.create(name='Picker School', admin=cls.owner, is_active=True)
        cls.location = Location.objects.create(school=cls.school, name='Hamilton Campus')

    def test_names_schedule_and_venue(self):
        c = ClassRoom.objects.create(
            name='Year 10 Maths', school=self.school, location=self.location,
            day='tuesday', start_time=time(16, 0), end_time=time(17, 30),
        )
        self.assertEqual(
            c.picker_label,
            'Year 10 Maths — Tuesday 4:00 PM – 5:30 PM · Hamilton Campus',
        )

    def test_says_so_when_schedule_and_venue_missing(self):
        c = ClassRoom.objects.create(name='Year 10 Maths', school=self.school)
        self.assertEqual(
            c.picker_label,
            'Year 10 Maths — Time not set · Location not set',
        )


# ---------------------------------------------------------------------------
# Rendered pickers
# ---------------------------------------------------------------------------

class ClassPickerRenderMixin:
    """A school with two same-named classes that differ only by day and venue."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = _make_owner(f'io_{cls.__name__.lower()}')
        cls.school = School.objects.create(
            name='Render School', admin=cls.owner, is_active=True,
        )
        cls.subject, _ = Subject.objects.get_or_create(
            slug='maths', defaults={'name': 'Maths'},
        )
        cls.hamilton = Location.objects.create(school=cls.school, name='Hamilton Campus')
        cls.rotorua = Location.objects.create(school=cls.school, name='Rotorua Campus')
        cls.tuesday_class = ClassRoom.objects.create(
            name='Year 10 Maths', school=cls.school, subject=cls.subject,
            location=cls.hamilton, day='tuesday',
            start_time=time(16, 0), end_time=time(17, 30),
        )
        cls.thursday_class = ClassRoom.objects.create(
            name='Year 10 Maths', school=cls.school, subject=cls.subject,
            location=cls.rotorua, day='thursday',
            start_time=time(9, 0), end_time=time(10, 30),
        )

    def _client(self):
        c = Client()
        c.force_login(self.owner)
        return c

    def assertBothClassesDistinguishable(self, resp):
        self.assertContains(resp, 'Tuesday 4:00 PM – 5:30 PM', html=False)
        self.assertContains(resp, 'Thursday 9:00 AM – 10:30 AM', html=False)
        self.assertContains(resp, 'Hamilton Campus')
        self.assertContains(resp, 'Rotorua Campus')


class TestAddStudentModalPicker(ClassPickerRenderMixin, TestCase):

    def test_time_and_location_listed(self):
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        self.assertBothClassesDistinguishable(self._client().get(url))

    def test_missing_schedule_and_venue_are_named(self):
        ClassRoom.objects.create(name='Unscheduled Maths', school=self.school)
        url = reverse('admin_school_students', kwargs={'school_id': self.school.id})
        resp = self._client().get(url)
        self.assertContains(resp, 'Time not set')
        self.assertContains(resp, 'Location not set')


class TestStudentEditModalPicker(ClassPickerRenderMixin, TestCase):

    def test_time_and_location_listed(self):
        student = _make_student('editmodal_student', self.school)
        url = reverse(
            'admin_school_student_edit_modal',
            kwargs={'school_id': self.school.id, 'student_id': student.id},
        )
        self.assertBothClassesDistinguishable(self._client().get(url))


class TestAddParentInlineStudentPicker(ClassPickerRenderMixin, TestCase):

    def test_time_and_location_listed(self):
        url = reverse('admin_school_add_parent', kwargs={'school_id': self.school.id})
        self.assertBothClassesDistinguishable(self._client().get(url))


class TestMoveTargetDropdown(ClassPickerRenderMixin, TestCase):

    def test_option_names_time_and_location(self):
        student = _make_student('move_student', self.school)
        ClassStudent.objects.create(classroom=self.tuesday_class, student=student)
        url = reverse('class_detail', kwargs={'class_id': self.tuesday_class.id})
        resp = self._client().get(url)
        self.assertContains(
            resp,
            'Year 10 Maths — Thursday 9:00 AM – 10:30 AM · Rotorua Campus',
        )
