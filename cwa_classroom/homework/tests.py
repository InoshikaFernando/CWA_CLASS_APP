from datetime import timedelta

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

# ---------------------------------------------------------------------------
# UI (template rendering) tests
# ---------------------------------------------------------------------------
# These tests assert on specific HTML elements, CSS classes, labels and
# interactive controls that students and teachers see in the browser.
# ---------------------------------------------------------------------------

from accounts.models import CustomUser, Role
from classroom.models import ClassRoom, ClassStudent, ClassTeacher, Level, School, SchoolTeacher, Subject, Topic
from maths.models import Answer, Question

from .models import Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission


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

        # Subject / topic / level / questions
        subject, _ = Subject.objects.get_or_create(slug='maths-hw-test', defaults={'name': 'Maths HW Test'})
        cls.level, _ = Level.objects.get_or_create(
            level_number=501, defaults={'display_name': 'HW Test Level'},
        )
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

    def test_late_submission_shows_late_status(self):
        sub = HomeworkSubmission.objects.create(
            homework=self.past_homework, student=self.student,
            attempt_number=1, score=3, total_questions=5, points=60.0,
        )
        HomeworkSubmission.objects.filter(pk=sub.pk).update(
            submitted_at=self.past_homework.due_date + timedelta(hours=2)
        )
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'Late')

    def test_overdue_student_shows_overdue_status(self):
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertContains(resp, 'Overdue')

    def test_other_teacher_gets_404(self):
        self.client.login(username='teacher2', password='pass1234')
        url = reverse('homework:teacher_detail', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)


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

    def test_take_blocked_when_past_due(self):
        url = reverse('homework:student_take', kwargs={'homework_id': self.past_homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 302)

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

    def test_non_enrolled_student_gets_404(self):
        self.client.login(username='student2', password='pass1234')
        # Remove student2 from classroom
        ClassStudent.objects.filter(classroom=self.classroom, student=self.student2).update(is_active=False)
        url = reverse('homework:student_take', kwargs={'homework_id': self.homework.id})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 404)
        # Restore
        ClassStudent.objects.filter(classroom=self.classroom, student=self.student2).update(is_active=True)


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
        self.assertContains(resp, 'Open')

    def test_closed_badge_shown_for_past_homework(self):
        resp = self.client.get(
            reverse('homework:teacher_monitor') + f'?classroom={self.classroom.id}'
        )
        self.assertContains(resp, 'Closed')

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

    def test_no_action_button_when_past_due(self):
        resp = self.client.get(reverse('homework:student_list'))
        # past_homework is closed — no Start/Retry button for it
        # The "Overdue" badge should appear instead
        self.assertContains(resp, 'Overdue')
        self.assertNotContains(resp, 'href="/homework/%d/take/' % self.past_homework.id)

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
