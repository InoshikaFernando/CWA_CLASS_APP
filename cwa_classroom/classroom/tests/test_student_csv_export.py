"""
test_student_csv_export.py
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Tests for SchoolStudentExportCSVView — downloading a school's students as CSV.

Coverage:
  - CSV download responds with text/csv + attachment Content-Disposition
  - Header row contains the expected columns
  - One row per student, with parents (parent1/parent2) populated
  - A student enrolled in multiple classes gets a single row with classes
    joined into the "Classes" column and the correct "Class Count"
  - Guardian (non-user) parents are exported alongside parent-user links
  - Access control: a user without access cannot export another school's roster
"""

import csv
import io

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, SchoolStudent, ClassRoom, ClassStudent, ParentStudent, Subject,
    Guardian, StudentGuardian,
)


def _role(name, display_name=None):
    r, _ = Role.objects.get_or_create(
        name=name,
        defaults={'display_name': display_name or name.replace('_', ' ').title()},
    )
    return r


def _make_owner(username):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@test.com', first_name='Hoi', last_name='Owner',
    )
    UserRole.objects.create(user=u, role=_role(Role.INSTITUTE_OWNER, 'Institute Owner'))
    UserRole.objects.create(user=u, role=_role(Role.HEAD_OF_INSTITUTE, 'Head of Institute'))
    return u


def _make_student(username, school, **kwargs):
    u = CustomUser.objects.create_user(
        username=username, password='pass1234!',
        email=f'{username}@student.test',
        first_name=kwargs.get('first_name', 'Test'),
        last_name=kwargs.get('last_name', 'Student'),
    )
    UserRole.objects.create(user=u, role=_role(Role.STUDENT, 'Student'))
    SchoolStudent.objects.create(school=school, student=u)
    return u


def _make_class(school, name):
    subject, _ = Subject.objects.get_or_create(slug='cs', defaults={'name': 'CS'})
    return ClassRoom.objects.create(name=name, school=school, subject=subject, is_active=True)


class StudentCSVExportTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.owner = _make_owner('hoi')
        self.school = School.objects.create(name='Greenwood School', admin=self.owner, is_active=True)
        self.url = reverse('admin_school_students_export_csv', args=[self.school.id])

    def _download(self):
        self.client.force_login(self.owner)
        resp = self.client.get(self.url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('attachment', resp['Content-Disposition'])
        body = resp.content.decode('utf-8')
        return list(csv.reader(io.StringIO(body)))

    def test_header_row(self):
        rows = self._download()
        header = rows[0]
        for col in ['Email', 'Parent 1 Name', 'Parent 2 Email', 'Classes', 'Class Count']:
            self.assertIn(col, header)

    def test_multi_class_student_single_row(self):
        """A student in two classes => one row, both classes in Classes column."""
        student = _make_student('alice', self.school, first_name='Alice', last_name='Adams')
        c1 = _make_class(self.school, 'Maths')
        c2 = _make_class(self.school, 'Science')
        ClassStudent.objects.create(classroom=c1, student=student)
        ClassStudent.objects.create(classroom=c2, student=student)

        rows = self._download()
        header, data = rows[0], rows[1:]
        self.assertEqual(len(data), 1)  # one row, not two

        row = dict(zip(header, data[0]))
        self.assertEqual(row['Email'], 'alice@student.test')
        self.assertEqual(row['Class Count'], '2')
        self.assertIn('Maths', row['Classes'])
        self.assertIn('Science', row['Classes'])
        self.assertIn('|', row['Classes'])

    def test_parents_populated_from_both_systems(self):
        student = _make_student('bob', self.school, first_name='Bob', last_name='Brown')

        # Parent-user link (ParentStudent)
        parent_user = CustomUser.objects.create_user(
            username='mum', password='pass1234!', email='mum@home.test',
            first_name='Mary', last_name='Brown',
        )
        UserRole.objects.create(user=parent_user, role=_role(Role.PARENT, 'Parent'))
        ParentStudent.objects.create(
            parent=parent_user, student=student, school=self.school,
            relationship='mother', is_primary_contact=True,
        )

        # Guardian record (StudentGuardian)
        guardian = Guardian.objects.create(
            school=self.school, first_name='John', last_name='Brown',
            email='dad@home.test', relationship='father',
        )
        StudentGuardian.objects.create(student=student, guardian=guardian)

        rows = self._download()
        row = dict(zip(rows[0], rows[1]))
        # Primary contact (mother) listed first.
        self.assertEqual(row['Parent 1 Name'], 'Mary Brown')
        self.assertEqual(row['Parent 1 Email'], 'mum@home.test')
        self.assertEqual(row['Parent 2 Name'], 'John Brown')
        self.assertEqual(row['Parent 2 Email'], 'dad@home.test')

    def test_access_control_other_school(self):
        other_owner = _make_owner('intruder')
        other_school = School.objects.create(name='Other', admin=other_owner, is_active=True)
        url = reverse('admin_school_students_export_csv', args=[other_school.id])
        self.client.force_login(self.owner)
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
