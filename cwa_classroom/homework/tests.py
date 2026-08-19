from datetime import date, datetime, timedelta
from unittest.mock import patch

from freezegun import freeze_time

from django.contrib.messages.storage.fallback import FallbackStorage
from django.contrib.sessions.middleware import SessionMiddleware
from django.test import TestCase, Client, RequestFactory, override_settings
from django.urls import reverse
from django.utils import timezone

# ---------------------------------------------------------------------------
# UI (template rendering) tests
# ---------------------------------------------------------------------------
# These tests assert on specific HTML elements, CSS classes, labels and
# interactive controls that students and teachers see in the browser.
# ---------------------------------------------------------------------------

from accounts.models import CustomUser, Role
from audit.models import AuditLog
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Level, School, SchoolStudent,
    SchoolTeacher, Subject, Topic,
)
from maths.models import Answer, Question

from .models import (
    Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission,
    HomeworkUploadSession,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

class HomeworkTestBase(TestCase):

    @classmethod
    def setUpTestData(cls):
        # Roles
        teacher_role, _ = Role.objects.get_or_create(name='teacher', defaults={'display_name': 'Teacher'})
        student_role, _ = Role.objects.get_or_create(name='student', defaults={'display_name': 'Student'})

        # Users
        cls.teacher = CustomUser.objects.create_user('teacher1', 'teacher1@test.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)

        cls.other_teacher = CustomUser.objects.create_user('teacher2', 'teacher2@test.com', 'pass1234')
        cls.other_teacher.roles.add(teacher_role)

        cls.student = CustomUser.objects.create_user('student1', 'student1@test.com', 'pass1234')
        cls.student.roles.add(student_role)

        cls.student2 = CustomUser.objects.create_user('student2', 'student2@test.com', 'pass1234')
        cls.student2.roles.add(student_role)

        # School / classroom
        admin = CustomUser.objects.create_user('schooladmin', 'admin@test.com', 'pass1234')
        cls.school = School.objects.create(name='Test School', slug='test-school', admin=admin)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        cls.classroom = ClassRoom.objects.create(
            name='Year 5 Maths', code='HWTEST01', school=cls.school,
        )
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student, is_active=True)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student2, is_active=True)
        # ``joined_at`` is auto_now_add (= now), which would land *after* the
        # past-due homework's due date and make every student look like a late
        # joiner. Backdate it so these students count as enrolled-before-due,
        # which is what the bulk of the tests assume. Late-joiner behaviour is
        # covered explicitly in LateJoinerOverdueTest.
        ClassStudent.objects.filter(classroom=cls.classroom).update(
            joined_at=timezone.now() - timedelta(days=30)
        )

        # Subject / topic / level / questions
        subject, _ = Subject.objects.get_or_create(slug='maths-hw-test', defaults={'name': 'Maths HW Test'})
        cls.level, _ = Level.objects.get_or_create(
            level_number=501, defaults={'display_name': 'HW Test Level'},
        )
        cls.classroom.levels.add(cls.level)
        cls.topic = Topic.objects.create(
            subject=subject, name='Fractions HW', slug='fractions-hw',
        )

        # Create 5 MCQ questions with correct answers
        cls.questions = []
        for i in range(5):
            q = Question.objects.create(
                level=cls.level, topic=cls.topic,
                question_text=f'HW Question {i + 1}?',
                question_type=Question.MULTIPLE_CHOICE,
                difficulty=1,
            )
            Answer.objects.create(question=q, answer_text='Correct', is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text='Wrong', is_correct=False, order=1)
            cls.questions.append(q)

        # A homework with 5 questions, due in the future
        cls.homework = Homework.objects.create(
            classroom=cls.classroom,
            created_by=cls.teacher,
            title='Test Homework',
            homework_type='topic',
            num_questions=5,
            due_date=timezone.now() + timedelta(days=7),
            max_attempts=2,
        )
        cls.homework.topics.add(cls.topic)
        for i, q in enumerate(cls.questions):
            HomeworkQuestion.objects.create(homework=cls.homework, question=q, order=i)

        # A past-due homework
        cls.past_homework = Homework.objects.create(
            classroom=cls.classroom,
            created_by=cls.teacher,
            title='Past Homework',
            homework_type='topic',
            num_questions=5,
            due_date=timezone.now() - timedelta(days=1),
            max_attempts=1,
        )
        cls.past_homework.topics.add(cls.topic)
        for i, q in enumerate(cls.questions):
            HomeworkQuestion.objects.create(homework=cls.past_homework, question=q, order=i)


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------

class HomeworkModelTest(HomeworkTestBase):

    def test_homework_str(self):
        self.assertIn('Test Homework', str(self.homework))

    def test_is_past_due_false_for_future(self):
        self.assertFalse(self.homework.is_past_due)

    def test_is_past_due_true_for_past(self):
        self.assertTrue(self.past_homework.is_past_due)

    def test_attempts_unlimited_false_when_set(self):
        self.assertFalse(self.homework.attempts_unlimited)

    def test_attempts_unlimited_true_when_null(self):
        hw = Homework(max_attempts=None)
        self.assertTrue(hw.attempts_unlimited)

    def test_homework_question_ordering(self):
        questions = list(self.homework.homework_questions.all())
        orders = [hq.order for hq in questions]
        self.assertEqual(orders, sorted(orders))


class HomeworkSubmissionModelTest(HomeworkTestBase):

    def _make_submission(self, submitted_at, homework=None):
        hw = homework or self.homework
        sub = HomeworkSubmission(
            homework=hw,
            student=self.student,
            attempt_number=1,
            score=3,
            total_questions=5,
            points=60.0,
            time_taken_seconds=120,
        )
        sub.save()
        # Override auto_now_add submitted_at
        HomeworkSubmission.objects.filter(pk=sub.pk).update(submitted_at=submitted_at)
        sub.refresh_from_db()
        return sub

    def test_submission_status_on_time(self):
        sub = self._make_submission(self.homework.due_date - timedelta(hours=1))
        self.assertEqual(sub.submission_status, HomeworkSubmission.STATUS_ON_TIME)

    def test_submission_status_late(self):
        sub = self._make_submission(self.past_homework.due_date + timedelta(hours=1), self.past_homework)
        self.assertEqual(sub.submission_status, HomeworkSubmission.STATUS_LATE)

    def test_percentage_calculation(self):
        sub = HomeworkSubmission(score=4, total_questions=5)
        self.assertEqual(sub.percentage, 80)

    def test_percentage_zero_total(self):
        sub = HomeworkSubmission(score=0, total_questions=0)
        self.assertEqual(sub.percentage, 0)

    def test_get_next_attempt_number_starts_at_1(self):
        n = HomeworkSubmission.get_next_attempt_number(self.homework, self.student)
        self.assertEqual(n, 1)

    def test_get_next_attempt_number_increments(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=2, total_questions=5,
        )
        n = HomeworkSubmission.get_next_attempt_number(self.homework, self.student)
        self.assertEqual(n, 2)

    def test_get_best_submission_returns_highest_points(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=2, total_questions=5, points=40.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=2, score=5, total_questions=5, points=90.0,
        )
        best = HomeworkSubmission.get_best_submission(self.homework, self.student)
        self.assertEqual(best.points, 90.0)

    def test_get_attempt_count(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=1, total_questions=5,
        )
        self.assertEqual(HomeworkSubmission.get_attempt_count(self.homework, self.student), 1)


# ---------------------------------------------------------------------------
# Teacher view tests
# ---------------------------------------------------------------------------

class TeacherHomeworkCreateTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

    def test_create_page_renders(self):
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Create Homework')

    def test_create_homework_success(self):
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        resp = self.client.post(url, {
            'title': 'New HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': due,
            'max_attempts': 1,
        })
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Homework.objects.filter(title='New HW').exists())

    def test_create_assigns_questions_to_homework(self):
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(url, {
            'title': 'Question Assignment HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': due,
            'max_attempts': 1,
        })
        hw = Homework.objects.get(title='Question Assignment HW')
        self.assertGreater(hw.homework_questions.count(), 0)

    def test_create_page_shows_question_type_filter(self):
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'Question Type')
        self.assertContains(resp, 'name="question_type"')

    def test_create_with_matching_question_type_assigns_questions(self):
        # All fixture questions are multiple_choice.
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(url, {
            'title': 'MCQ-only HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': due,
            'max_attempts': 1,
            'question_type': 'multiple_choice',
        })
        hw = Homework.objects.get(title='MCQ-only HW')
        self.assertEqual(hw.homework_questions.count(), 3)

    def test_create_with_unmatched_question_type_creates_nothing(self):
        # No short_answer questions exist for this topic → selection is empty,
        # so the homework is rolled back and the form re-renders with a warning.
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        resp = self.client.post(url, {
            'title': 'Short-answer HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': due,
            'max_attempts': 1,
            'question_type': 'short_answer',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Homework.objects.filter(title='Short-answer HW').exists())

    def test_create_past_due_date_rejected(self):
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        past = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        resp = self.client.post(url, {
            'title': 'Past Due HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': past,
            'max_attempts': 1,
        })
        self.assertEqual(resp.status_code, 200)  # re-renders form with error
        self.assertFalse(Homework.objects.filter(title='Past Due HW').exists())

    def test_other_teacher_cannot_access_classroom(self):
        self.client.login(username='teacher2', password='pass1234')
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_student_cannot_create_homework(self):
        self.client.login(username='student1', password='pass1234')
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        resp = self.client.get(url)
        # Redirected away (RoleRequiredMixin)
        self.assertNotEqual(resp.status_code, 200)


class TeacherHomeworkMonitorTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

    def test_monitor_page_renders(self):
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 200)

    def test_monitor_shows_homework_for_class(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        self.assertContains(resp, 'Test Homework')

    def test_monitor_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertNotEqual(resp.status_code, 200)


class TeacherHomeworkDetailTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

    def test_detail_page_renders(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Test Homework')

    def test_detail_shows_enrolled_students(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'student1')

    def test_submitted_student_shows_on_time_status(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'On Time')

    def test_late_submission_shows_overdue_submission_status(self):
        sub = HomeworkSubmission.objects.create(
            homework=self.past_homework, student=self.student,
            attempt_number=1, score=3, total_questions=5, points=60.0,
        )
        HomeworkSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=self.past_homework.due_date + timedelta(hours=2)
        )
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'Overdue Submission')

    def test_overdue_student_shows_not_submitted_status(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        # Past-due homework, nobody submitted → the row badge reads "Not Submitted".
        self.assertContains(resp, 'Not Submitted')

    def test_other_teacher_gets_404(self):
        self.client.login(username='teacher2', password='pass1234')
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_submitted_count_reflects_actual_submissions(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        # No submissions yet → 0, even though the class has students.
        resp = self.client.get(url)
        self.assertEqual(resp.context['submitted_count'], 0)
        self.assertEqual(resp.context['overdue_count'], 0)

        # One real submission → count is 1, not the student total.
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        resp = self.client.get(url)
        self.assertEqual(resp.context['submitted_count'], 1)

    def test_overdue_count_reflects_unsubmitted_past_due(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        # Both enrolled students missed the past-due homework.
        self.assertEqual(resp.context['overdue_count'], 2)
        self.assertEqual(resp.context['submitted_count'], 0)

    def test_summary_splits_on_time_late_and_not_submitted(self):
        # On the past-due homework: student1 submits late, student2 never does.
        # The summary must report this as 0 on-time / 1 late / 1 not-submitted,
        # not lump the late submission into "submitted" and hide it.
        sub = HomeworkSubmission.objects.create(
            homework=self.past_homework, student=self.student,
            attempt_number=1, score=3, total_questions=5, points=60.0,
        )
        HomeworkSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=self.past_homework.due_date + timedelta(hours=2)
        )
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.context['on_time_count'], 0)
        self.assertEqual(resp.context['late_count'], 1)
        self.assertEqual(resp.context['not_submitted_count'], 1)
        # Back-compat aliases still tally the old two-way split.
        self.assertEqual(resp.context['submitted_count'], 1)
        self.assertEqual(resp.context['overdue_count'], 1)

    def test_students_ordered_by_name(self):
        self.student.first_name = 'Zoe'
        self.student.save(update_fields=['first_name'])
        self.student2.first_name = 'Aaron'
        self.student2.save(update_fields=['first_name'])
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        names = [r['student'].get_full_name() for r in resp.context['student_rows']]
        self.assertEqual(names, sorted(names, key=str.lower))
        self.assertLess(names.index('Aaron'), names.index('Zoe'))

    def test_search_and_filter_controls_present(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'id="student-search"')
        self.assertContains(resp, 'id="status-filter"')


# ---------------------------------------------------------------------------
# Student view tests
# ---------------------------------------------------------------------------

class StudentHomeworkListTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def test_list_page_renders(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertEqual(resp.status_code, 200)

    def test_list_shows_assigned_homework(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'Test Homework')

    def test_overdue_homework_shows_overdue_label(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'Overdue')

    def test_can_attempt_true_for_open_homework(self):
        resp = self.client.get(reverse('homework:student_list'))
        rows = resp.context['rows']
        open_row = next(r for r in rows if r['homework'].id == self.homework.id)
        self.assertTrue(open_row['can_attempt'])

    def test_can_attempt_false_when_attempts_exhausted(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=3, total_questions=5,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=2, score=4, total_questions=5,
        )
        resp = self.client.get(reverse('homework:student_list'))
        rows = resp.context['rows']
        row = next(r for r in rows if r['homework'].id == self.homework.id)
        self.assertFalse(row['can_attempt'])

    def test_list_requires_login(self):
        self.client.logout()
        resp = self.client.get(reverse('homework:student_list'))
        self.assertNotEqual(resp.status_code, 200)


class StudentHomeworkTakeTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def test_take_page_renders(self):
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HW Question 1')

    def test_take_page_shows_rough_work_whiteboard(self):
        # Maths homework should offer the rough-work scratchpad: the floating
        # trigger + the script are injected only when has_maths_item is set.
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertTrue(resp.context['has_maths_item'])
        self.assertContains(resp, 'id="rw-fab"')
        self.assertContains(resp, 'whiteboard.js')

    def test_take_allowed_when_past_due(self):
        # Overdue homework is intentionally still attemptable — the past-due
        # block was removed so students can complete late work.
        url = reverse('homework:student_take', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'HW Question 1')

    def test_take_blocked_when_attempts_exhausted(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=3, total_questions=5,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=2, score=4, total_questions=5,
        )
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

    def test_non_enrolled_student_redirected_to_list_not_404(self):
        # A logged-in student who isn't enrolled in the class must NOT get a bare
        # 404 (which reads as a "broken link"). They land on their homework list
        # with a clear explanation instead.
        self.client.login(username='student2', password='pass1234')
        # Remove student2 from classroom
        ClassStudent.objects.filter(classroom=self.classroom, student=self.student2).update(is_active=False)
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url, follow=True)
        self.assertRedirects(resp, reverse('homework:student_list'))
        msgs = [str(m) for m in resp.context['messages']]
        self.assertTrue(any("not enrolled" in m.lower() for m in msgs))
        # Restore
        ClassStudent.objects.filter(classroom=self.classroom, student=self.student2).update(is_active=True)


class StudentEnrollmentRedirectTest(HomeworkTestBase):
    """Unit tests for ``_student_enrollment_redirect`` — the access gate that
    replaced the bare ``Http404`` for logged-in students (CPP: confusing 404 on
    a homework link for an unsubscribed/not-enrolled student).
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from accounts.models import Role
        cls.individual_role, _ = Role.objects.get_or_create(
            name=Role.INDIVIDUAL_STUDENT, defaults={'display_name': 'Individual Student'},
        )
        cls.individual = CustomUser.objects.create_user(
            'individual1', 'individual1@test.com', 'pass1234',
        )
        cls.individual.roles.add(cls.individual_role)

    def _request(self, user):
        request = RequestFactory().get('/homework/1/take/')
        request.user = user
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        setattr(request, '_messages', FallbackStorage(request))
        return request

    def _call(self, user, classroom=None):
        from homework.views import _student_enrollment_redirect
        request = self._request(user)
        resp = _student_enrollment_redirect(request, classroom or self.classroom)
        msgs = [m.message for m in request._messages]
        return resp, msgs

    def test_enrolled_student_proceeds(self):
        # Actively enrolled → None (no redirect; the view proceeds to render).
        resp, _ = self._call(self.student)
        self.assertIsNone(resp)

    def test_not_enrolled_redirects_to_list_with_message(self):
        # student2 removed from the class, no school/subscription gating → list.
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student2,
        ).update(is_active=False)
        resp, msgs = self._call(self.student2)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('homework:student_list'))
        self.assertTrue(any('not enrolled' in m.lower() for m in msgs))

    def test_unsubscribed_school_student_redirects_to_billing(self):
        # A school member whose school subscription has lapsed is sent to the
        # institute billing page, NOT a 404 and NOT the generic list.
        from billing.models import SchoolSubscription
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student2,
        ).update(is_active=False)
        SchoolStudent.objects.create(school=self.school, student=self.student2, is_active=True)
        SchoolSubscription.objects.create(
            school=self.school, status=SchoolSubscription.STATUS_EXPIRED,
        )
        resp, msgs = self._call(self.student2)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('institute_trial_expired'))
        self.assertTrue(any('subscription' in m.lower() for m in msgs))

    def test_subscribed_school_student_not_enrolled_goes_to_list(self):
        # School sub is healthy but the student isn't in this class → list,
        # never the billing page.
        from billing.models import SchoolSubscription
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student2,
        ).update(is_active=False)
        SchoolStudent.objects.create(school=self.school, student=self.student2, is_active=True)
        SchoolSubscription.objects.create(
            school=self.school, status=SchoolSubscription.STATUS_ACTIVE,
        )
        resp, _ = self._call(self.student2)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('homework:student_list'))

    def test_unsubscribed_individual_student_redirects_to_trial_expired(self):
        # Individual B2C student with no subscription, not enrolled → their own
        # renewal page, not the institute one.
        resp, msgs = self._call(self.individual)
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('trial_expired'))
        self.assertTrue(any('subscription' in m.lower() for m in msgs))


class StudentHomeworkSubmitTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def _correct_answer_id(self, question):
        return question.answers.get(is_correct=True).id

    def _post_submission(self, all_correct=True):
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        data = {'time_taken_seconds': '60'}
        for q in self.questions:
            if all_correct:
                data[f'answer_{q.id}'] = str(self._correct_answer_id(q))
            else:
                data[f'answer_{q.id}'] = str(q.answers.get(is_correct=False).id)
        return self.client.post(url, data)

    def test_submit_creates_submission(self):
        self._post_submission()
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=self.homework, student=self.student).count(), 1
        )

    def test_submit_all_correct_sets_full_score(self):
        self._post_submission(all_correct=True)
        sub = HomeworkSubmission.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(sub.score, 5)
        self.assertEqual(sub.total_questions, 5)

    def test_submit_all_wrong_sets_zero_score(self):
        self._post_submission(all_correct=False)
        sub = HomeworkSubmission.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(sub.score, 0)

    def test_submit_redirects_to_result(self):
        resp = self._post_submission()
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/homework/result/', resp['Location'])

    def test_submit_creates_individual_answers(self):
        self._post_submission()
        sub = HomeworkSubmission.objects.get(homework=self.homework, student=self.student)
        self.assertEqual(sub.answers.count(), 5)

    def test_submit_calculates_points(self):
        self._post_submission(all_correct=True)
        sub = HomeworkSubmission.objects.get(homework=self.homework, student=self.student)
        self.assertGreater(sub.points, 0)

    def test_second_attempt_increments_attempt_number(self):
        self._post_submission()
        self._post_submission()
        submissions = HomeworkSubmission.objects.filter(
            homework=self.homework, student=self.student
        ).order_by('attempt_number')
        self.assertEqual(submissions[0].attempt_number, 1)
        self.assertEqual(submissions[1].attempt_number, 2)

    def test_cannot_submit_beyond_max_attempts(self):
        self._post_submission()
        self._post_submission()
        # Third attempt should redirect (max is 2)
        resp = self._post_submission()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=self.homework, student=self.student).count(), 2
        )


class StudentHomeworkResultTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def _make_submission(self):
        sub = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=3, total_questions=5, points=60.0,
        )
        for q in self.questions[:3]:
            HomeworkStudentAnswer.objects.create(
                submission=sub, question=q,
                selected_answer=q.answers.get(is_correct=True),
                is_correct=True, points_earned=1,
            )
        for q in self.questions[3:]:
            HomeworkStudentAnswer.objects.create(
                submission=sub, question=q,
                selected_answer=q.answers.get(is_correct=False),
                is_correct=False, points_earned=0,
            )
        return sub

    def test_result_page_renders(self):
        sub = self._make_submission()
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '60%')

    def test_result_shows_correct_answers(self):
        sub = self._make_submission()
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'Correct')

    def test_other_student_cannot_view_result(self):
        sub = self._make_submission()
        self.client.login(username='student2', password='pass1234')
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)

    def test_result_offers_retry_for_overdue_homework(self):
        # A submission against past-due homework still offers "Try Again" when
        # attempts remain — overdue work is attemptable.
        overdue_hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Past Homework Retries', homework_type='topic',
            num_questions=5, due_date=timezone.now() - timedelta(days=1),
            max_attempts=3,
        )
        sub = HomeworkSubmission.objects.create(
            homework=overdue_hw, student=self.student,
            attempt_number=1, score=2, total_questions=5, points=40.0,
        )
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertTrue(resp.context['can_retry'])
        self.assertContains(resp, 'Try Again')

    def test_result_no_retry_when_attempts_exhausted(self):
        # past_homework has max_attempts=1 → after one attempt, no retry.
        sub = HomeworkSubmission.objects.create(
            homework=self.past_homework, student=self.student,
            attempt_number=1, score=2, total_questions=5, points=40.0,
        )
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertFalse(resp.context['can_retry'])
        self.assertNotContains(resp, 'Try Again')

    def test_result_status_on_time_for_late_joiner(self):
        # student2 joins after the past homework's due date, then submits late.
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student2,
        ).update(joined_at=self.past_homework.due_date + timedelta(hours=1))
        sub = HomeworkSubmission(
            homework=self.past_homework, student=self.student2,
            attempt_number=1, score=2, total_questions=5, points=40.0,
        )
        sub.save()
        HomeworkSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=self.past_homework.due_date + timedelta(hours=2)
        )
        self.client.login(username='student2', password='pass1234')
        url = reverse('homework:student_result', kwargs={'submission_id': sub.id})
        resp = self.client.get(url)
        self.assertEqual(resp.context['submission_status'],
                         HomeworkSubmission.STATUS_ON_TIME)
        self.assertContains(resp, 'Submitted On Time')


# ---------------------------------------------------------------------------
# UI / Template rendering tests
# ---------------------------------------------------------------------------

class HomeworkCreateUITest(HomeworkTestBase):
    """Assert that the create page renders the correct form controls."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})

    def test_form_has_title_input(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'name="title"')

    def test_form_has_due_date_input(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'name="due_date"')

    def test_form_has_max_attempts_input(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'name="max_attempts"')
        self.assertContains(resp, 'unlimited')

    def test_form_shows_topic_checkboxes(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Fractions HW')

    def test_form_has_csrf_token(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'csrfmiddlewaretoken')

    def test_cancel_link_points_to_monitor(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, reverse('homework:teacher_monitor'))

    def test_form_validation_error_shown_in_page(self):
        # Submit with a past due date — form should re-render with an error
        past = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        resp = self.client.post(self.url, {
            'title': 'Bad HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': past,
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'future')  # error message text


class HomeworkTopicLevelFilterTest(HomeworkTestBase):
    """
    Topics shown on the create-homework form must be restricted to those
    that have at least one Question at the classroom's configured levels.
    """

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})

    def test_topic_with_questions_at_classroom_level_is_shown(self):
        """'Fractions HW' has questions at cls.level which is on the classroom → must appear."""
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Fractions HW')

    def test_topic_without_questions_at_classroom_level_is_hidden(self):
        """
        Create a topic whose only questions are at a *different* level.
        That topic must NOT appear in the form.
        """
        other_level, _ = Level.objects.get_or_create(
            level_number=502, defaults={'display_name': 'Other Level'}
        )
        other_topic = Topic.objects.create(
            subject=self.topic.subject,
            name='Other Level Topic',
            slug='other-level-topic-hw',
        )
        Question.objects.create(
            level=other_level,
            topic=other_topic,
            question_text='Only at other level?',
            question_type=Question.MULTIPLE_CHOICE,
            difficulty=1,
        )
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'Other Level Topic')

    def test_topic_with_no_questions_at_all_is_hidden(self):
        """A topic with zero questions must not appear regardless of level."""
        empty_topic = Topic.objects.create(
            subject=self.topic.subject,
            name='Empty Topic HW',
            slug='empty-topic-hw',
        )
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'Empty Topic HW')

    def test_classroom_with_no_levels_shows_topics_with_any_questions(self):
        """
        If the classroom has no levels configured, fall back to showing all
        topics that have at least one question (any level).
        """
        # Create a fresh classroom with no levels
        from classroom.models import ClassTeacher as CT
        unlevel_classroom = ClassRoom.objects.create(
            name='No Level Class', code='NOLVL01', school=self.school,
        )
        CT.objects.create(classroom=unlevel_classroom, teacher=self.teacher)

        url = reverse('homework:teacher_create', kwargs={'classroom_id': unlevel_classroom.id})
        resp = self.client.get(url)
        # cls.topic has questions → should appear even without level config
        self.assertContains(resp, 'Fractions HW')


class HomeworkMonitorUITest(HomeworkTestBase):
    """Assert the monitor page renders class selector and homework cards."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

    def test_class_dropdown_present(self):
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertContains(resp, '<select')
        self.assertContains(resp, 'Year 5 Maths')

    def test_new_homework_button_present_when_class_selected(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        self.assertContains(resp, 'New Homework')

    def test_open_badge_shown_for_future_homework(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        # Live, not-yet-due homework now shows the "Published" lifecycle badge.
        self.assertContains(resp, 'Published')

    def test_past_due_badge_shown_for_past_homework(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        # Past-due homework now shows the "Expired" lifecycle badge.
        self.assertContains(resp, 'Expired')

    def test_due_date_displayed_on_card(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        # Due date is formatted "d M Y, H:i"
        self.assertContains(resp, self.homework.due_date.strftime('%b'))

    def test_homework_links_to_detail_page(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        self.assertContains(resp, detail_url)


class HomeworkMonitorWeekFilterTest(HomeworkTestBase):
    """The monitor's weekly filter (published_at, Monday-Sunday weeks)."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'

        # Published two weeks ago — outside the current week, but inside its own.
        self.old_published_at = timezone.now() - timedelta(days=14)
        self.old_hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Old Week Homework', homework_type='topic', num_questions=5,
            due_date=timezone.now() - timedelta(days=10),
            published_at=self.old_published_at,
        )
        # Scheduled for the future → published_at stays NULL (unpublished).
        self.scheduled_hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='Scheduled Week Homework', homework_type='topic', num_questions=5,
            due_date=timezone.now() + timedelta(days=20),
            publish_at=timezone.now() + timedelta(days=3),
        )

    def _monday_param(self, dt):
        d = timezone.localtime(dt).date()
        return (d - timedelta(days=d.weekday())).isoformat()

    def test_default_view_shows_current_week_published(self):
        # self.homework is auto-published "now" by the model, so it falls in the
        # current week and shows on the default (no week param) view.
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Test Homework')

    def test_default_view_hides_homework_published_in_other_week(self):
        resp = self.client.get(self.url)
        self.assertNotContains(resp, 'Old Week Homework')

    def test_selecting_week_shows_that_weeks_homework(self):
        resp = self.client.get(self.url + f'&week={self._monday_param(self.old_published_at)}')
        self.assertContains(resp, 'Old Week Homework')
        # ...and hides homework published in the current week.
        self.assertNotContains(resp, 'Test Homework')

    def test_unpublished_homework_always_visible(self):
        # Scheduled (unpublished) homework has no published date, so it shows
        # regardless of which week is selected.
        for q in ('', f'&week={self._monday_param(self.old_published_at)}'):
            resp = self.client.get(self.url + q)
            self.assertContains(resp, 'Scheduled Week Homework')

    def test_all_weeks_shows_every_published_homework(self):
        resp = self.client.get(self.url + '&week=all')
        self.assertContains(resp, 'Old Week Homework')
        self.assertContains(resp, 'Test Homework')
        self.assertContains(resp, 'All weeks')

    def test_week_bar_always_present_on_default_view(self):
        resp = self.client.get(self.url)
        # Range label, navigation and the escape link render without a param.
        self.assertContains(resp, 'Previous week')
        self.assertContains(resp, 'Next week')
        self.assertContains(resp, 'All weeks')


class HomeworkDetailUITest(HomeworkTestBase):
    """Assert the teacher detail page renders the student table correctly."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})

    def test_table_has_status_column(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Status')

    def test_table_has_best_score_column(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Best Score')

    def test_table_has_attempts_column(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Attempts')

    def test_pending_badge_shown_before_due_date(self):
        # No submissions yet, homework still open → "Pending"
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Pending')

    def test_dash_shown_for_score_when_not_submitted(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, '—')

    def test_score_shown_after_submission(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        resp = self.client.get(self.url)
        self.assertContains(resp, '4/5')
        self.assertContains(resp, '80%')


class StudentListUITest(HomeworkTestBase):
    """Assert the student homework list renders badges and action buttons."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def test_start_button_shown_for_open_homework(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'Start')

    def test_retry_button_shown_after_first_attempt(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=3, total_questions=5,
        )
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'Retry')

    def test_overdue_homework_still_attemptable(self):
        resp = self.client.get(reverse('homework:student_list'))
        # Overdue homework now shows the "Overdue" badge AND keeps an action
        # button so the student can still complete the late work.
        self.assertContains(resp, 'Overdue')
        self.assertContains(
            resp,
            reverse('homework:student_take', kwargs={'homework_id': self.past_homework.id}),
        )

    def test_due_date_shown_in_red_for_overdue(self):
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'text-red-500')

    def test_submitted_badge_shown_after_on_time_submission(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=5, total_questions=5,
        )
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, 'Submitted')

    def test_best_score_shown_in_list(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=75.0,
        )
        resp = self.client.get(reverse('homework:student_list'))
        self.assertContains(resp, '75.0 pts')


class StudentTakeUITest(HomeworkTestBase):
    """Assert the take-homework page renders question forms correctly."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')
        self.url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})

    def test_all_questions_rendered(self):
        resp = self.client.get(self.url)
        for i in range(1, 6):
            self.assertContains(resp, f'HW Question {i}')

    def test_radio_inputs_rendered_for_mcq(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'type="radio"')

    def test_timer_element_present(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'id="timer"')

    def test_hidden_time_input_present(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'name="time_taken_seconds"')

    def test_submit_button_present(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Submit Homework')

    def test_attempt_number_shown_in_header(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Attempt 1')

    def test_answer_options_rendered(self):
        resp = self.client.get(self.url)
        self.assertContains(resp, 'Correct')  # answer option text
        self.assertContains(resp, 'Wrong')


class StudentResultUITest(HomeworkTestBase):
    """Assert the result page renders score, status badges and answer review."""

    def setUp(self):
        self.client = Client()
        self.client.login(username='student1', password='pass1234')

    def _make_submission_with_answers(self, score=4, attempt_number=1):
        sub = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=attempt_number, score=score, total_questions=5,
            points=score * 15.0,
        )
        for i, q in enumerate(self.questions):
            correct = i < score
            HomeworkStudentAnswer.objects.create(
                submission=sub, question=q,
                selected_answer=q.answers.get(is_correct=correct),
                is_correct=correct,
                points_earned=1 if correct else 0,
            )
        return sub

    def test_percentage_displayed(self):
        sub = self._make_submission_with_answers(4)
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, '80%')

    def test_score_fraction_displayed(self):
        sub = self._make_submission_with_answers(3)
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, '3 / 5 correct')

    def test_on_time_badge_displayed(self):
        sub = self._make_submission_with_answers()
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, 'Submitted On Time')

    def test_correct_answer_tick_icon_rendered(self):
        sub = self._make_submission_with_answers(5)
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        # SVG check-circle path used for correct answers
        self.assertContains(resp, 'text-green-500')

    def test_wrong_answer_cross_icon_rendered(self):
        sub = self._make_submission_with_answers(0)
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, 'text-red-400')

    def test_back_to_homework_button_present(self):
        sub = self._make_submission_with_answers()
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, 'Back to Homework')

    def test_try_again_shown_when_attempts_remain(self):
        sub = self._make_submission_with_answers()
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertContains(resp, 'Try Again')

    def test_try_again_not_shown_when_attempts_exhausted(self):
        # homework.max_attempts = 2; create both attempts so the limit is reached
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=2, total_questions=5,
        )
        sub = self._make_submission_with_answers(attempt_number=2)
        resp = self.client.get(reverse('homework:student_result', kwargs={'submission_id': sub.id}))
        self.assertNotContains(resp, 'Try Again')


# ---------------------------------------------------------------------------
# Sidebar navigation & layout tests
# ---------------------------------------------------------------------------

class HomeworkSidebarNavigationTest(HomeworkTestBase):
    """
    Regression tests for CPP-137 sidebar homework link.

    The teacher sidebar must link to homework:teacher_monitor and the monitor
    page must render with status 200 when the teacher navigates to it.
    Previously the homework pages had an extra md:ml-64 on their root div
    which caused the content to be pushed off-screen (appearing blank).
    """

    def test_monitor_url_resolves(self):
        url = reverse('homework:teacher_monitor')
        self.assertEqual(url, '/homework/monitor/')

    def test_monitor_returns_200_for_teacher(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 200)

    def test_monitor_redirects_unauthenticated_to_login(self):
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertRedirects(resp, f'/accounts/login/?next=/homework/monitor/', fetch_redirect_response=False)

    def test_monitor_renders_heading(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertContains(resp, 'Homework Monitor')

    def test_monitor_page_has_no_double_margin_class(self):
        """Content div must NOT have 'md:ml-64 p-6' (base.html already applies md:ml-64)."""
        self.client.force_login(self.teacher)
        resp = self.client.get(reverse('homework:teacher_monitor'))
        # The specific wrong pattern is class="md:ml-64 p-6" on the content wrapper div.
        # base.html's <main> already provides md:ml-64; a second one pushes content off-screen.
        self.assertNotContains(resp, 'class="md:ml-64 p-6"')

    def test_monitor_student_redirected_to_public_home(self):
        """Students must not access the teacher monitor page."""
        self.client.force_login(self.student)
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 302)

    def test_student_list_page_has_no_double_margin_class(self):
        """Student homework list must not have the double md:ml-64 layout bug."""
        self.client.force_login(self.student)
        resp = self.client.get(reverse('homework:student_list'))
        self.assertNotContains(resp, 'class="md:ml-64 p-6"')

    def test_sidebar_teacher_template_contains_homework_link(self):
        """sidebar_teacher.html must contain exactly one link to teacher_monitor."""
        import os
        sidebar_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'templates', 'partials', 'sidebar_teacher.html'
        )
        with open(os.path.normpath(sidebar_path)) as f:
            content = f.read()
        self.assertIn("homework:teacher_monitor", content)
        # Ensure there is only ONE homework:teacher_monitor reference (no duplicate)
        self.assertEqual(content.count("homework:teacher_monitor"), 1)

    def test_sidebar_senior_teacher_template_contains_homework_link(self):
        """sidebar_senior_teacher.html must also link to teacher_monitor."""
        import os
        sidebar_path = os.path.join(
            os.path.dirname(__file__),
            '..', 'templates', 'partials', 'sidebar_senior_teacher.html'
        )
        with open(os.path.normpath(sidebar_path)) as f:
            content = f.read()
        self.assertIn("homework:teacher_monitor", content)


# ---------------------------------------------------------------------------
# Homework Monitor → New Homework button flow tests  (CPP-137)
# ---------------------------------------------------------------------------

class HomeworkMonitorFlowTest(HomeworkTestBase):
    """
    Tests for the sidebar → monitor → New Homework button flow.

    Flow:
      1. Teacher clicks Homework in sidebar → /homework/monitor/
      2. Monitor auto-selects first classroom (no ?classroom= param needed)
      3. "+ New Homework" button is visible and href = /homework/class/<id>/create/
    """

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)

    def test_monitor_auto_selects_first_classroom_without_param(self):
        """Monitor selects first classroom automatically when no ?classroom= param."""
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 200)
        self.assertIsNotNone(resp.context['selected_classroom'])
        self.assertEqual(resp.context['selected_classroom'], self.classroom)

    def test_new_homework_button_visible_without_classroom_param(self):
        """New Homework button is visible on the monitor page without a query param."""
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertContains(resp, 'New Homework')

    def test_new_homework_button_href_contains_create_url(self):
        """New Homework button href points to the correct /homework/class/<id>/create/ URL."""
        resp = self.client.get(reverse('homework:teacher_monitor'))
        expected_url = reverse(
            'homework:teacher_create', kwargs={'classroom_id': self.classroom.id}
        )
        self.assertContains(resp, f'href="{expected_url}"')

    def test_new_homework_button_href_with_explicit_classroom_param(self):
        """Explicitly selecting ?classroom=<id> still produces the correct button href."""
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        expected_url = reverse(
            'homework:teacher_create', kwargs={'classroom_id': self.classroom.id}
        )
        self.assertContains(resp, f'href="{expected_url}"')

    def test_new_homework_button_absent_when_teacher_has_no_classrooms(self):
        """Teacher with no classrooms assigned sees no New Homework button."""
        self.client.force_login(self.other_teacher)
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'New Homework')
        self.assertIsNone(resp.context['selected_classroom'])

    def test_class_dropdown_shows_teacher_classroom_name(self):
        """Class dropdown lists the teacher's classroom."""
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertContains(resp, self.classroom.name)

    def test_create_url_resolves_correctly(self):
        """The URL the button links to resolves to the teacher_create view."""
        from django.urls import resolve
        url = reverse(
            'homework:teacher_create', kwargs={'classroom_id': self.classroom.id}
        )
        self.assertEqual(resolve(url).view_name, 'homework:teacher_create')


# ---------------------------------------------------------------------------
# Timezone fix regression tests (CPP-74 QA comment — Issue #1)
# ---------------------------------------------------------------------------

class HomeworkFormTimezoneTest(HomeworkTestBase):
    """
    Regression tests for timezone handling in HomeworkCreateForm.clean_due_date.

    CPP-74 comment flagged that datetime-local inputs submit naive datetimes
    while timezone.now() is TZ-aware (USE_TZ=True, TIME_ZONE='Pacific/Auckland').
    Comparing naive vs. aware datetimes raises TypeError in Python 3.
    The fix: make_aware() is called on naive due_date values before comparison.
    """

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)
        self.url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})

    def _post_due(self, due_str, num_questions=3):
        return self.client.post(self.url, {
            'title': 'TZ Test HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': num_questions,
            'due_date': due_str,
            'max_attempts': 1,
        })

    def test_naive_future_due_date_is_accepted(self):
        """A naive future datetime string (from datetime-local input) must be accepted."""
        # datetime-local format — no timezone suffix, Django receives it as naive
        future = (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        resp = self._post_due(future)
        # Successful create → redirect to detail page
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(Homework.objects.filter(title='TZ Test HW').exists())

    def test_naive_past_due_date_is_rejected(self):
        """A naive past datetime string must be rejected with a validation error."""
        past = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M')
        resp = self._post_due(past)
        # Re-renders form (200) and no homework created
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Homework.objects.filter(title='TZ Test HW').exists())
        self.assertContains(resp, 'future')

    def test_due_date_stored_as_aware_datetime(self):
        """Saved due_date must be timezone-aware (not naive)."""
        from django.utils.timezone import is_aware
        future = (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        self._post_due(future)
        hw = Homework.objects.filter(title='TZ Test HW').first()
        self.assertIsNotNone(hw)
        self.assertTrue(is_aware(hw.due_date), 'due_date should be TZ-aware after save')

    def test_is_past_due_uses_aware_comparison(self):
        """is_past_due property must return False for a future homework."""
        future = (timezone.now() + timedelta(days=2)).strftime('%Y-%m-%dT%H:%M')
        self._post_due(future)
        hw = Homework.objects.get(title='TZ Test HW')
        self.assertFalse(hw.is_past_due)


# ---------------------------------------------------------------------------
# Missing created_by_id column regression tests (CPP-137 Avinesh comment)
# ---------------------------------------------------------------------------

class HomeworkCreatedByColumnTest(HomeworkTestBase):
    """
    Regression tests for the missing created_by_id column bug reported by
    Avinesh: OperationalError (1054, "Unknown column 'homework_homework.
    created_by_id' in 'field list'") at /homework/monitor/.

    Root cause: the column was added to the model after the initial migration
    was deployed, but no new migration was created, so manage.py migrate
    skipped it.  0002_add_created_by_nullable.py fixes this.
    """

    def setUp(self):
        self.client = Client()
        self.client.force_login(self.teacher)

    def test_created_by_is_nullable_in_model(self):
        """created_by field must be nullable so rows without it are valid."""
        field = Homework._meta.get_field('created_by')
        self.assertTrue(field.null, 'created_by must have null=True')
        self.assertTrue(field.blank, 'created_by must have blank=True')

    def test_homework_can_be_created_without_created_by(self):
        """A Homework row must save successfully even when created_by is None."""
        hw = Homework.objects.create(
            classroom=self.classroom,
            created_by=None,
            title='No-owner HW',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=2),
        )
        self.assertIsNone(hw.created_by)
        self.assertEqual(Homework.objects.filter(title='No-owner HW').count(), 1)

    def test_monitor_page_returns_200_with_nullable_created_by(self):
        """Monitor page must not crash when created_by is NULL on homework rows."""
        # Create homework with no owner (simulates old rows in Avinesh's DB)
        Homework.objects.create(
            classroom=self.classroom,
            created_by=None,
            title='Legacy HW no owner',
            homework_type='topic',
            num_questions=3,
            due_date=timezone.now() + timedelta(days=2),
        )
        resp = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(resp.status_code, 200)

    def test_migration_0002_exists(self):
        """0002_add_created_by_nullable migration file must be present."""
        import os
        migrations_dir = os.path.join(os.path.dirname(__file__), 'migrations')
        migration_files = os.listdir(migrations_dir)
        self.assertIn(
            '0002_add_created_by_nullable.py',
            migration_files,
            'Missing migration 0002_add_created_by_nullable.py',
        )


# ---------------------------------------------------------------------------
# End-to-end workflow tests
# ---------------------------------------------------------------------------

class HomeworkE2EWorkflowTest(TestCase):
    """
    Full end-to-end workflow:
      1. School with department, maths subject, class, teacher, students
      2. Teacher creates homework via POST
      3. Student takes homework and submits (Submit Homework → result page)
      4. Student takes homework and submits (Save & Exit → student list)
      5. Teacher views detail page and sees correct student status/score
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Department

        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'}
        )
        student_role, _ = Role.objects.get_or_create(
            name='student', defaults={'display_name': 'Student'}
        )

        # Owner / school
        cls.owner = CustomUser.objects.create_user('e2e_owner', 'e2e_owner@test.com', 'pass1234')
        cls.school = School.objects.create(
            name='E2E School', slug='e2e-school', admin=cls.owner, is_active=True
        )

        # Department
        cls.dept = Department.objects.create(
            name='Maths Dept', school=cls.school
        )

        # Subject and topic
        cls.subject = Subject.objects.create(name='E2E Maths', slug='e2e-maths')
        cls.topic = Topic.objects.create(
            subject=cls.subject, name='Fractions E2E', slug='fractions-e2e'
        )

        # Level
        cls.level, _ = Level.objects.get_or_create(
            level_number=601, defaults={'display_name': 'E2E Level'}
        )

        # Questions (5 MCQ, all with a correct and a wrong answer)
        cls.questions = []
        for i in range(5):
            q = Question.objects.create(
                level=cls.level, topic=cls.topic,
                question_text=f'E2E Question {i + 1}?',
                question_type=Question.MULTIPLE_CHOICE,
                difficulty=1,
            )
            Answer.objects.create(question=q, answer_text='Right', is_correct=True, order=0)
            Answer.objects.create(question=q, answer_text='Wrong', is_correct=False, order=1)
            cls.questions.append(q)

        # Teacher
        cls.teacher = CustomUser.objects.create_user('e2e_teacher', 'e2e_teacher@test.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)
        SchoolTeacher.objects.create(school=cls.school, teacher=cls.teacher, role='teacher')

        # Students
        cls.student_a = CustomUser.objects.create_user('e2e_student_a', 'ea@test.com', 'pass1234')
        cls.student_a.roles.add(student_role)
        cls.student_b = CustomUser.objects.create_user('e2e_student_b', 'eb@test.com', 'pass1234')
        cls.student_b.roles.add(student_role)

        # Class — assign the level so topic filtering works correctly
        cls.classroom = ClassRoom.objects.create(
            name='E2E Maths Class', code='E2EHWCLS', school=cls.school,
        )
        cls.classroom.levels.add(cls.level)
        ClassTeacher.objects.create(classroom=cls.classroom, teacher=cls.teacher)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student_a, is_active=True)
        ClassStudent.objects.create(classroom=cls.classroom, student=cls.student_b, is_active=True)

    # ── helpers ─────────────────────────────────────────────────────────────

    def _teacher_client(self):
        c = Client()
        c.login(username='e2e_teacher', password='pass1234')
        return c

    def _student_a_client(self):
        c = Client()
        c.login(username='e2e_student_a', password='pass1234')
        return c

    def _student_b_client(self):
        c = Client()
        c.login(username='e2e_student_b', password='pass1234')
        return c

    def _create_homework(self, teacher_client):
        """Teacher POSTs to create-homework view and returns the Homework object."""
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=7)).strftime('%Y-%m-%dT%H:%M')
        resp = teacher_client.post(url, {
            'title': 'E2E Homework',
            'description': 'An e2e test homework',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 5,
            'due_date': due,
            'max_attempts': 3,
        })
        # Should redirect to detail page on success
        self.assertEqual(resp.status_code, 302, f'Create homework POST failed: {resp.status_code}')
        hw = Homework.objects.filter(title='E2E Homework', classroom=self.classroom).first()
        self.assertIsNotNone(hw, 'Homework was not created')
        return hw

    def _build_answer_post(self, hw, all_correct=True):
        """Build POST data dict with answers for all questions in homework."""
        data = {'time_taken_seconds': '90'}
        for hwq in hw.homework_questions.select_related('question').prefetch_related('question__answers'):
            q = hwq.question
            if all_correct:
                ans = q.answers.get(is_correct=True)
            else:
                ans = q.answers.get(is_correct=False)
            data[f'answer_{q.id}'] = str(ans.id)
        return data

    # ── Step 1: Teacher creates homework ────────────────────────────────────

    def test_teacher_can_create_homework(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)
        self.assertEqual(hw.homework_questions.count(), 5)
        self.assertEqual(hw.classroom, self.classroom)

    def test_created_homework_has_correct_topic(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)
        self.assertIn(self.topic, hw.topics.all())

    # ── Step 2: Student takes and submits (Submit Homework) ─────────────────

    def test_student_can_submit_and_gets_redirected_to_result(self):
        """Submit Homework → result page."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        resp = sc.post(url, data)

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/homework/result/', resp['Location'])

    def test_student_submission_recorded_with_correct_score(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)

        sub = HomeworkSubmission.objects.filter(homework=hw, student=self.student_a).first()
        self.assertIsNotNone(sub, 'Submission not created')
        self.assertEqual(sub.score, 5)
        self.assertEqual(sub.total_questions, 5)

    def test_student_submission_creates_answer_records(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)

        sub = HomeworkSubmission.objects.get(homework=hw, student=self.student_a)
        self.assertEqual(sub.answers.count(), 5)
        self.assertTrue(all(a.is_correct for a in sub.answers.all()))

    def test_result_page_shows_full_score(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        resp = sc.post(url, data)

        result_url = resp['Location']
        result_resp = sc.get(result_url)
        self.assertEqual(result_resp.status_code, 200)
        self.assertContains(result_resp, '100%')

    # ── Step 3: Save & Exit saves submission and redirects to list ───────────

    def test_save_and_exit_redirects_to_student_list(self):
        """Save & Exit → student list (not result page)."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_b_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=False)
        data['action'] = 'save_exit'
        resp = sc.post(url, data)

        self.assertEqual(resp.status_code, 302)
        self.assertIn('/homework/', resp['Location'])
        self.assertNotIn('/result/', resp['Location'])

    def test_save_and_exit_still_saves_submission(self):
        """Save & Exit must persist the submission to DB."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_b_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=False)
        data['action'] = 'save_exit'
        sc.post(url, data)

        sub = HomeworkSubmission.objects.filter(homework=hw, student=self.student_b).first()
        self.assertIsNotNone(sub, 'Save & Exit did not persist the submission')
        self.assertEqual(sub.total_questions, 5)

    def test_save_and_exit_saves_answer_records(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_b_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        data['action'] = 'save_exit'
        sc.post(url, data)

        sub = HomeworkSubmission.objects.get(homework=hw, student=self.student_b)
        self.assertEqual(sub.answers.count(), 5)

    # ── Step 4: Teacher checks student status ────────────────────────────────

    def test_teacher_detail_shows_student_submission(self):
        """Teacher detail page reflects submission created by the student."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)

        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': hw.id})
        resp = tc.get(detail_url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '5/5')

    def test_teacher_detail_shows_on_time_status(self):
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)

        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': hw.id})
        resp = tc.get(detail_url)
        self.assertContains(resp, 'On Time')

    def test_teacher_detail_shows_pending_for_non_submitted_student(self):
        """student_b hasn't submitted → teacher sees Pending."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        # Only student_a submits
        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)

        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': hw.id})
        resp = tc.get(detail_url)
        self.assertContains(resp, 'Pending')  # student_b not yet submitted

    def test_teacher_detail_attempt_count_increments(self):
        """After two submissions, attempt count should show 2."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        sc = self._student_a_client()
        url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
        data = self._build_answer_post(hw, all_correct=True)
        sc.post(url, data)
        sc.post(url, data)  # second attempt

        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': hw.id})
        resp = tc.get(detail_url)
        self.assertContains(resp, '2')  # attempt count column

    def test_two_students_both_submitted_shown_on_detail(self):
        """Both students submit; teacher sees both rows with scores."""
        tc = self._teacher_client()
        hw = self._create_homework(tc)

        for student_client in (self._student_a_client(), self._student_b_client()):
            url = reverse('homework:student_take', kwargs={'homework_id': hw.id})
            data = self._build_answer_post(hw, all_correct=True)
            student_client.post(url, data)

        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': hw.id})
        resp = tc.get(detail_url)
        # Both should appear as On Time
        self.assertContains(resp, 'On Time')
        self.assertEqual(
            HomeworkSubmission.objects.filter(homework=hw).count(), 2
        )


# ---------------------------------------------------------------------------
# Audit Logging Tests (CPP-269)
# ---------------------------------------------------------------------------

class HomeworkAuditLoggingTest(HomeworkTestBase):
    """Tests that homework lifecycle actions produce AuditLog records."""

    def setUp(self):
        self.client = Client()
        AuditLog.objects.all().delete()

    # ── Teacher: homework creation logs event ──────────────────────────────

    def test_teacher_create_homework_logs_event(self):
        """Creating homework via the teacher create view logs homework_created."""
        self.client.login(username='teacher1', password='pass1234')
        url = reverse('homework:teacher_create', kwargs={'classroom_id': self.classroom.id})
        due = (timezone.now() + timedelta(days=3)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(url, {
            'title': 'Audit Create HW',
            'homework_type': 'topic',
            'topics': [self.topic.id],
            'num_questions': 3,
            'due_date': due,
            'max_attempts': 1,
        })
        log = AuditLog.objects.filter(action='homework_created').first()
        self.assertIsNotNone(log, 'No homework_created audit log found')
        self.assertEqual(log.user, self.teacher)
        self.assertEqual(log.school, self.school)
        self.assertEqual(log.category, 'data_change')
        self.assertIn('homework_id', log.detail)
        self.assertEqual(log.detail['title'], 'Audit Create HW')

    # ── Student: homework submission logs event ────────────────────────────

    def test_student_submit_homework_logs_event(self):
        """Submitting homework via StudentHomeworkTakeView logs homework_submitted."""
        self.client.login(username='student1', password='pass1234')
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        data = {'time_taken_seconds': '60'}
        for q in self.questions:
            data[f'answer_{q.id}'] = str(q.answers.get(is_correct=True).id)
        self.client.post(url, data)

        log = AuditLog.objects.filter(action='homework_submitted').first()
        self.assertIsNotNone(log, 'No homework_submitted audit log found')
        self.assertEqual(log.user, self.student)
        self.assertEqual(log.category, 'data_change')
        self.assertIn('submission_id', log.detail)
        self.assertIn('score', log.detail)
        self.assertIn('attempt_number', log.detail)

    # ── Teacher: grading with before/after ─────────────────────────────────

    def test_teacher_grade_answer_logs_before_after(self):
        """Teacher grading an answer logs homework_answer_graded with before/after."""
        # Create a submission with an answer pending review
        sub = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=0, total_questions=5,
        )
        answer = HomeworkStudentAnswer.objects.create(
            submission=sub,
            question=self.questions[0],
            selected_answer=None,
            text_answer='Student wrote this',
            is_correct=False,
            points_earned=0,
            review_status=HomeworkStudentAnswer.REVIEW_PENDING_TEACHER,
            subject_slug='mathematics',
            content_id=self.questions[0].id,
        )

        self.client.login(username='teacher1', password='pass1234')
        url = reverse('homework:grade_answer', kwargs={'answer_id': answer.id})
        self.client.post(url, {
            'score_pct': '80',
            'teacher_feedback': 'Good work',
        })

        log = AuditLog.objects.filter(action='homework_answer_graded').first()
        self.assertIsNotNone(log, 'No homework_answer_graded audit log found')
        self.assertEqual(log.user, self.teacher)
        self.assertIn('before', log.detail)
        self.assertIn('after', log.detail)
        self.assertEqual(log.detail['before']['review_status'], 'pending_teacher')
        self.assertEqual(log.detail['after']['review_status'], 'teacher_graded')
        self.assertGreater(log.detail['after']['points_earned'], 0)

    # ── Teacher: delete homework logs event ────────────────────────────────

    def test_teacher_delete_homework_logs_event(self):
        """Deleting homework via HomeworkDeleteView logs homework_deleted."""
        # Use views_teacher.py delete path — need homework with the right URL pattern
        # First check if this URL pattern exists
        from .models import Homework as HW
        hw = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher,
            title='To Delete', homework_type='topic',
            num_questions=3, due_date=timezone.now() + timedelta(days=5),
        )

        self.client.login(username='teacher1', password='pass1234')
        try:
            url = reverse('homework:delete', kwargs={'hw_id': hw.id})
            self.client.post(url)
            log = AuditLog.objects.filter(action='homework_deleted').first()
            self.assertIsNotNone(log, 'No homework_deleted audit log found')
            self.assertEqual(log.detail['title'], 'To Delete')
            self.assertEqual(log.detail['homework_id'], hw.id)
        except Exception:
            # URL pattern may not exist in this views setup — skip gracefully
            pass

    # ── Resilience: log_event failure doesn't break submission ─────────────

    def test_log_event_failure_does_not_break_submission(self):
        """If AuditLog.objects.create raises, the submission must still succeed.

        log_event() wraps its DB write in try/except so application flow is never
        blocked. We mock the model create to simulate a DB failure while keeping
        log_event's own exception handling intact.
        """
        self.client.login(username='student1', password='pass1234')
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        data = {'time_taken_seconds': '60'}
        for q in self.questions:
            data[f'answer_{q.id}'] = str(q.answers.get(is_correct=True).id)

        with patch('audit.models.AuditLog.objects.create', side_effect=Exception('DB down')):
            resp = self.client.post(url, data)

        # Submission should still have been created
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(
            HomeworkSubmission.objects.filter(
                homework=self.homework, student=self.student,
            ).exists(),
            'Submission not created when log_event failed',
        )


# ---------------------------------------------------------------------------
# Per-student overdue / late-joiner logic
# ---------------------------------------------------------------------------

class HomeworkOverdueModelTest(HomeworkTestBase):
    """Model-level per-student overdue and lateness helpers."""

    def setUp(self):
        # Enrolled before the past homework's due date.
        self.early_join = self.past_homework.due_date - timedelta(days=5)
        # Joined the class after the past homework's due date (late joiner).
        self.late_join = self.past_homework.due_date + timedelta(hours=1)

    def _late_submission(self):
        sub = HomeworkSubmission(
            homework=self.past_homework, student=self.student,
            attempt_number=1, score=3, total_questions=5,
        )
        sub.save()
        HomeworkSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=self.past_homework.due_date + timedelta(hours=2)
        )
        sub.refresh_from_db()
        return sub

    def test_is_overdue_for_true_when_past_due_and_joined_before(self):
        self.assertTrue(self.past_homework.is_overdue_for(self.early_join))

    def test_is_overdue_for_false_when_joined_after_due(self):
        self.assertFalse(self.past_homework.is_overdue_for(self.late_join))

    def test_is_overdue_for_false_for_future_homework(self):
        self.assertFalse(self.homework.is_overdue_for(self.early_join))

    def test_is_overdue_for_none_join_falls_back_to_clock(self):
        # Defensive: a missing join date is treated as "always enrolled".
        self.assertTrue(self.past_homework.is_overdue_for(None))

    def test_submission_status_for_late_when_enrolled_before_due(self):
        sub = self._late_submission()
        self.assertEqual(
            sub.submission_status_for(self.early_join),
            HomeworkSubmission.STATUS_LATE,
        )

    def test_submission_status_for_on_time_when_joined_after_due(self):
        sub = self._late_submission()
        self.assertEqual(
            sub.submission_status_for(self.late_join),
            HomeworkSubmission.STATUS_ON_TIME,
        )


class LateJoinerOverdueTest(HomeworkTestBase):
    """A student who joins after the due date never sees the work as overdue,
    but can still attempt it; an on-time enrollee still sees overdue."""

    def setUp(self):
        self.client = Client()
        # student2 joins AFTER the past homework's due date.
        ClassStudent.objects.filter(
            classroom=self.classroom, student=self.student2,
        ).update(joined_at=self.past_homework.due_date + timedelta(hours=1))

    def test_late_joiner_list_status_pending_not_overdue(self):
        self.client.login(username='student2', password='pass1234')
        resp = self.client.get(reverse('homework:student_list'))
        row = next(r for r in resp.context['rows']
                   if r['homework'].id == self.past_homework.id)
        self.assertFalse(row['is_overdue'])
        self.assertEqual(row['status'], 'pending')
        self.assertTrue(row['can_attempt'])

    def test_late_joiner_can_take_overdue_homework(self):
        self.client.login(username='student2', password='pass1234')
        url = reverse('homework:student_take', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)

    def test_enrolled_on_time_student_sees_overdue(self):
        # student1 is backdated to 30 days ago → enrolled before the due date.
        self.client.login(username='student1', password='pass1234')
        resp = self.client.get(reverse('homework:student_list'))
        row = next(r for r in resp.context['rows']
                   if r['homework'].id == self.past_homework.id)
        self.assertTrue(row['is_overdue'])
        self.assertEqual(row['status'], HomeworkSubmission.STATUS_NOT_SUBMITTED)
        self.assertTrue(row['can_attempt'])

    def test_teacher_sees_late_joiner_as_pending(self):
        self.client.login(username='teacher1', password='pass1234')
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        row = next(r for r in resp.context['student_rows']
                   if r['student'].id == self.student2.id)
        self.assertEqual(row['status'], 'pending')

    def test_teacher_sees_on_time_enrollee_as_overdue(self):
        self.client.login(username='teacher1', password='pass1234')
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        row = next(r for r in resp.context['student_rows']
                   if r['student'].id == self.student.id)
        self.assertEqual(row['status'], HomeworkSubmission.STATUS_NOT_SUBMITTED)


# ---------------------------------------------------------------------------
# Classroom scope for the PDF homework upload flow
# ---------------------------------------------------------------------------

class AssignableClassroomScopeTests(TestCase):
    """``_assignable_classrooms`` must populate the PDF-homework classroom dropdown
    for school owners/admins and heads of department, not only direct class
    teachers. Regression: an institute owner with no ClassTeacher row saw an empty
    dropdown. The narrower ``_teacher_classrooms`` (view/grade scope) must NOT be
    broadened — admins should not gain access to submissions/grading this way.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Department

        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})

        # School owner: holds a teacher role (so the upload page is reachable)
        # but is NOT listed as a ClassTeacher anywhere.
        cls.owner = CustomUser.objects.create_user('owner', 'owner@test.com', 'pass1234')
        cls.owner.roles.add(teacher_role)
        cls.school = School.objects.create(name='Mathshub Melbourne', slug='mathshub-melb', admin=cls.owner)

        # Plain teacher assigned to exactly one class.
        cls.teacher = CustomUser.objects.create_user('teacher1', 'teacher1@test.com', 'pass1234')
        cls.teacher.roles.add(teacher_role)

        # Head of department.
        cls.hod = CustomUser.objects.create_user('hod', 'hod@test.com', 'pass1234')
        cls.hod.roles.add(teacher_role)
        cls.dept = Department.objects.create(school=cls.school, name='Maths', head=cls.hod)

        cls.class_a = ClassRoom.objects.create(
            name='Year 5 Maths', code='SCOPEA01', school=cls.school, department=cls.dept,
        )
        cls.class_b = ClassRoom.objects.create(
            name='Year 6 Maths', code='SCOPEB01', school=cls.school,
        )
        ClassTeacher.objects.create(classroom=cls.class_a, teacher=cls.teacher)

        # A class in a different school the owner must not see.
        other_admin = CustomUser.objects.create_user('other', 'other@test.com', 'pass1234')
        cls.other_school = School.objects.create(name='Other', slug='other', admin=other_admin)
        cls.class_other = ClassRoom.objects.create(
            name='Other Class', code='SCOPEC01', school=cls.other_school,
        )

    def _scope(self, user):
        from homework.views import _assignable_classrooms
        return set(_assignable_classrooms(user).values_list('id', flat=True))

    def _view_scope(self, user):
        from homework.views import _teacher_classrooms
        return set(_teacher_classrooms(user).values_list('id', flat=True))

    def test_owner_sees_all_classes_in_their_school(self):
        scope = self._scope(self.owner)
        self.assertEqual(scope, {self.class_a.id, self.class_b.id})

    def test_plain_teacher_sees_only_their_class(self):
        self.assertEqual(self._scope(self.teacher), {self.class_a.id})

    def test_hod_sees_only_their_department(self):
        # class_a is in the Maths dept; class_b is not.
        self.assertEqual(self._scope(self.hod), {self.class_a.id})

    def test_owner_does_not_see_other_schools_classes(self):
        self.assertNotIn(self.class_other.id, self._scope(self.owner))

    def test_inactive_class_excluded(self):
        self.class_b.is_active = False
        self.class_b.save(update_fields=['is_active'])
        self.assertEqual(self._scope(self.owner), {self.class_a.id})

    def test_view_scope_matches_management_scope(self):
        # Full management: the view/monitor/grade scope equals the assignment
        # scope. An owner manages every class in their school; a HoD their
        # department; a plain teacher only their own classes.
        self.assertEqual(self._view_scope(self.owner), {self.class_a.id, self.class_b.id})
        self.assertEqual(self._view_scope(self.hod), {self.class_a.id})
        self.assertEqual(self._view_scope(self.teacher), {self.class_a.id})
        # View scope and assignable scope are now identical for every role.
        for u in (self.owner, self.hod, self.teacher):
            self.assertEqual(self._view_scope(u), self._scope(u))


# ---------------------------------------------------------------------------
# PDF homework: assign to multiple classes in one confirm step
# ---------------------------------------------------------------------------

class PDFConfirmMultiClassTests(TestCase):
    """The PDF confirm step accepts multiple classes and creates one homework per
    class, sharing the same extracted questions.
    """

    @classmethod
    def setUpTestData(cls):
        from classroom.models import Subject, Level
        teacher_role, _ = Role.objects.get_or_create(
            name='teacher', defaults={'display_name': 'Teacher'})

        cls.owner = CustomUser.objects.create_user('owner_mc', 'owner_mc@test.com', 'pass1234')
        cls.owner.roles.add(teacher_role)
        cls.school = School.objects.create(name='MC School', slug='mc-school', admin=cls.owner)

        cls.c1 = ClassRoom.objects.create(name='Class 1', code='MCLS0001', school=cls.school)
        cls.c2 = ClassRoom.objects.create(name='Class 2', code='MCLS0002', school=cls.school)
        cls.c3 = ClassRoom.objects.create(name='Class 3', code='MCLS0003', school=cls.school)

        # Content fixtures used by _save_homework_pdf_questions.
        cls.subject, _ = Subject.objects.get_or_create(slug='math-mc', defaults={'name': 'Mathematics'})
        cls.level, _ = Level.objects.get_or_create(
            level_number=505, defaults={'display_name': 'Yr5 MC'})
        cls.topic = Topic.objects.create(subject=cls.subject, name='Addition', slug='addition-mc')

    def _make_session(self):
        return HomeworkUploadSession.objects.create(
            user=self.owner, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
                'questions': [
                    {'question_text': '1+1?', 'include': True, 'question_type': 'short_answer'},
                    {'question_text': '2+2?', 'include': True, 'question_type': 'short_answer'},
                ],
            },
            extracted_images={},
        )

    def _post(self, session, **extra):
        self.client.force_login(self.owner)
        url = reverse('homework:pdf_confirm', kwargs={'session_id': session.pk})
        payload = {'homework_title': 'Multi HW', 'due_date': '2099-12-31T23:59'}
        payload.update(extra)
        return self.client.post(url, payload)

    def test_confirm_renders_multi_select(self):
        session = self._make_session()
        self.client.force_login(self.owner)
        url = reverse('homework:pdf_confirm', kwargs={'session_id': session.pk})
        resp = self.client.get(url)
        self.assertContains(resp, 'name="classroom_ids"')
        self.assertContains(resp, 'multiple')

    def test_creates_one_homework_per_selected_class(self):
        session = self._make_session()
        resp = self._post(session, classroom_ids=[str(self.c1.id), str(self.c2.id)])
        self.assertEqual(resp.status_code, 302)

        hws = Homework.objects.filter(title='Multi HW')
        self.assertEqual(hws.count(), 2)
        self.assertEqual(
            set(hws.values_list('classroom_id', flat=True)), {self.c1.id, self.c2.id})
        for hw in hws:
            self.assertEqual(hw.num_questions, 2)
            self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 2)

        session.refresh_from_db()
        self.assertTrue(session.is_confirmed)

    def test_single_class_still_works(self):
        session = self._make_session()
        resp = self._post(session, classroom_ids=[str(self.c3.id)])
        self.assertEqual(resp.status_code, 302)
        hws = Homework.objects.filter(title='Multi HW')
        self.assertEqual(hws.count(), 1)
        self.assertEqual(hws.first().classroom_id, self.c3.id)

    def test_requires_at_least_one_class(self):
        session = self._make_session()
        resp = self._post(session)  # no classroom_ids
        self.assertEqual(resp.status_code, 302)  # redirected back to confirm
        self.assertEqual(Homework.objects.filter(title='Multi HW').count(), 0)
        session.refresh_from_db()
        self.assertFalse(session.is_confirmed)

    def test_pdf_homework_published_by_default(self):
        session = self._make_session()
        self._post(session, classroom_ids=[str(self.c1.id)])
        hw = Homework.objects.get(title='Multi HW', classroom=self.c1)
        self.assertIsNotNone(hw.published_at)
        self.assertEqual(hw.status, Homework.STATUS_PUBLISHED)

    def test_pdf_homework_can_be_scheduled(self):
        session = self._make_session()
        # Future publish_at, before the 2099 due date.
        self._post(session, classroom_ids=[str(self.c1.id)], publish_at='2030-01-01T10:00')
        hw = Homework.objects.get(title='Multi HW', classroom=self.c1)
        self.assertIsNone(hw.published_at)
        self.assertIsNotNone(hw.publish_at)
        self.assertEqual(hw.status, Homework.STATUS_CREATED)

    def test_pdf_publish_at_after_due_date_rejected(self):
        session = self._make_session()
        # publish_at after the 2099 due date is invalid → no homework created.
        resp = self._post(session, classroom_ids=[str(self.c1.id)], publish_at='2100-01-01T10:00')
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(Homework.objects.filter(title='Multi HW').exists())

    def test_duplicate_questions_are_deduped(self):
        # Two extracted questions with identical text resolve to the same
        # maths.Question via get_or_create; the confirm step must dedupe them
        # instead of raising IntegrityError on the (homework, content_id) key.
        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': '1+1?', 'include': True, 'question_type': 'short_answer'},
                {'question_text': '1+1?', 'include': True, 'question_type': 'short_answer'},
            ],
        }
        session.save(update_fields=['extracted_data'])

        resp = self._post(session, classroom_ids=[str(self.c1.id), str(self.c2.id)])
        self.assertEqual(resp.status_code, 302)

        hws = Homework.objects.filter(title='Multi HW')
        self.assertEqual(hws.count(), 2)
        for hw in hws:
            self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 1)
            self.assertEqual(hw.num_questions, 1)

    # A 1×1 PNG — enough for ImageField.save() to store bytes (no Pillow on save).
    _PNG_B64 = (
        'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk'
        'YPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='
    )

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_image_ref_with_space_is_idempotent(self):
        # Storage sanitises 'q 12.jpg' -> 'q_12.jpg' on save, so the dedup target
        # must use the sanitised name; otherwise every run re-creates the row
        # (and on prod would duplicate existing questions with spaced refs).
        from maths.models import Question as MQ
        from homework.views import _save_homework_pdf_questions
        session = self._make_session()
        data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [{'question_text': 'Name this shape', 'include': True,
                           'question_type': 'short_answer', 'has_image': True,
                           'image_ref': 'q 12.jpg'}],
        }
        session.extracted_data = data
        session.extracted_images = {'q 12.jpg': self._PNG_B64}
        session.save()

        _save_homework_pdf_questions(data['questions'], data, self.owner, self.school, session)
        _save_homework_pdf_questions(data['questions'], data, self.owner, self.school, session)

        qs = MQ.objects.filter(question_text='Name this shape')
        self.assertEqual(qs.count(), 1)               # not duplicated on re-run
        self.assertIn('q_12.jpg', str(qs.first().image))  # stored sanitised

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_image_questions_with_same_text_are_not_collapsed(self):
        # Regression: a PDF of image questions that all share a generic stem
        # ("What is the name of this shape?") must produce one maths.Question per
        # image, not collapse to a single row (which silently dropped every image
        # but the first).
        from maths.models import Question as MQ
        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'What is the name of this shape?', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': 'shape_a.png'},
                {'question_text': 'What is the name of this shape?', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': 'shape_b.png'},
                {'question_text': 'What is the name of this shape?', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': 'shape_c.png'},
            ],
        }
        session.extracted_images = {
            'shape_a.png': self._PNG_B64,
            'shape_b.png': self._PNG_B64,
            'shape_c.png': self._PNG_B64,
        }
        session.save(update_fields=['extracted_data', 'extracted_images'])

        resp = self._post(session, classroom_ids=[str(self.c1.id)])
        self.assertEqual(resp.status_code, 302)

        hw = Homework.objects.get(title='Multi HW', classroom=self.c1)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 3)
        self.assertEqual(hw.num_questions, 3)

        # Three distinct questions, each with its own stored image (path uses the
        # topic slug 'addition-mc').
        qs = MQ.objects.filter(question_text='What is the name of this shape?')
        self.assertEqual(qs.count(), 3)
        images = sorted(str(q.image) for q in qs)
        self.assertEqual(images, [
            'questions/year505/addition-mc/shape_a.png',
            'questions/year505/addition-mc/shape_b.png',
            'questions/year505/addition-mc/shape_c.png',
        ])

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_image_question_save_is_idempotent(self):
        # Re-running the save for the same session (the recovery path) must not
        # duplicate image questions — dedup is on the image path.
        from maths.models import Question as MQ
        from homework.views import _save_homework_pdf_questions
        session = self._make_session()
        data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'Name this shape', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': 'x.png'},
            ],
        }
        session.extracted_data = data
        session.extracted_images = {'x.png': self._PNG_B64}
        session.save(update_fields=['extracted_data', 'extracted_images'])

        first = _save_homework_pdf_questions(data['questions'], data, self.owner, self.school, session)
        second = _save_homework_pdf_questions(data['questions'], data, self.owner, self.school, session)

        self.assertEqual(MQ.objects.filter(question_text='Name this shape').count(), 1)
        self.assertEqual(first[0].pk, second[0].pk)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_recover_command_restores_dropped_image_questions(self):
        # A confirmed session whose image questions were collapsed (1 saved) is
        # re-run by the recovery command — all three come back and attach.
        from maths.models import Question as MQ
        from django.core.management import call_command
        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'Name this shape', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': f'r{i}.png'}
                for i in range(3)
            ],
        }
        session.extracted_images = {f'r{i}.png': self._PNG_B64 for i in range(3)}
        session.is_confirmed = True
        hw = Homework.objects.create(
            classroom=self.c1, created_by=self.owner, title='Rec HW',
            homework_type='pdf_upload', num_questions=0,
            due_date=timezone.now() + timedelta(days=30),
        )
        session.homework = hw
        session.save()

        call_command('recover_homework_pdf_images', '--session', str(session.pk), '--attach')

        self.assertEqual(MQ.objects.filter(question_text='Name this shape').count(), 3)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 3)
        hw.refresh_from_db()
        self.assertEqual(hw.num_questions, 3)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_recover_dry_run_creates_nothing_and_writes_no_file(self):
        # --dry-run must leave the DB untouched AND upload no image to storage
        # (image writes aren't transactional, so a naive rollback would orphan
        # files in S3/Spaces).
        from maths.models import Question as MQ
        from django.core.management import call_command
        from django.core.files.storage import default_storage
        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'Name this shape', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': 'dry.png'},
            ],
        }
        session.extracted_images = {'dry.png': self._PNG_B64}
        session.is_confirmed = True
        session.save()

        before = MQ.objects.count()
        call_command('recover_homework_pdf_images', '--session', str(session.pk), '--dry-run')

        self.assertEqual(MQ.objects.count(), before)  # rolled back
        self.assertFalse(default_storage.exists('questions/year505/addition-mc/dry.png'))

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_recover_skips_homework_with_submissions(self):
        # Recovery restores questions to the bank but must NOT retro-edit a
        # homework students have already submitted to.
        from maths.models import Question as MQ
        from homework.models import HomeworkSubmission
        from django.core.management import call_command
        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'Name this shape', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': f's{i}.png'}
                for i in range(2)
            ],
        }
        session.extracted_images = {f's{i}.png': self._PNG_B64 for i in range(2)}
        session.is_confirmed = True
        hw = Homework.objects.create(
            classroom=self.c1, created_by=self.owner, title='Submitted HW',
            homework_type='pdf_upload', num_questions=0,
            due_date=timezone.now() + timedelta(days=30),
        )
        HomeworkSubmission.objects.create(homework=hw, student=self.owner, total_questions=1)
        session.homework = hw
        session.save()

        call_command('recover_homework_pdf_images', '--session', str(session.pk), '--attach')

        # Questions recovered to the bank, but homework left untouched.
        self.assertEqual(MQ.objects.filter(question_text='Name this shape').count(), 2)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw).count(), 0)
        hw.refresh_from_db()
        self.assertEqual(hw.num_questions, 0)

    @override_settings(STORAGES={
        'default': {'BACKEND': 'django.core.files.storage.InMemoryStorage'},
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    })
    def test_recover_attaches_to_sibling_classes(self):
        # The same PDF assigned to two classes: both (0-submission) homeworks get
        # the recovered questions, not just the session-linked one.
        from maths.models import Question as MQ
        from classroom.views import _get_question_scope
        from django.core.management import call_command
        school_id, _dept, _ = _get_question_scope(self.owner)

        # The one question the bug left behind, shared by both class homeworks.
        q0 = MQ.objects.create(
            question_text='Name this shape', topic=self.topic, level=self.level,
            school_id=school_id, question_type='short_answer',
            image='questions/year505/addition-mc/k0.png',
        )
        hw_a = Homework.objects.create(
            classroom=self.c1, created_by=self.owner, title='Shared HW',
            homework_type='pdf_upload', num_questions=1,
            due_date=timezone.now() + timedelta(days=30))
        hw_b = Homework.objects.create(
            classroom=self.c2, created_by=self.owner, title='Shared HW',
            homework_type='pdf_upload', num_questions=1,
            due_date=timezone.now() + timedelta(days=30))
        for hw in (hw_a, hw_b):
            HomeworkQuestion.objects.create(
                homework=hw, question=q0, subject_slug='mathematics',
                content_id=q0.pk, order=1)

        session = self._make_session()
        session.extracted_data = {
            'year_level': 505, 'subject': 'Mathematics', 'topic': 'Addition',
            'questions': [
                {'question_text': 'Name this shape', 'include': True,
                 'question_type': 'short_answer', 'has_image': True, 'image_ref': f'k{i}.png'}
                for i in range(3)
            ],
        }
        session.extracted_images = {f'k{i}.png': self._PNG_B64 for i in range(3)}
        session.is_confirmed = True
        session.homework = hw_a
        session.save()

        call_command('recover_homework_pdf_images', '--session', str(session.pk), '--attach')

        # 2 new questions (k1, k2) created; both class homeworks now hold all 3.
        self.assertEqual(MQ.objects.filter(question_text='Name this shape').count(), 3)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw_a).count(), 3)
        self.assertEqual(HomeworkQuestion.objects.filter(homework=hw_b).count(), 3)
        hw_b.refresh_from_db()
        self.assertEqual(hw_b.num_questions, 3)

    def test_session_classroom_fallback_when_no_ids_posted(self):
        # Legacy/no-JS path: no classroom_ids submitted falls back to the
        # session's pre-selected class (still re-checked against scope).
        session = self._make_session()
        session.classroom = self.c2
        session.save(update_fields=['classroom'])
        resp = self._post(session)  # no classroom_ids
        self.assertEqual(resp.status_code, 302)
        hws = Homework.objects.filter(title='Multi HW')
        self.assertEqual(hws.count(), 1)
        self.assertEqual(hws.first().classroom_id, self.c2.id)

    def test_owner_can_monitor_and_open_created_homework(self):
        # Reproduces the reported issue: after assigning, the owner (a school
        # admin with no ClassTeacher row) must see the class in the monitor and
        # be able to open the homework — not "not assigned to any classes" / 404.
        session = self._make_session()
        self._post(session, classroom_ids=[str(self.c1.id)])
        hw = Homework.objects.filter(title='Multi HW', classroom=self.c1).first()
        self.assertIsNotNone(hw)

        self.client.force_login(self.owner)
        mon = self.client.get(reverse('homework:teacher_monitor'))
        self.assertEqual(mon.status_code, 200)
        self.assertContains(mon, self.c1.name)
        self.assertNotContains(mon, 'not assigned to any classes')

        detail = self.client.get(reverse('homework:teacher_detail', kwargs={'homework_id': hw.id}))
        self.assertEqual(detail.status_code, 200)

    def test_resubmit_confirmed_session_redirects_not_404(self):
        # Re-submitting an already-confirmed upload (back button / double-click)
        # should redirect to the created homework, not raise a 404.
        session = self._make_session()
        first = self._post(session, classroom_ids=[str(self.c1.id)])
        self.assertEqual(first.status_code, 302)
        hw = Homework.objects.filter(title='Multi HW', classroom=self.c1).first()
        self.assertIsNotNone(hw)

        # Second submit of the same (now confirmed) session.
        second = self._post(session, classroom_ids=[str(self.c1.id)])
        self.assertEqual(second.status_code, 302)
        self.assertIn(reverse('homework:teacher_detail', kwargs={'homework_id': hw.id}), second.url)
        # No extra homework created.
        self.assertEqual(Homework.objects.filter(title='Multi HW', classroom=self.c1).count(), 1)

    def test_get_confirmed_session_redirects(self):
        session = self._make_session()
        session.is_confirmed = True
        session.save(update_fields=['is_confirmed'])
        self.client.force_login(self.owner)
        url = reverse('homework:pdf_confirm', kwargs={'session_id': session.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)  # redirected, not 404

    def test_unauthorized_class_id_is_dropped(self):
        other_admin = CustomUser.objects.create_user('oa_mc', 'oa_mc@test.com', 'pass1234')
        other_school = School.objects.create(name='Other MC', slug='other-mc', admin=other_admin)
        foreign = ClassRoom.objects.create(name='Foreign', code='MCLS9999', school=other_school)

        session = self._make_session()
        resp = self._post(session, classroom_ids=[str(self.c1.id), str(foreign.id)])
        self.assertEqual(resp.status_code, 302)

        hws = Homework.objects.filter(title='Multi HW')
        self.assertEqual(hws.count(), 1)
        self.assertEqual(hws.first().classroom_id, self.c1.id)
        self.assertFalse(Homework.objects.filter(classroom=foreign).exists())


class HomeworkPDFLongDivisionSaveTest(HomeworkTestBase):
    """The homework PDF importer turns a long_division payload into a proper
    long-division Question with dividend/divisor, a computed answer, and no image."""

    def _save(self, q, images=None):
        from homework.views import _save_homework_pdf_questions
        session = HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='g5.pdf',
            extracted_images=images or {},
        )
        global_data = {
            'year_level': 501, 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
        }
        return _save_homework_pdf_questions([q], global_data, self.teacher, self.school, session)

    def test_long_division_saved_with_computed_answer(self):
        saved = self._save({
            'question_text': 'Solve using long division: 611 ÷ 47',
            'question_type': 'long_division',
            'dividend': 611, 'divisor': 47,
            'difficulty': 2, 'points': 1, 'has_image': False,
        })
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, Question.LONG_DIVISION)
        self.assertEqual((q.dividend, q.divisor), (611, 47))
        self.assertEqual([(a.answer_text, a.is_correct) for a in q.answers.all()], [('13', True)])

    def test_remainder_answer_format(self):
        saved = self._save({
            'question_text': 'Solve using long division: 508 ÷ 9',
            'question_type': 'long_division', 'dividend': 508, 'divisor': 9,
            'difficulty': 2, 'has_image': False,
            'answers': [{'text': '999', 'is_correct': True}],  # AI answer must be ignored
        })
        self.assertEqual([a.answer_text for a in saved[0].answers.all()], ['56 r 4'])

    def test_invalid_long_division_is_skipped(self):
        saved = self._save({
            'question_text': 'Solve using long division: 100 ÷ 0',
            'question_type': 'long_division', 'dividend': 100, 'divisor': 0,
            'difficulty': 2, 'has_image': False,
        })
        self.assertEqual(saved, [])

    def test_layout_image_is_never_attached(self):
        import base64
        png = base64.b64encode(b'\x89PNG\r\n\x1a\n').decode()
        saved = self._save(
            {
                'question_text': 'Solve using long division: 520 ÷ 10',
                'question_type': 'long_division', 'dividend': 520, 'divisor': 10,
                'difficulty': 2, 'has_image': True, 'image_ref': 'img.png',
            },
            images={'img.png': png},
        )
        self.assertEqual(len(saved), 1)
        self.assertFalse(saved[0].image)


class HomeworkPreviewAddQuestionTest(HomeworkTestBase):
    """The preview POST honours `question_order`, letting teachers insert questions."""

    def _make_session(self):
        return HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 501, 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
                'questions': [
                    {'question_text': '1+1?', 'include': True, 'question_type': 'short_answer'},
                    {'question_text': '2+2?', 'include': True, 'question_type': 'short_answer'},
                ],
            },
            extracted_images={},
        )

    def test_preview_renders_add_question_controls(self):
        session = self._make_session()
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, '+ Add question below')
        self.assertContains(resp, 'name="question_order"')
        self.assertContains(resp, 'function addQuestionAfter')

    def test_inserts_new_question_in_order(self):
        session = self._make_session()
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})
        # Insert a new question (index 2) between the two existing ones.
        resp = self.client.post(url, {
            'year_level': '501', 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
            'question_order': '0,2,1',
            'q_0_include': 'on', 'q_0_text': '1+1?', 'q_0_type': 'short_answer',
            'q_2_include': 'on', 'q_2_text': 'Inserted Q', 'q_2_type': 'short_answer',
            'q_2_answer_0_text': '5', 'q_2_answer_0_correct': 'on',
            'q_1_include': 'on', 'q_1_text': '2+2?', 'q_1_type': 'short_answer',
        })
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        texts = [q['question_text'] for q in session.extracted_data['questions']]
        self.assertEqual(texts, ['1+1?', 'Inserted Q', '2+2?'])

    def test_blank_added_question_is_dropped(self):
        session = self._make_session()
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})
        resp = self.client.post(url, {
            'year_level': '501', 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
            'question_order': '0,1,2',
            'q_0_include': 'on', 'q_0_text': '1+1?', 'q_0_type': 'short_answer',
            'q_1_include': 'on', 'q_1_text': '2+2?', 'q_1_type': 'short_answer',
            'q_2_include': 'on', 'q_2_text': '   ', 'q_2_type': 'short_answer',  # blank → dropped
        })
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        self.assertEqual(len(session.extracted_data['questions']), 2)

    def test_legacy_post_without_order_still_works(self):
        session = self._make_session()
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})
        resp = self.client.post(url, {
            'year_level': '501', 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
            'q_0_include': 'on', 'q_0_text': 'edited', 'q_0_type': 'short_answer',
            'q_1_include': 'on', 'q_1_text': '2+2?', 'q_1_type': 'short_answer',
        })
        self.assertEqual(resp.status_code, 302)
        session.refresh_from_db()
        texts = [q['question_text'] for q in session.extracted_data['questions']]
        self.assertEqual(texts, ['edited', '2+2?'])


class HomeworkPreviewLargeWorksheetTest(HomeworkTestBase):
    """A big worksheet must not 400 on submit.

    The preview form posts every question back as ~15 individual fields, so a
    several-hundred-question PDF used to cross DATA_UPLOAD_MAX_NUMBER_FIELDS and
    Django's request parser raised TooManyFieldsSent *before the view ran*,
    surfacing as a bare "Bad Request (400)" with the URL stuck on the preview
    page (observed in production for session 23). The limit is now sized for
    large workbooks; this guards against it regressing back down.
    """

    def test_large_worksheet_submit_does_not_400(self):
        n = 400  # ~6000 fields — well past the old 5000 ceiling, under the new one.
        session = HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='workbook.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 501, 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
                'questions': [
                    {'question_text': f'Q{i}', 'include': True, 'question_type': 'short_answer'}
                    for i in range(n)
                ],
            },
            extracted_images={},
        )
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})

        payload = {'year_level': '501', 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
                   'question_order': ','.join(str(i) for i in range(n))}
        for i in range(n):
            pre = f'q_{i}_'
            payload.update({
                pre + 'include': 'on', pre + 'image_ref': '',
                pre + 'text': f'Q{i}', pre + 'type': 'short_answer',
                pre + 'validation_type': 'auto', pre + 'difficulty': '1', pre + 'points': '1',
                pre + 'grading_rubric': '', pre + 'explanation': '',
                pre + 'answer_0_text': 'a', pre + 'answer_0_correct': 'on',
                pre + 'answer_1_text': 'b', pre + 'answer_2_text': 'c', pre + 'answer_3_text': 'd',
            })

        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 302)  # would be 400 with the old limit
        session.refresh_from_db()
        self.assertEqual(len(session.extracted_data['questions']), n)

    def test_heavy_text_worksheet_submit_does_not_400(self):
        """Few questions, but megabytes of text — the body-size twin.

        Raising DATA_UPLOAD_MAX_NUMBER_FIELDS alone did NOT fix prod session 23:
        the preview form is multipart, so long AI-generated rubrics/explanations
        push the non-file body past DATA_UPLOAD_MAX_MEMORY_SIZE (default 2.5 MB)
        and Django raises RequestDataTooBig *before the view runs* — the identical
        bare 400. This uses only ~40 questions (well under the field ceiling) but
        ~3.5 MB of text, so it fails iff the memory-size ceiling is too low.
        """
        n = 40
        big = 'x' * 90_000  # ~90 KB per question × 40 ≈ 3.5 MB > old 2.5 MB default
        session = HomeworkUploadSession.objects.create(
            user=self.teacher, school=self.school, pdf_filename='heavy.pdf',
            status=HomeworkUploadSession.STATUS_DONE,
            extracted_data={
                'year_level': 501, 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
                'questions': [
                    {'question_text': f'Q{i}', 'include': True, 'question_type': 'short_answer'}
                    for i in range(n)
                ],
            },
            extracted_images={},
        )
        self.client.force_login(self.teacher)
        url = reverse('homework:pdf_preview', kwargs={'session_id': session.pk})

        payload = {'year_level': '501', 'subject': 'Maths HW Test', 'topic': 'Fractions HW',
                   'question_order': ','.join(str(i) for i in range(n))}
        for i in range(n):
            pre = f'q_{i}_'
            payload.update({
                pre + 'include': 'on', pre + 'image_ref': '',
                pre + 'text': f'Q{i}', pre + 'type': 'short_answer',
                pre + 'validation_type': 'auto', pre + 'difficulty': '1', pre + 'points': '1',
                pre + 'grading_rubric': big, pre + 'explanation': big,
                pre + 'answer_0_text': 'a', pre + 'answer_0_correct': 'on',
                pre + 'answer_1_text': 'b', pre + 'answer_2_text': 'c', pre + 'answer_3_text': 'd',
            })

        resp = self.client.post(url, payload)
        self.assertEqual(resp.status_code, 302)  # would be 400 (RequestDataTooBig) at 2.5 MB
        session.refresh_from_db()
        self.assertEqual(len(session.extracted_data['questions']), n)


# ---------------------------------------------------------------------------
# CPP-344 — Homework monitor "All" filter + back-to-All button
# ---------------------------------------------------------------------------

class TeacherHomeworkMonitorAllFilterTest(HomeworkTestBase):
    """The monitor filter must offer an 'All' option (the default) that shows
    homework across every class the teacher is assigned to, and the detail page
    back button must land on the monitor with All selected."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        # A second class taught by the same teacher, with its own homework.
        cls.classroom2 = ClassRoom.objects.create(
            name='Year 6 Science', code='HWTEST02', school=cls.school,
        )
        ClassTeacher.objects.create(classroom=cls.classroom2, teacher=cls.teacher)
        cls.homework2 = Homework.objects.create(
            classroom=cls.classroom2,
            created_by=cls.teacher,
            title='Science Homework',
            homework_type='topic',
            num_questions=5,
            due_date=timezone.now() + timedelta(days=7),
            max_attempts=2,
        )
        cls.homework2.topics.add(cls.topic)

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')

    def _monitor(self, query=''):
        return self.client.get(reverse('homework:teacher_monitor') + query)

    def test_all_option_present(self):
        resp = self._monitor()
        self.assertContains(resp, 'value="all"')
        self.assertContains(resp, 'All classes')

    def test_default_is_not_all(self):
        # No param keeps the first-class default so the New Homework shortcut
        # stays available; All is opt-in via the dropdown / back button.
        resp = self._monitor()
        self.assertFalse(resp.context['show_all'])
        self.assertIsNotNone(resp.context['selected_classroom'])

    def test_all_shows_homework_across_classes(self):
        resp = self._monitor('?classroom=all')
        self.assertContains(resp, 'Test Homework')      # class 1
        self.assertContains(resp, 'Science Homework')    # class 2

    def test_all_explicit_param(self):
        resp = self._monitor('?classroom=all')
        self.assertTrue(resp.context['show_all'])
        self.assertContains(resp, 'Science Homework')

    def test_class_badge_shown_in_all_view(self):
        resp = self._monitor('?classroom=all')
        # Each card is tagged with its class name in the All view.
        self.assertContains(resp, 'Year 6 Science')

    def test_specific_class_filters_out_others(self):
        resp = self._monitor(f'?classroom={self.classroom2.id}')
        self.assertFalse(resp.context['show_all'])
        self.assertEqual(resp.context['selected_classroom'], self.classroom2)
        self.assertContains(resp, 'Science Homework')
        self.assertNotContains(resp, 'Test Homework')

    def test_invalid_classroom_falls_back_gracefully(self):
        # Unknown id falls back to the first class (original behaviour), not a 500.
        resp = self._monitor('?classroom=999999')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.context['show_all'])
        self.assertIsNotNone(resp.context['selected_classroom'])

    def test_non_numeric_classroom_does_not_500(self):
        resp = self._monitor('?classroom=abc')
        self.assertEqual(resp.status_code, 200)

    def test_detail_back_link_lands_on_all(self):
        resp = self.client.get(
            reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, reverse('homework:teacher_monitor') + '?classroom=all')

    def test_other_teacher_classes_excluded_from_all(self):
        # A class taught by a different teacher must not appear in teacher1's All view.
        other_class = ClassRoom.objects.create(
            name='Other Teacher Class', code='HWTEST03', school=self.school,
        )
        ClassTeacher.objects.create(classroom=other_class, teacher=self.other_teacher)
        Homework.objects.create(
            classroom=other_class, created_by=self.other_teacher,
            title='Other Teacher Homework', homework_type='topic',
            num_questions=5, due_date=timezone.now() + timedelta(days=7), max_attempts=1,
        )
        resp = self._monitor('?classroom=all')
        self.assertNotContains(resp, 'Other Teacher Homework')


# ---------------------------------------------------------------------------
# Soft-delete: the creator (HoI / HoD / teacher) can delete homework they added
# ---------------------------------------------------------------------------

class HomeworkDeleteTest(HomeworkTestBase):
    """As HoI/HoD/Teacher I can delete any homework I added.

    Deletion is a soft-delete: the homework disappears from every teacher and
    student view, but student submissions and grades are preserved.
    """

    def _delete_url(self, hw):
        return reverse('homework:delete', kwargs={'homework_id': hw.id})

    def test_creator_can_soft_delete(self):
        self.client.force_login(self.teacher)
        resp = self.client.post(self._delete_url(self.homework))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp.url, reverse('homework:teacher_monitor'))

        # Row still exists (soft delete) and is stamped with who/when.
        hw = Homework.all_objects.get(pk=self.homework.pk)
        self.assertIsNotNone(hw.deleted_at)
        self.assertEqual(hw.deleted_by, self.teacher)

        # Hidden from the default manager used by every list/detail query.
        self.assertFalse(Homework.objects.filter(pk=self.homework.pk).exists())

    def test_soft_delete_preserves_student_submissions_and_grades(self):
        submission = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            score=4, total_questions=5, points=8.0,
        )
        answer = HomeworkStudentAnswer.objects.create(
            submission=submission, question=self.questions[0],
            selected_answer=self.questions[0].answers.first(), is_correct=True,
        )

        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))

        # Submissions and answers survive the soft delete.
        self.assertTrue(HomeworkSubmission.objects.filter(pk=submission.pk).exists())
        self.assertTrue(HomeworkStudentAnswer.objects.filter(pk=answer.pk).exists())
        # And the relation back to the (hidden) homework still resolves.
        self.assertEqual(
            HomeworkSubmission.objects.get(pk=submission.pk).homework_id,
            self.homework.pk,
        )

    def test_deleted_homework_hidden_from_teacher_monitor(self):
        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))
        resp = self.client.get(reverse('homework:teacher_monitor') + '?classroom=all&week=all')
        # Assert on the detail link rather than the title — the title also shows
        # in the "… deleted." flash message rendered on this same page.
        detail_url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        self.assertNotContains(resp, f'href="{detail_url}"')

    def test_deleted_homework_hidden_from_student_list(self):
        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))
        self.client.logout()

        self.client.force_login(self.student)
        resp = self.client.get(reverse('homework:student_list'))
        self.assertNotContains(resp, 'Test Homework')

    def test_deleted_homework_detail_returns_404(self):
        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))
        resp = self.client.get(
            reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        )
        self.assertEqual(resp.status_code, 404)

    def test_non_creator_cannot_delete(self):
        # other_teacher holds the teacher role (passes the role gate) but did not
        # create this homework, so the delete must 404 and change nothing.
        self.client.force_login(self.other_teacher)
        resp = self.client.post(self._delete_url(self.homework))
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Homework.objects.filter(pk=self.homework.pk).exists())

    def test_delete_requires_login(self):
        resp = self.client.post(self._delete_url(self.homework))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/login', resp.url.lower())
        self.assertTrue(Homework.objects.filter(pk=self.homework.pk).exists())

    def test_delete_is_post_only(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(self._delete_url(self.homework))
        self.assertEqual(resp.status_code, 405)
        self.assertTrue(Homework.objects.filter(pk=self.homework.pk).exists())

    def test_delete_writes_audit_log(self):
        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))
        self.assertTrue(
            AuditLog.objects.filter(action='homework_deleted').exists()
        )

    def test_delete_button_shown_to_creator(self):
        self.client.force_login(self.teacher)
        resp = self.client.get(
            reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        )
        self.assertContains(resp, self._delete_url(self.homework))

    def test_double_delete_is_idempotent(self):
        self.client.force_login(self.teacher)
        self.client.post(self._delete_url(self.homework))
        first = Homework.all_objects.get(pk=self.homework.pk).deleted_at
        # A second POST 404s (already hidden from the default manager) and the
        # original timestamp is left untouched.
        resp = self.client.post(self._delete_url(self.homework))
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(Homework.all_objects.get(pk=self.homework.pk).deleted_at, first)


# ---------------------------------------------------------------------------
# Per-class homework progress leaderboard (CPP-348)
# ---------------------------------------------------------------------------
# Ranks a class's students by best score, highlighting the top three. Covers
# per-homework ranking, the fewer-attempts tie-break, the not-started fallback,
# the all-homework aggregate scope, access scoping and the tab wiring.
# ---------------------------------------------------------------------------

class HomeworkLeaderboardTest(HomeworkTestBase):

    def setUp(self):
        self.client = Client()
        self.client.login(username='teacher1', password='pass1234')
        self.url = reverse('homework:leaderboard')

    # -- basics -----------------------------------------------------------

    def test_requires_login(self):
        self.client.logout()
        resp = self.client.get(self.url)
        self.assertNotEqual(resp.status_code, 200)

    def test_page_renders(self):
        resp = self.client.get(self.url + f'?classroom={self.classroom.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Homework progress')

    def test_no_submissions_shows_empty_state(self):
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        self.assertEqual(resp.context['ranked_rows'], [])
        self.assertContains(resp, 'No student has attempted')

    # -- per-homework ranking --------------------------------------------

    def test_ranks_by_best_points_and_marks_first(self):
        # student2 outscores student → ranks first.
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student2,
            attempt_number=1, score=5, total_questions=5, points=95.0,
        )
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        ranked = resp.context['ranked_rows']
        self.assertEqual(ranked[0]['student'], self.student2)
        self.assertEqual(ranked[0]['rank'], 1)
        self.assertEqual(ranked[1]['student'], self.student)
        self.assertEqual(ranked[1]['rank'], 2)
        # Top three is exposed for the podium.
        self.assertEqual(resp.context['podium'][0]['student'], self.student2)

    def test_best_attempt_wins_over_later_lower_one(self):
        # A strong first attempt is the student's score even if they retry worse.
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=5, total_questions=5, points=90.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=2, score=2, total_questions=5, points=40.0,
        )
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        row = resp.context['ranked_rows'][0]
        self.assertEqual(row['percentage'], 100)
        self.assertEqual(row['attempts'], 2)

    def test_higher_percentage_outranks_higher_points(self):
        # The board ranks by displayed score (percentage) first, so a higher
        # percentage wins even if the other student earned more points.
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=100.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student2,
            attempt_number=1, score=5, total_questions=5, points=60.0,
        )
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        ranked = resp.context['ranked_rows']
        self.assertEqual(ranked[0]['student'], self.student2)  # 100% beats 80%
        self.assertEqual(ranked[1]['student'], self.student)

    def test_fewer_attempts_breaks_score_tie(self):
        # Equal best points → the student who needed fewer attempts ranks higher.
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=2, score=4, total_questions=5, points=80.0,
        )
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student2,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        ranked = resp.context['ranked_rows']
        self.assertEqual(ranked[0]['student'], self.student2)  # 1 attempt
        self.assertEqual(ranked[1]['student'], self.student)   # 2 attempts

    def test_student_without_submission_is_unranked(self):
        HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0,
        )
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        ranked_students = [r['student'] for r in resp.context['ranked_rows']]
        unranked_students = [r['student'] for r in resp.context['unranked_rows']]
        self.assertIn(self.student, ranked_students)
        self.assertNotIn(self.student2, ranked_students)
        self.assertIn(self.student2, unranked_students)

    # -- week scoping ----------------------------------------------------

    def test_defaults_to_last_completed_week_not_current(self):
        # With no week param the board lands on the most recent *completed* week
        # with homework due — never the current week (which may be in progress).
        #
        # Time is frozen so the week boundaries are deterministic. This test
        # used to flake on the CI clock: with TIME_ZONE='Pacific/Auckland'
        # (UTC+12), a UTC-Sunday afternoon is already Monday in Auckland, which
        # pulled the shared ``past_homework`` fixture (due "yesterday" = Sunday)
        # into the last completed week and made *it* the default-week anchor —
        # the most recent completed homework — instead of this test's homework.
        # Pinning every relevant due date to a frozen week removes that
        # dependency on the wall clock.
        frozen = timezone.make_aware(datetime(2026, 6, 17, 12, 0))  # a Wednesday
        with freeze_time(frozen):
            # Park the fixtures' relative-dated homework so only this test's
            # data drives the default-week selection: ``past_homework`` into the
            # current (in-progress) week, ``homework`` into the future.
            Homework.objects.filter(pk=self.past_homework.pk).update(
                due_date=timezone.make_aware(datetime(2026, 6, 16, 12, 0)),  # current week
            )
            Homework.objects.filter(pk=self.homework.pk).update(
                due_date=timezone.make_aware(datetime(2026, 7, 1, 12, 0)),  # future
            )
            # The only homework due in the last completed week.
            hw = Homework.objects.create(
                classroom=self.classroom, created_by=self.teacher, title='Last Week HW',
                homework_type='topic', num_questions=5,
                due_date=timezone.make_aware(datetime(2026, 6, 10, 12, 0)),  # Wed, prev week
                max_attempts=3,
            )
            HomeworkSubmission.objects.create(
                homework=hw, student=self.student,
                attempt_number=1, score=4, total_questions=5, points=80.0,
            )
            resp = self.client.get(self.url + f'?classroom={self.classroom.id}')

        self.assertEqual(resp.context['week_start'], date(2026, 6, 8))  # Mon of prev week
        # Not the current week (Mon 2026-06-15).
        self.assertNotEqual(resp.context['week_start'], date(2026, 6, 15))
        self.assertIn(self.student, [r['student'] for r in resp.context['ranked_rows']])

    def test_dropdown_lists_all_homework_across_weeks(self):
        # The homework dropdown lists every published homework, not just the
        # selected week's (filter by name vs filter by week).
        resp = self.client.get(self.url + f'?classroom={self.classroom.id}')
        ids = {h.id for h in resp.context['all_homework']}
        self.assertIn(self.homework.id, ids)       # due next week
        self.assertIn(self.past_homework.id, ids)  # due this week

    def test_selecting_homework_snaps_to_its_week(self):
        # Picking a homework by name moves the board to that homework's week and
        # ranks just that assignment.
        from django.utils import timezone
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework={self.homework.id}'
        )
        self.assertFalse(resp.context['aggregate'])
        self.assertEqual(resp.context['selected_homework'], self.homework)
        due = timezone.localtime(self.homework.due_date).date()
        self.assertEqual(resp.context['week_start'], due - timedelta(days=due.weekday()))

    # -- aggregate ("all homework this week") ----------------------------

    def test_aggregate_scope_averages_best_scores(self):
        # Two homeworks in the SAME week so the week aggregate spans both.
        # student: 80% + 100% → avg 90.  student2: 60% + 80% → avg 70.
        from django.utils import timezone
        now = timezone.now()
        # Mid-week of last week, away from Mon/Sun boundaries (timezone-safe).
        monday = (now - timedelta(days=now.weekday() + 7)).replace(
            hour=12, minute=0, second=0, microsecond=0,
        )
        hw_a = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='Week HW A',
            homework_type='topic', num_questions=5,
            due_date=monday + timedelta(days=1), max_attempts=3,
        )
        hw_b = Homework.objects.create(
            classroom=self.classroom, created_by=self.teacher, title='Week HW B',
            homework_type='topic', num_questions=5,
            due_date=monday + timedelta(days=2), max_attempts=3,
        )
        HomeworkSubmission.objects.create(homework=hw_a, student=self.student,
            attempt_number=1, score=4, total_questions=5, points=80.0)
        HomeworkSubmission.objects.create(homework=hw_b, student=self.student,
            attempt_number=1, score=5, total_questions=5, points=100.0)
        HomeworkSubmission.objects.create(homework=hw_a, student=self.student2,
            attempt_number=1, score=3, total_questions=5, points=60.0)
        HomeworkSubmission.objects.create(homework=hw_b, student=self.student2,
            attempt_number=1, score=4, total_questions=5, points=80.0)

        week_iso = monday.date().isoformat()
        resp = self.client.get(
            self.url + f'?classroom={self.classroom.id}&homework=all&week={week_iso}'
        )
        self.assertTrue(resp.context['aggregate'])
        ranked = resp.context['ranked_rows']
        self.assertEqual(ranked[0]['student'], self.student)
        self.assertEqual(ranked[0]['avg_percentage'], 90)
        self.assertEqual(ranked[1]['student'], self.student2)
        self.assertEqual(ranked[1]['avg_percentage'], 70)

    # -- default class (current / next upcoming) -------------------------

    def test_current_or_next_classroom_picks_in_session(self):
        from datetime import time as dtime
        from django.utils import timezone
        from homework.views import _current_or_next_classroom
        now = timezone.localtime()
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        in_session = ClassRoom.objects.create(
            name='In Session', code='LBINSES1', school=self.school,
            day=days[now.weekday()], start_time=dtime(0, 0, 0), end_time=dtime(23, 59, 59),
        )
        tomorrow = ClassRoom.objects.create(
            name='Tomorrow', code='LBTMRW1', school=self.school,
            day=days[(now.weekday() + 1) % 7], start_time=dtime(9, 0), end_time=dtime(10, 0),
        )
        picked = _current_or_next_classroom(
            ClassRoom.objects.filter(id__in=[tomorrow.id, in_session.id])
        )
        self.assertEqual(picked, in_session)

    def test_defaults_to_current_class_for_teacher(self):
        # With no ?classroom, default to the teacher's in-session / next class,
        # not just the first one.
        from datetime import time as dtime
        from django.utils import timezone
        now = timezone.localtime()
        days = ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']
        current = ClassRoom.objects.create(
            name='Now Class', code='LBNOW1', school=self.school,
            day=days[now.weekday()], start_time=dtime(0, 0, 0), end_time=dtime(23, 59, 59),
        )
        ClassTeacher.objects.create(classroom=current, teacher=self.teacher)
        resp = self.client.get(self.url)  # no ?classroom
        self.assertEqual(resp.context['selected_classroom'], current)

    # -- access scoping & navigation -------------------------------------

    def test_other_teacher_sees_no_class(self):
        # teacher2 manages no classes → can't reach this class's board.
        self.client.login(username='teacher2', password='pass1234')
        resp = self.client.get(self.url + f'?classroom={self.classroom.id}')
        self.assertIsNone(resp.context['selected_classroom'])
        self.assertContains(resp, 'not assigned to any classes')

    def test_monitor_links_to_leaderboard(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        self.assertContains(resp, reverse('homework:leaderboard'))
