"""
Tests for the homework module (CPP-74).

Covers:
  - Model behaviour (Homework, HomeworkSubmission)
  - Form validation (HomeworkForm, SubmissionForm, GradingForm)
  - Teacher views (create, list, edit, delete, publish, submissions, grade, CSV export)
  - Student views (dashboard, detail, submit)
  - Access control (role-based, class membership)
  - Management command (publish_scheduled_homework)
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

from django.core.management import call_command
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from classroom.models import (
    School, Subject, Level, Topic, ClassRoom, ClassTeacher, ClassStudent,
)
from homework.models import Homework, HomeworkQuestion, HomeworkSubmission
from homework.forms import HomeworkForm, GradingForm


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_school():
    return School.objects.create(name='Test School', slug='test-school')


def _create_user(username, role_name=None):
    user = CustomUser.objects.create_user(
        username=username,
        email=f'{username}@test.com',
        password='testpass123',
    )
    if role_name:
        role, _ = Role.objects.get_or_create(name=role_name)
        UserRole.objects.create(user=user, role=role)
    return user


def _create_classroom(school, teacher, subject=None):
    if subject is None:
        subject = Subject.objects.create(name='Maths', slug='maths')
    level = Level.objects.create(level_number=5, display_name='Year 5', subject=subject)
    topic = Topic.objects.create(subject=subject, name='Fractions', slug='fractions')
    topic.levels.add(level)
    classroom = ClassRoom.objects.create(
        name='Year 5 Maths',
        school=school,
        subject=subject,
        created_by=teacher,
    )
    classroom.levels.add(level)
    ClassTeacher.objects.create(classroom=classroom, teacher=teacher)
    return classroom, topic, level


def _create_homework(classroom, topic, teacher, **kwargs):
    defaults = {
        'title': 'Test Homework',
        'due_date': timezone.now() + timedelta(days=3),
        'status': Homework.STATUS_ACTIVE,
        'assigned_by': teacher,
        'published_at': timezone.now(),
    }
    defaults.update(kwargs)
    return Homework.objects.create(classroom=classroom, topic=topic, **defaults)


# ===========================================================================
# Model Tests
# ===========================================================================

class HomeworkModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)

    def test_str(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        self.assertIn('Test Homework', str(hw))
        self.assertIn('Year 5 Maths', str(hw))

    def test_is_overdue_false_when_future(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() + timedelta(days=2))
        self.assertFalse(hw.is_overdue)

    def test_is_overdue_true_when_past(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() - timedelta(hours=1))
        self.assertTrue(hw.is_overdue)

    def test_is_overdue_false_when_draft(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() - timedelta(hours=1),
                              status=Homework.STATUS_DRAFT)
        self.assertFalse(hw.is_overdue)

    def test_is_due_soon(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() + timedelta(hours=12))
        self.assertTrue(hw.is_due_soon)

    def test_is_due_soon_false_far_future(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() + timedelta(days=5))
        self.assertFalse(hw.is_due_soon)

    def test_can_edit_true_no_submissions(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        self.assertTrue(hw.can_edit())

    def test_can_edit_false_with_submissions(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        student = _create_user('student1', Role.STUDENT)
        HomeworkSubmission.objects.create(
            homework=hw, student=student, attempt_number=1,
        )
        self.assertFalse(hw.can_edit())

    def test_can_edit_false_when_closed(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              status=Homework.STATUS_CLOSED)
        self.assertFalse(hw.can_edit())

    def test_publish(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              status=Homework.STATUS_DRAFT, published_at=None)
        hw.publish()
        hw.refresh_from_db()
        self.assertEqual(hw.status, Homework.STATUS_ACTIVE)
        self.assertIsNotNone(hw.published_at)

    def test_soft_delete_hides_homework(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        hw.is_active = False
        hw.save()
        self.assertEqual(
            Homework.objects.filter(classroom=self.classroom, is_active=True).count(), 0
        )


class HomeworkSubmissionModelTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.student = _create_user('student1', Role.STUDENT)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)

    def test_is_late_auto_computed_on_create(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() - timedelta(hours=1))
        sub = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
        )
        self.assertTrue(sub.is_late)

    def test_not_late_when_before_due(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              due_date=timezone.now() + timedelta(days=3))
        sub = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
        )
        self.assertFalse(sub.is_late)

    def test_unique_together_constraint(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
        )
        from django.db import IntegrityError
        with self.assertRaises(IntegrityError):
            HomeworkSubmission.objects.create(
                homework=hw, student=self.student, attempt_number=1,
            )

    def test_str(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        sub = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
        )
        self.assertIn('student1', str(sub))
        self.assertIn('attempt 1', str(sub))


# ===========================================================================
# Form Tests
# ===========================================================================

class GradingFormTest(TestCase):

    def test_valid(self):
        form = GradingForm(data={'score': '85', 'max_score': '100', 'feedback': 'Good'})
        self.assertTrue(form.is_valid())

    def test_score_exceeds_max(self):
        form = GradingForm(data={'score': '110', 'max_score': '100', 'feedback': ''})
        self.assertFalse(form.is_valid())
        self.assertIn('score', form.errors)

    def test_feedback_optional(self):
        form = GradingForm(data={'score': '50', 'max_score': '100'})
        self.assertTrue(form.is_valid())


# ===========================================================================
# Teacher View Tests
# ===========================================================================

class TeacherHomeworkViewsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)
        cls.student = _create_user('student1', Role.STUDENT)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)

    # ── Create ──

    def test_create_get(self):
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Assign Homework')

    def test_create_post_publish_immediately(self):
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        resp = self.client.post(url, {
            'title': 'New HW',
            'topic': self.topic.pk,
            'description': 'Do this',
            'due_date': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'max_attempts': 0,
            'homework_type': 'note',
            'publish_option': 'publish',
        })
        self.assertEqual(resp.status_code, 302)
        hw = Homework.objects.get(title='New HW')
        self.assertEqual(hw.status, Homework.STATUS_ACTIVE)
        self.assertIsNotNone(hw.published_at)

    def test_create_post_draft(self):
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        resp = self.client.post(url, {
            'title': 'Draft HW',
            'topic': self.topic.pk,
            'description': 'Revise this',
            'due_date': (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'max_attempts': 0,
            'homework_type': 'note',
            'publish_option': 'draft',
        })
        self.assertEqual(resp.status_code, 302)
        hw = Homework.objects.get(title='Draft HW')
        self.assertEqual(hw.status, Homework.STATUS_DRAFT)

    def test_create_post_scheduled(self):
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        publish_at = timezone.now() + timedelta(days=1)
        resp = self.client.post(url, {
            'title': 'Scheduled HW',
            'topic': self.topic.pk,
            'description': 'Revise this',
            'due_date': (publish_at + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'max_attempts': 0,
            'homework_type': 'note',
            'publish_option': 'schedule',
            'scheduled_publish_at': publish_at.strftime('%Y-%m-%dT%H:%M'),
        })
        self.assertEqual(resp.status_code, 302)
        hw = Homework.objects.get(title='Scheduled HW')
        self.assertEqual(hw.status, Homework.STATUS_SCHEDULED)

    # ── List ──

    def test_class_list(self):
        _create_homework(self.classroom, self.topic, self.teacher)
        url = reverse('homework:class_list', kwargs={'class_id': self.classroom.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test Homework')

    def test_class_list_tabs(self):
        _create_homework(self.classroom, self.topic, self.teacher, status=Homework.STATUS_DRAFT, title='Draft One')
        url = reverse('homework:class_list', kwargs={'class_id': self.classroom.pk})
        resp = self.client.get(url + '?tab=drafts')
        self.assertContains(resp, 'Draft One')

    # ── Edit ──

    def test_edit_get(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher, status=Homework.STATUS_DRAFT)
        url = reverse('homework:edit', kwargs={'hw_id': hw.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_edit_blocked_with_submissions(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:edit', kwargs={'hw_id': hw.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)  # redirected with warning

    # ── Delete ──

    def test_soft_delete(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        url = reverse('homework:delete', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        hw.refresh_from_db()
        self.assertFalse(hw.is_active)

    # ── Publish ──

    def test_publish_draft(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher,
                              status=Homework.STATUS_DRAFT, published_at=None)
        url = reverse('homework:publish', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        hw.refresh_from_db()
        self.assertEqual(hw.status, Homework.STATUS_ACTIVE)

    # ── Submissions ──

    def test_submissions_list(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:submissions', kwargs={'hw_id': hw.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'student1')

    # ── Grade ──

    def test_grade_get(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        sub = HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:grade', kwargs={'hw_id': hw.pk, 'sub_id': sub.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_grade_post_save(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        sub = HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:grade', kwargs={'hw_id': hw.pk, 'sub_id': sub.pk})
        resp = self.client.post(url, {'score': '85', 'max_score': '100', 'feedback': 'Good', 'save': ''})
        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        self.assertTrue(sub.is_graded)
        self.assertFalse(sub.is_published)

    def test_grade_post_publish(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        sub = HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:grade', kwargs={'hw_id': hw.pk, 'sub_id': sub.pk})
        resp = self.client.post(url, {'score': '90', 'max_score': '100', 'feedback': '', 'publish': ''})
        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        self.assertTrue(sub.is_graded)
        self.assertTrue(sub.is_published)

    # ── Bulk Publish ──

    def test_bulk_publish(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        sub = HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
            is_graded=True, score=Decimal('80'), max_score=Decimal('100'),
        )
        url = reverse('homework:publish_all', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        sub.refresh_from_db()
        self.assertTrue(sub.is_published)

    # ── CSV Export ──

    def test_csv_export(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(homework=hw, student=self.student, attempt_number=1)
        url = reverse('homework:export_csv', kwargs={'hw_id': hw.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv')
        self.assertIn('student1', resp.content.decode())


# ===========================================================================
# Student View Tests
# ===========================================================================

class StudentHomeworkViewsTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.student = _create_user('student1', Role.STUDENT)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student)

    def test_dashboard_empty(self):
        resp = self.client.get(reverse('homework:dashboard'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'My Homework')

    def test_dashboard_shows_active_homework(self):
        _create_homework(self.classroom, self.topic, self.teacher)
        resp = self.client.get(reverse('homework:dashboard'))
        self.assertContains(resp, 'Test Homework')

    def test_dashboard_hides_draft(self):
        _create_homework(self.classroom, self.topic, self.teacher,
                         title='Draft HW', status=Homework.STATUS_DRAFT)
        resp = self.client.get(reverse('homework:dashboard'))
        self.assertNotContains(resp, 'Draft HW')

    def test_detail_page_note(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher, homework_type=Homework.TYPE_NOTE)
        resp = self.client.get(reverse('homework:detail', kwargs={'hw_id': hw.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Mark as Done')

    def test_detail_page_quiz(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher, homework_type=Homework.TYPE_QUIZ)
        resp = self.client.get(reverse('homework:detail', kwargs={'hw_id': hw.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Quiz')

    def test_submit_homework(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        url = reverse('homework:submit', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url, {'content': 'My answer'})
        self.assertEqual(resp.status_code, 302)
        sub = HomeworkSubmission.objects.get(homework=hw, student=self.student)
        self.assertEqual(sub.attempt_number, 1)
        self.assertEqual(sub.content, 'My answer')

    def test_multiple_attempts(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        url = reverse('homework:submit', kwargs={'hw_id': hw.pk})
        self.client.post(url, {'content': 'Attempt 1'})
        self.client.post(url, {'content': 'Attempt 2'})
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=hw, student=self.student).count(), 2
        )

    def test_max_attempts_enforced(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher, max_attempts=1)
        url = reverse('homework:submit', kwargs={'hw_id': hw.pk})
        self.client.post(url, {'content': 'Attempt 1'})
        resp = self.client.post(url, {'content': 'Attempt 2'})
        self.assertEqual(resp.status_code, 302)  # redirect with error
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=hw, student=self.student).count(), 1
        )

    def test_unenrolled_student_read_only(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher, homework_type=Homework.TYPE_PDF)
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1, content='My work',
        )
        cs = ClassStudent.objects.get(classroom=self.classroom, student=self.student)
        cs.is_active = False
        cs.save()
        resp = self.client.get(reverse('homework:detail', kwargs={'hw_id': hw.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'no longer enrolled')
        self.assertNotContains(resp, 'Upload &amp; Submit')

    def test_published_score_visible(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
            score=Decimal('90'), max_score=Decimal('100'),
            is_graded=True, is_published=True,
        )
        resp = self.client.get(reverse('homework:detail', kwargs={'hw_id': hw.pk}))
        self.assertContains(resp, '90')

    def test_unpublished_score_hidden(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student, attempt_number=1,
            score=Decimal('90'), max_score=Decimal('100'),
            is_graded=True, is_published=False,
        )
        resp = self.client.get(reverse('homework:detail', kwargs={'hw_id': hw.pk}))
        self.assertContains(resp, 'marks not yet published')


# ===========================================================================
# Access Control Tests
# ===========================================================================

class AccessControlTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.other_teacher = _create_user('teacher2', Role.TEACHER)
        cls.student = _create_user('student1', Role.STUDENT)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)

    def test_unauthenticated_redirects_to_login(self):
        url = reverse('homework:dashboard')
        resp = Client().get(url)
        self.assertEqual(resp.status_code, 302)
        self.assertIn('login', resp.url)

    def test_non_class_teacher_denied(self):
        client = Client()
        client.force_login(self.other_teacher)
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        resp = client.get(url)
        self.assertEqual(resp.status_code, 302)  # redirected with error

    def test_student_cannot_access_teacher_views(self):
        client = Client()
        client.force_login(self.student)
        url = reverse('homework:create', kwargs={'class_id': self.classroom.pk})
        resp = client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_non_enrolled_student_cannot_submit(self):
        hw = _create_homework(self.classroom, self.topic, self.teacher)
        client = Client()
        client.force_login(self.student)
        url = reverse('homework:submit', kwargs={'hw_id': hw.pk})
        resp = client.post(url, {'content': 'Hack attempt'})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(HomeworkSubmission.objects.count(), 0)


# ===========================================================================
# Management Command Tests
# ===========================================================================

class PublishScheduledHomeworkTest(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)

    def test_publishes_due_homework(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            status=Homework.STATUS_SCHEDULED,
            scheduled_publish_at=timezone.now() - timedelta(minutes=5),
            published_at=None,
        )
        out = StringIO()
        call_command('publish_scheduled_homework', stdout=out)
        hw.refresh_from_db()
        self.assertEqual(hw.status, Homework.STATUS_ACTIVE)
        self.assertIsNotNone(hw.published_at)
        self.assertIn('Published 1', out.getvalue())

    def test_does_not_publish_future(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            status=Homework.STATUS_SCHEDULED,
            scheduled_publish_at=timezone.now() + timedelta(hours=2),
            published_at=None,
        )
        call_command('publish_scheduled_homework', stdout=StringIO())
        hw.refresh_from_db()
        self.assertEqual(hw.status, Homework.STATUS_SCHEDULED)

    def test_does_not_publish_inactive(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            status=Homework.STATUS_SCHEDULED,
            scheduled_publish_at=timezone.now() - timedelta(minutes=5),
            published_at=None,
            is_active=False,
        )
        call_command('publish_scheduled_homework', stdout=StringIO())
        hw.refresh_from_db()
        self.assertEqual(hw.status, Homework.STATUS_SCHEDULED)

    def test_noop_message(self):
        out = StringIO()
        call_command('publish_scheduled_homework', stdout=out)
        self.assertIn('No scheduled homework', out.getvalue())


# ===========================================================================
# Homework Type Tests
# ===========================================================================

class MarkDoneViewTest(TestCase):
    """Tests for note-type homework mark-as-done."""

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.student = _create_user('student1', Role.STUDENT)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student)

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.student)

    def test_mark_done_creates_submission(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_NOTE,
        )
        url = reverse('homework:mark_done', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 302)
        sub = HomeworkSubmission.objects.get(homework=hw, student=self.student)
        self.assertTrue(sub.is_auto_completed)
        self.assertEqual(sub.attempt_number, 1)

    def test_mark_done_rejects_non_note_type(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_PDF,
        )
        url = reverse('homework:mark_done', kwargs={'hw_id': hw.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 404)

    def test_mark_done_rejects_non_enrolled(self):
        other = _create_user('other_student', Role.STUDENT)
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_NOTE,
        )
        client = Client()
        client.force_login(other)
        resp = client.post(reverse('homework:mark_done', kwargs={'hw_id': hw.pk}))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(HomeworkSubmission.objects.count(), 0)


class QuestionSnapshotTest(TestCase):
    """Tests for quiz-type homework question snapshot."""

    @classmethod
    def setUpTestData(cls):
        cls.school = _create_school()
        cls.teacher = _create_user('teacher1', Role.TEACHER)
        cls.classroom, cls.topic, cls.level = _create_classroom(cls.school, cls.teacher)

    def test_snapshot_creates_homework_questions(self):
        from maths.models import Question, Answer
        for i in range(5):
            q = Question.objects.create(
                level=self.level, topic=self.topic,
                question_text=f'Q{i}', question_type='multiple_choice',
            )
            Answer.objects.create(question=q, answer_text='A', is_correct=True)

        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_QUIZ,
        )
        hw.quiz_topics.set([self.topic])
        hw.quiz_level = self.level
        hw.num_questions = 3
        hw.save()
        hw.snapshot_questions()

        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 3)

    def test_snapshot_all_questions_when_num_is_none(self):
        from maths.models import Question, Answer
        for i in range(4):
            q = Question.objects.create(
                level=self.level, topic=self.topic,
                question_text=f'Q{i}', question_type='multiple_choice',
            )
            Answer.objects.create(question=q, answer_text='A', is_correct=True)

        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_QUIZ,
        )
        hw.quiz_topics.set([self.topic])
        hw.quiz_level = self.level
        hw.save()
        hw.snapshot_questions()

        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 4)

    def test_snapshot_skipped_for_non_quiz(self):
        hw = _create_homework(
            self.classroom, self.topic, self.teacher,
            homework_type=Homework.TYPE_NOTE,
        )
        hw.snapshot_questions()
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 0)
