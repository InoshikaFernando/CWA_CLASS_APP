"""Tests for ParentHomeworkView (/parent/homework/)."""
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import (
    School, SchoolStudent, Subject, ClassRoom, ClassStudent, ParentStudent,
)
from homework.models import Homework, HomeworkSubmission

from .test_parent_portal import ParentPortalTestBase


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_homework(classroom, title='HW 1', due_offset_days=7, created_by=None):
    """Create a Homework with a due date relative to now."""
    return Homework.objects.create(
        classroom=classroom,
        title=title,
        due_date=timezone.now() + timezone.timedelta(days=due_offset_days),
        num_questions=5,
        created_by=created_by,
    )


def _make_submission(homework, student, score=4, total=5, submitted_at=None):
    """Create a HomeworkSubmission."""
    sub = HomeworkSubmission(
        homework=homework,
        student=student,
        score=score,
        total_questions=total,
        attempt_number=HomeworkSubmission.get_next_attempt_number(homework, student),
    )
    sub.save()
    if submitted_at is not None:
        # Override auto_now_add by updating directly
        HomeworkSubmission.objects.filter(pk=sub.pk).update(submitted_at=submitted_at)
        sub.refresh_from_db()
    return sub


# ---------------------------------------------------------------------------
# Unit tests — ParentHomeworkView
# ---------------------------------------------------------------------------

class ParentHomeworkViewTest(ParentPortalTestBase):
    """Tests for GET /parent/homework/ using the shared parent/student fixtures."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='parent1', password='password1!')
        # Activate the child in session
        self.client.post(reverse('parent_switch_child', args=[self.student.id]))

    # --- Access control ---

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_requires_parent_role(self):
        self.client.login(username='student1', password='password1!')
        resp = self.client.get(reverse('parent_homework'))
        self.assertNotEqual(resp.status_code, 200)

    def test_unlinked_parent_cannot_see_child_homework(self):
        """An unlinked parent has no active child, so gets the 'no child' state."""
        self.client.login(username='other_parent', password='password1!')
        hw = _make_homework(self.classroom, 'Secret HW')
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Secret HW')

    # --- No homework states ---

    def test_no_homework_assigned(self):
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No homework assigned yet')

    def test_no_child_in_session(self):
        """Parent with no linked children sees the 'no child selected' state."""
        self.client.login(username='other_parent', password='password1!')
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'No child selected')

    # --- Status badges ---

    def test_pending_homework_shows_pending_badge(self):
        hw = _make_homework(self.classroom, 'Pending HW', due_offset_days=7)
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, 'Pending HW')
        self.assertContains(resp, 'Pending')

    def test_not_submitted_overdue_shows_badge(self):
        hw = _make_homework(self.classroom, 'Overdue HW', due_offset_days=-1)
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, 'Overdue HW')
        self.assertContains(resp, 'Not Submitted')

    def test_submitted_on_time_shows_submitted_badge(self):
        hw = _make_homework(self.classroom, 'Done HW', due_offset_days=5)
        submitted_time = timezone.now() - timezone.timedelta(days=1)
        _make_submission(hw, self.student, score=4, total=5, submitted_at=submitted_time)
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, 'Done HW')
        self.assertContains(resp, 'Submitted')

    def test_submitted_after_due_shows_late_badge(self):
        hw = _make_homework(self.classroom, 'Late HW', due_offset_days=-3)
        # submitted_at is *after* due_date
        submitted_time = timezone.now() - timezone.timedelta(days=1)
        _make_submission(hw, self.student, score=3, total=5, submitted_at=submitted_time)
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, 'Late HW')
        self.assertContains(resp, 'Late')

    # --- Score display ---

    def test_score_displayed_after_submission(self):
        hw = _make_homework(self.classroom, 'Scored HW', due_offset_days=5)
        submitted_time = timezone.now() - timezone.timedelta(days=1)
        _make_submission(hw, self.student, score=4, total=5, submitted_at=submitted_time)
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, '4')
        self.assertContains(resp, '5')

    def test_no_score_shown_for_pending_homework(self):
        hw = _make_homework(self.classroom, 'Unscored HW', due_offset_days=5)
        resp = self.client.get(reverse('parent_homework'))
        self.assertNotContains(resp, 'Score:')

    def test_multiple_attempts_shows_best_score(self):
        hw = _make_homework(self.classroom, 'Multi HW', due_offset_days=5)
        submitted_time = timezone.now() - timezone.timedelta(days=1)
        # First attempt: score 2
        sub1 = _make_submission(hw, self.student, score=2, total=5, submitted_at=submitted_time)
        HomeworkSubmission.objects.filter(pk=sub1.pk).update(points=2.0)
        # Second attempt: score 4 (best)
        sub2 = _make_submission(hw, self.student, score=4, total=5, submitted_at=submitted_time)
        HomeworkSubmission.objects.filter(pk=sub2.pk).update(points=4.0)
        resp = self.client.get(reverse('parent_homework'))
        # Best score (4) should be shown; best is ordered by points desc
        self.assertContains(resp, '4')
        self.assertContains(resp, '2 attempts')

    # --- Context data ---

    def test_context_contains_child(self):
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.context['child'], self.student)

    def test_context_contains_school(self):
        resp = self.client.get(reverse('parent_homework'))
        self.assertEqual(resp.context['school'], self.school)

    def test_homework_from_other_class_not_shown(self):
        """Homework for a class the child is NOT enrolled in must not appear."""
        other_class = ClassRoom.objects.create(
            name='Other Class', school=self.school, subject=self.maths,
        )
        hw = _make_homework(other_class, 'Other Class HW')
        resp = self.client.get(reverse('parent_homework'))
        self.assertNotContains(resp, 'Other Class HW')

    def test_child_name_displayed_in_header(self):
        resp = self.client.get(reverse('parent_homework'))
        self.assertContains(resp, self.student.first_name)
