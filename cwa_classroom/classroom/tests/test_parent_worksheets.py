"""Tests for ParentWorksheetView (/parent/worksheets/) — CPP-293."""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, Subject, ClassRoom, ClassStudent, ParentStudent,
)
from worksheets.models import (
    Worksheet, WorksheetAssignment, WorksheetSubmission,
)

from .test_parent_portal import ParentPortalTestBase


def _make_worksheet(school, name='Test Worksheet', level=None, created_by=None):
    return Worksheet.objects.create(
        school=school, name=name, level=level,
        original_filename='', pdf_file=None, created_by=created_by,
    )


def _make_assignment(worksheet, classroom):
    return WorksheetAssignment.objects.create(
        worksheet=worksheet, classroom=classroom,
    )


def _make_submission(assignment, student, score=0, total=5, completed=False):
    sub = WorksheetSubmission.objects.create(
        assignment=assignment, student=student,
        score=score, total_questions=total,
    )
    if completed:
        WorksheetSubmission.objects.filter(pk=sub.pk).update(
            completed_at=timezone.now(),
        )
        sub.refresh_from_db()
    return sub


class ParentWorksheetViewTest(ParentPortalTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='password1!')
        self.client.post(reverse('parent_switch_child', args=[self.student.id]))

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_requires_parent_role(self):
        self.client.login(username='student1', password='password1!')
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertNotEqual(resp.status_code, 200)

    def test_no_child_shows_empty_state(self):
        self.client.login(username='other_parent', password='password1!')
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No child selected')

    def test_no_assignments_shows_empty_state(self):
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No worksheet assignments yet')

    def test_parent_dashboard_shows_worksheet_scores(self):
        ws = _make_worksheet(self.school, 'Fractions Quiz')
        assignment = _make_assignment(ws, self.classroom)
        _make_submission(assignment, self.student, score=8, total=10, completed=True)
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Fractions Quiz')
        self.assertContains(resp, '8 / 10')
        self.assertContains(resp, '80%')
        self.assertContains(resp, 'Completed')

    def test_in_progress_shows_badge(self):
        ws = _make_worksheet(self.school, 'Algebra WS')
        assignment = _make_assignment(ws, self.classroom)
        _make_submission(assignment, self.student, score=0, total=5, completed=False)
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertContains(resp, 'In Progress')
        self.assertNotContains(resp, 'Score:')

    def test_not_started_shows_badge(self):
        ws = _make_worksheet(self.school, 'Geometry WS')
        _make_assignment(ws, self.classroom)
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertContains(resp, 'Not Started')

    def test_parent_dashboard_multi_child_scoped_correctly(self):
        """Second child in different class only sees their own assignments."""
        student2 = CustomUser.objects.create_user(
            'student2_ws', 'ws_student2@test.com', 'password1!',
            first_name='Max', last_name='Student',
        )
        student2_role, _ = Role.objects.get_or_create(
            name=Role.STUDENT, defaults={'display_name': 'Student'},
        )
        student2.roles.add(student2_role)
        SchoolStudent.objects.create(school=self.school, student=student2)
        ParentStudent.objects.create(
            parent=self.parent, student=student2,
            school=self.school, relationship='mother',
        )
        class2 = ClassRoom.objects.create(
            name='Science Year 8', school=self.school, subject=self.maths,
        )
        ClassStudent.objects.create(classroom=class2, student=student2)

        ws1 = _make_worksheet(self.school, 'Child 1 WS')
        _make_assignment(ws1, self.classroom)
        ws2 = _make_worksheet(self.school, 'Child 2 WS')
        _make_assignment(ws2, class2)

        resp = self.client.get(reverse('parent_worksheets'))
        self.assertContains(resp, 'Child 1 WS')
        self.assertNotContains(resp, 'Child 2 WS')

        self.client.post(reverse('parent_switch_child', args=[student2.id]))
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertContains(resp, 'Child 2 WS')
        self.assertNotContains(resp, 'Child 1 WS')

    def test_other_school_assignments_not_visible(self):
        """Tenant isolation: parent cannot see assignments from other schools."""
        other_school = School.objects.create(
            name='Other School', slug='other-school-ws',
            admin=CustomUser.objects.create_user('os_admin_ws', 'os_ws@t.com', 'p1!'),
        )
        other_class = ClassRoom.objects.create(
            name='Other Class', school=other_school, subject=self.maths,
        )
        ws = _make_worksheet(other_school, 'Other School WS')
        _make_assignment(ws, other_class)
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertNotContains(resp, 'Other School WS')

    def test_child_name_displayed_in_header(self):
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertContains(resp, self.student.first_name)

    def test_context_contains_child_and_school(self):
        resp = self.client.get(reverse('parent_worksheets'))
        self.assertEqual(resp.context['child'], self.student)
        self.assertEqual(resp.context['school'], self.school)
