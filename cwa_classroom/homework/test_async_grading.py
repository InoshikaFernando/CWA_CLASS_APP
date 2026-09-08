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

    @patch('homework.views.grade_pending_answers')
    @patch('taskqueue.services.django_rq.get_queue', side_effect=ConnectionError('redis down'))
    def test_enqueue_failure_falls_back_to_inline(self, _mock_queue, mock_grade):
        # Queue unavailable on a large batch → grade inline, don't raise.
        submission = self._submission_with_pending(AI_GRADE_ASYNC_THRESHOLD + 1)
        _trigger_ai_grading_for_submission(submission, request=None)
        mock_grade.assert_called_once()


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


class GradePendingAnswersFailureTests(GradingTestBase):
    """A failure is not a verdict — the answer stays pending for the teacher.

    ``grade_extended_answer`` returns ``is_correct: False, score 0.0`` when it
    could not grade at all (the API failed, the quota ran out, the question's
    diagram could not be loaded). Writing that to the student's record as
    "AI graded" marks a child wrong for something nobody marked, and hides the
    failure from the teacher's review screen.
    """

    def _submission_with_question(self):
        from classroom.models import Level, Subject, Topic
        from maths.models import Question
        subject = Subject.objects.get_or_create(
            slug='mathematics', school=None, defaults={'name': 'Mathematics'})[0]
        level = Level.objects.get_or_create(
            level_number=7, defaults={'display_name': 'Year 7'})[0]
        topic = Topic.objects.get_or_create(
            name='Angles HW', subject=subject,
            defaults={'slug': 'angles-hw', 'is_active': True})[0]
        question = Question.objects.create(
            question_text='Find angle x and explain.',
            question_type='extended_answer', topic=topic, level=level,
        )
        submission = HomeworkSubmission.objects.create(
            homework=self.homework, student=self.student,
            attempt_number=HomeworkSubmission.get_next_attempt_number(
                self.homework, self.student),
        )
        answer = HomeworkStudentAnswer.objects.create(
            submission=submission, content_id=question.pk, question=question,
            review_status=HomeworkStudentAnswer.REVIEW_PENDING_AI,
            text_answer='x is 40 degrees.',
        )
        return submission, answer

    @patch('worksheets.grading_service.grade_extended_answer')
    def test_ungradable_answer_stays_pending_with_the_reason(self, mock_grade):
        from homework.views import grade_pending_answers
        mock_grade.return_value = {
            'is_correct': False,
            'is_partial': False,
            'score_fraction': 0.0,
            'feedback': ("This question's diagram could not be loaded, so the "
                         'answer was not marked automatically.'),
            'cache_hit': False,
            'error': 'diagram unavailable: could not read diagram "x.png"',
        }
        submission, answer = self._submission_with_question()

        grade_pending_answers(submission, self.school)

        answer.refresh_from_db()
        self.assertEqual(answer.review_status,
                         HomeworkStudentAnswer.REVIEW_PENDING_AI)
        self.assertIn('diagram', answer.ai_feedback)
        self.assertEqual(answer.points_earned, 0)
        self.assertIsNone(answer.graded_at)

    @patch('worksheets.grading_service.grade_extended_answer')
    def test_a_real_verdict_still_grades(self, mock_grade):
        from homework.views import grade_pending_answers
        mock_grade.return_value = {
            'is_correct': True,
            'is_partial': False,
            'score_fraction': 1.0,
            'feedback': 'Correct.',
            'cache_hit': False,
        }
        submission, answer = self._submission_with_question()

        grade_pending_answers(submission, self.school)

        answer.refresh_from_db()
        self.assertEqual(answer.review_status,
                         HomeworkStudentAnswer.REVIEW_AI_DONE)
        self.assertTrue(answer.is_correct)
        self.assertIsNotNone(answer.graded_at)
