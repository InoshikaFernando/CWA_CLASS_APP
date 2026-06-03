"""CPP-307d: async AI grading for homework submissions."""
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from accounts.models import CustomUser, Role
from classroom.models import ClassRoom, School
from homework.models import (
    Homework, HomeworkStudentAnswer, HomeworkSubmission,
)
from homework.views import (
    AI_GRADE_ASYNC_THRESHOLD, _trigger_ai_grading_for_submission,
)


class GradingTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.teacher = CustomUser.objects.create_user('g_t', 'g_t@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.teacher.roles.add(teacher_role)
        cls.student = CustomUser.objects.create_user('g_s', 'g_s@test.internal', 'pw1!')
        cls.school = School.objects.create(name='G School', slug='g-school', admin=cls.teacher)
        cls.classroom = ClassRoom.objects.create(
            name='G Class', school=cls.school, is_active=True)
        cls.homework = Homework.objects.create(
            classroom=cls.classroom, created_by=cls.teacher, title='HW',
            due_date=timezone.now() + timedelta(days=7),
        )

    def _submission_with_pending(self, n):
        submission = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=HomeworkSubmission.get_next_attempt_number(self.homework, self.student),
        )
        for i in range(n):
            HomeworkStudentAnswer.objects.create(
                submission=submission,
                content_id=i + 1,
                review_status=HomeworkStudentAnswer.REVIEW_PENDING_AI,
                text_answer='answer',
            )
        return submission


class TriggerThresholdTests(GradingTestBase):
    @patch('taskqueue.services.enqueue_task')
    @patch('homework.views.grade_pending_answers')
    def test_small_batch_grades_inline(self, mock_grade, mock_enqueue):
        submission = self._submission_with_pending(AI_GRADE_ASYNC_THRESHOLD)
        _trigger_ai_grading_for_submission(submission, request=None)
        mock_grade.assert_called_once()
        mock_enqueue.assert_not_called()

    @patch('homework.views.grade_pending_answers')
    @patch('homework.tasks.grade_submission_answers')
    @patch('taskqueue.services.django_rq.get_queue')
    def test_large_batch_enqueues_high_queue(self, mock_get_queue, _mock_task, mock_grade):
        from unittest.mock import MagicMock
        mock_job = MagicMock(); mock_job.id = 'grade-job-1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue

        submission = self._submission_with_pending(AI_GRADE_ASYNC_THRESHOLD + 1)
        _trigger_ai_grading_for_submission(submission, request=None)

        mock_grade.assert_not_called()
        mock_get_queue.assert_called_once_with('high')
        mock_queue.enqueue.assert_called_once()

    @patch('taskqueue.services.enqueue_task')
    @patch('homework.views.grade_pending_answers')
    def test_no_pending_does_nothing(self, mock_grade, mock_enqueue):
        submission = self._submission_with_pending(0)
        _trigger_ai_grading_for_submission(submission, request=None)
        mock_grade.assert_not_called()
        mock_enqueue.assert_not_called()


class GradeSubmissionTaskTests(GradingTestBase):
    @patch('homework.views.grade_pending_answers')
    def test_task_invokes_shared_helper(self, mock_grade):
        from homework.tasks import grade_submission_answers
        submission = self._submission_with_pending(5)

        result = grade_submission_answers(submission.pk, self.school.pk)

        mock_grade.assert_called_once()
        # the submission passed to the helper matches
        called_submission = mock_grade.call_args[0][0]
        self.assertEqual(called_submission.pk, submission.pk)
        self.assertEqual(result['submission_id'], submission.pk)

    @patch('homework.views.grade_pending_answers')
    def test_task_handles_null_school(self, mock_grade):
        from homework.tasks import grade_submission_answers
        submission = self._submission_with_pending(5)
        grade_submission_answers(submission.pk, None)
        called_school = mock_grade.call_args[0][1]
        self.assertIsNone(called_school)
