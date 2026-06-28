"""Unit tests for classroom.progress_summary (per-student report/dashboard aggregates)."""

import datetime

from django.utils import timezone

from classroom.models import Topic
from classroom.progress_summary import (
    homework_summary, maths_summary, coding_summary, build_summary,
)
from homework.models import Homework, HomeworkSubmission
from maths.models import StudentFinalAnswer

from .test_e2e_attendance_progress import _BaseAttendanceProgressTest


class ProgressSummaryTest(_BaseAttendanceProgressTest):
    """Homework (class-scoped) + Maths/Coding (platform-wide) summaries."""

    def _homework(self, title, published=True):
        # Homework.save() auto-publishes when both publish_at and published_at are
        # None, so an unpublished one needs a future publish_at (scheduled).
        return Homework.objects.create(
            classroom=self.classroom,
            created_by=self.teacher_user,
            title=title,
            due_date=timezone.now() + datetime.timedelta(days=7),
            published_at=timezone.now() if published else None,
            publish_at=None if published else timezone.now() + datetime.timedelta(days=3),
        )

    # ----- Homework -----------------------------------------------------

    def test_homework_zero_state(self):
        s = homework_summary(self.student_user, self.classroom)
        self.assertEqual(
            s, {'assigned': 0, 'completed': 0, 'completion_pct': 0, 'average_pct': 0},
        )

    def test_homework_completion_and_average(self):
        hw1 = self._homework('HW1')
        self._homework('HW2')                 # assigned, never submitted
        self._homework('Draft', published=False)  # unpublished → not assigned

        HomeworkSubmission.objects.create(
            homework=hw1, student=self.student_user,
            score=8, total_questions=10, points=80.0,
        )
        s = homework_summary(self.student_user, self.classroom)
        self.assertEqual(s['assigned'], 2)        # the two published ones
        self.assertEqual(s['completed'], 1)
        self.assertEqual(s['completion_pct'], 50)
        self.assertEqual(s['average_pct'], 80)    # best submission of HW1

    def test_homework_uses_best_attempt(self):
        hw = self._homework('HW')
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student_user, attempt_number=1,
            score=4, total_questions=10, points=40.0,
        )
        HomeworkSubmission.objects.create(
            homework=hw, student=self.student_user, attempt_number=2,
            score=9, total_questions=10, points=90.0,
        )
        s = homework_summary(self.student_user, self.classroom)
        self.assertEqual(s['average_pct'], 90)    # best, not latest/first

    # ----- Maths --------------------------------------------------------

    def test_maths_zero_state(self):
        self.assertEqual(
            maths_summary(self.student_user),
            {'topics_attempted': 0, 'average_pct': 0, 'basic_facts_levels': 0},
        )

    def test_maths_counts_best_per_topic_level(self):
        topic = Topic.objects.create(subject=self.subject, name='Algebra')
        StudentFinalAnswer.objects.create(
            student=self.student_user, topic=topic, level=self.level,
            quiz_type='topic', attempt_number=1,
            score=6, total_questions=10, points=60.0,
        )
        StudentFinalAnswer.objects.create(
            student=self.student_user, topic=topic, level=self.level,
            quiz_type='topic', attempt_number=2,
            score=9, total_questions=10, points=90.0,
        )
        s = maths_summary(self.student_user)
        self.assertEqual(s['topics_attempted'], 1)   # same topic-level collapses
        self.assertEqual(s['average_pct'], 90)       # best attempt

    # ----- Coding (zero-state: validates queries against fresh schema) --

    def test_coding_zero_state(self):
        self.assertEqual(
            coding_summary(self.student_user),
            {'exercises_completed': 0, 'problems_solved': 0},
        )

    # ----- Bundle -------------------------------------------------------

    def test_build_summary_respects_flags(self):
        full = build_summary(self.student_user, self.classroom)
        self.assertEqual(set(full), {'homework', 'maths', 'coding'})

        partial = build_summary(
            self.student_user, self.classroom,
            homework=True, maths=False, coding=False,
        )
        self.assertEqual(set(partial), {'homework'})

    def test_build_summary_skips_homework_without_class(self):
        out = build_summary(self.student_user, None)
        self.assertNotIn('homework', out)
        self.assertEqual(set(out), {'maths', 'coding'})
