"""The backfill that gives back marks all-or-nothing grading took off.

Grading a multi-value question gap by gap was fixed forward; every attempt
already recorded still said the child got nothing for a chart they had nearly
finished. ``backfill_partial_credit`` re-runs today's grader over the payload
each answer row already stores and awards the share they earned.

The rule these pin hardest is the one-directional one: a stored mark is never
lowered — not a row's points, not a submission's totals — because taking a mark
back from a child months later is not a decision a script makes on its own.
"""
import json
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from classroom.models import ClassRoom, Level, School, Subject, Topic
from homework.models import Homework, HomeworkStudentAnswer, HomeworkSubmission
from maths.models import Question
from worksheets.models import (
    Worksheet, WorksheetAssignment, WorksheetQuestion, WorksheetStudentAnswer,
    WorksheetSubmission,
)

User = get_user_model()

MONEY_SPEC = {
    'headers': ['Money value (¢)', 'Decimal form'],
    'rows': [
        [{'given': '56'}, {'answer': '0.56'}],
        [{'given': '84'}, {'answer': '0.84'}],
        [{'given': '7'}, {'answer': '0.07'}],
        [{'given': '96'}, {'answer': '0.96'}],
    ],
}
# Three of the four cells right — the reported case, in miniature.
THREE_OF_FOUR = json.dumps({'cells': {
    '0,1': '0.56', '1,1': '0.84', '2,1': '0.70', '3,1': '0.96'}})
ALL_FOUR = json.dumps({'cells': {
    '0,1': '0.56', '1,1': '0.84', '2,1': '0.07', '3,1': '0.96'}})
NONE_RIGHT = json.dumps({'cells': {
    '0,1': '9', '1,1': '9', '2,1': '9', '3,1': '9'}})


def _run(*args):
    out = StringIO()
    call_command('backfill_partial_credit', *args, stdout=out, stderr=out)
    return out.getvalue()


class BackfillPartialCreditTests(TestCase):

    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_user('bp_owner', 'bp_owner@x.com', 'p1!')
        cls.student = User.objects.create_user('bp_student', 'bp_s@x.com', 'p1!')
        cls.school = School.objects.create(
            name='Backfill School', slug='backfill-school', admin=cls.owner)
        cls.classroom = ClassRoom.objects.create(
            name='Backfill Class', school=cls.school)
        cls.level = Level.objects.get_or_create(
            level_number=969, defaults={'display_name': 'Backfill'})[0]
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', school=None, defaults={'name': 'Mathematics'})[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='Backfill Money',
            defaults={'slug': 'backfill-money'})[0]

    def _question(self, points=1):
        return Question.objects.create(
            level=self.level, topic=self.topic,
            question_text='Write the decimal form of each money value.',
            question_type=Question.TABLE_OF_VALUES,
            difficulty=1, points=points, table_spec=MONEY_SPEC,
        )

    # ── fixtures for each store ─────────────────────────────────────────

    def _worksheet_answer(self, question, payload=THREE_OF_FOUR, **row_kwargs):
        worksheet = Worksheet.objects.create(
            school=self.school, name='Backfill Worksheet',
            original_filename='', created_by=self.owner, question_count=1)
        WorksheetQuestion.objects.create(
            worksheet=worksheet, question=question, order=1,
            subject_slug='mathematics', content_id=question.pk)
        assignment = WorksheetAssignment.objects.create(
            worksheet=worksheet, classroom=self.classroom, assigned_by=self.owner)
        submission = WorksheetSubmission.objects.create(
            assignment=assignment, student=self.student, total_questions=1)
        defaults = dict(is_correct=False, points_earned=0.0, answer_data={})
        defaults.update(row_kwargs)
        return WorksheetStudentAnswer.objects.create(
            submission=submission, question=question,
            subject_slug='mathematics', content_id=question.pk,
            text_answer=payload, **defaults)

    def _homework_answer(self, question, payload=THREE_OF_FOUR, **row_kwargs):
        homework = Homework.objects.create(
            classroom=self.classroom, created_by=self.owner,
            title='Backfill Homework', homework_type='topic', num_questions=1,
            due_date=timezone.now() + timedelta(days=1))
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=self.student, total_questions=1,
            time_taken_seconds=60, score=0, points=0.0)
        defaults = dict(is_correct=False, points_earned=0.0, answer_data={})
        defaults.update(row_kwargs)
        return HomeworkStudentAnswer.objects.create(
            submission=submission, question=question,
            subject_slug='mathematics', content_id=question.pk,
            text_answer=payload, **defaults)

    # ── dry run ─────────────────────────────────────────────────────────

    def test_dry_run_reports_but_writes_nothing(self):
        row = self._worksheet_answer(self._question())
        out = _run()
        self.assertIn('3/4 cells right', out)
        self.assertIn('Dry run', out)
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 0.0)
        self.assertEqual(row.answer_data, {})

    # ── worksheets ──────────────────────────────────────────────────────

    def test_awards_the_share_the_student_earned(self):
        row = self._worksheet_answer(self._question())
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 0.75)
        self.assertFalse(row.is_correct)   # full marks still means every cell

    def test_stores_the_breakdown_so_the_review_page_can_explain_it(self):
        row = self._worksheet_answer(self._question())
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.answer_data['parts_correct'], 3)
        wrong = [p for p in row.answer_data['parts'] if not p['is_correct']]
        self.assertEqual(wrong[0]['label'], 'Decimal form for 7')
        self.assertEqual(wrong[0]['expected'], '0.07')

    def test_scales_with_the_questions_points(self):
        row = self._worksheet_answer(self._question(points=4))
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 3.0)

    def test_an_answer_now_fully_right_is_marked_correct_and_counted(self):
        row = self._worksheet_answer(self._question(), payload=ALL_FOUR)
        _run('--apply')
        row.refresh_from_db()
        row.submission.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, 1.0)
        self.assertEqual(row.submission.score, 1)

    def test_nothing_right_is_left_alone(self):
        row = self._worksheet_answer(self._question(), payload=NONE_RIGHT)
        out = _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 0.0)
        self.assertIn('No answer is owed', out)

    def test_a_payload_that_does_not_line_up_is_never_credited_on_a_guess(self):
        row = self._worksheet_answer(
            self._question(), payload='{"cells": "not a mapping"}')
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 0.0)

    def test_a_mark_is_never_lowered(self):
        # A row a teacher (or an earlier fix) already put above what gap-by-gap
        # marking says it is worth keeps every point of it.
        row = self._worksheet_answer(
            self._question(), points_earned=1.0, is_correct=True)
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 1.0)
        self.assertTrue(row.is_correct)

    def test_a_submission_score_above_its_rows_is_kept_and_reported(self):
        row = self._worksheet_answer(self._question())
        row.submission.score = 5      # higher than its one row justifies
        row.submission.save(update_fields=['score'])
        out = _run('--apply')
        row.submission.refresh_from_db()
        self.assertEqual(row.submission.score, 5)
        self.assertIn('Kept 5', out)

    # ── homework ────────────────────────────────────────────────────────

    def test_homework_row_and_submission_totals_move_together(self):
        row = self._homework_answer(self._question())
        _run('--apply')
        row.refresh_from_db()
        row.submission.refresh_from_db()
        self.assertEqual(row.points_earned, 0.75)
        # The submission's points are the speed-and-accuracy formula over the
        # credit earned — the same scale the submit path writes, so a partly
        # right chart lifts the total instead of resetting it to a sum of
        # points on a different scale.
        self.assertGreater(row.submission.points, 0)
        # The count of fully-correct questions has not moved: it never was one.
        self.assertEqual(row.submission.score, 0)

    def test_a_submission_graded_elsewhere_keeps_its_points_total(self):
        # Its points are the sum of per-answer points that AI/teacher grading
        # wrote — a different quantity from the submit formula. The row is
        # re-scored; the total is left as graded, and said out loud.
        row = self._homework_answer(self._question())
        row.submission.points = 2.5
        row.submission.save(update_fields=['points'])
        HomeworkStudentAnswer.objects.create(
            submission=row.submission, question=row.question,
            subject_slug='mathematics', content_id=999,
            text_answer='an essay', is_correct=False, points_earned=1.5,
            review_status=HomeworkStudentAnswer.REVIEW_AI_DONE)

        out = _run('--apply')

        row.refresh_from_db()
        row.submission.refresh_from_db()
        self.assertEqual(row.points_earned, 0.75)     # the row still gains
        self.assertEqual(row.submission.points, 2.5)  # the total is untouched
        self.assertIn('left as graded', out)

    def test_a_teacher_graded_row_is_left_to_the_teacher(self):
        row = self._homework_answer(
            self._question(),
            review_status=HomeworkStudentAnswer.REVIEW_TEACHER_DONE)
        _run('--apply')
        row.refresh_from_db()
        self.assertEqual(row.points_earned, 0.0)

    # ── scope, repeatability, honesty about what it can't reach ─────────

    def test_source_flag_limits_the_store(self):
        ws_row = self._worksheet_answer(self._question())
        hw_row = self._homework_answer(self._question())
        _run('--apply', '--source', 'worksheets')
        ws_row.refresh_from_db()
        hw_row.refresh_from_db()
        self.assertEqual(ws_row.points_earned, 0.75)
        self.assertEqual(hw_row.points_earned, 0.0)

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self._worksheet_answer(self._question())
        _run('--apply')
        out = _run('--apply')
        self.assertIn('No answer is owed', out)

    def test_it_says_what_it_could_not_reach(self):
        from maths.models import StudentAnswer
        question = self._question()
        self._worksheet_answer(question)
        StudentAnswer.objects.create(
            student=self.student, question=question, text_answer=THREE_OF_FOUR)
        out = _run()
        self.assertIn('quiz answer(s)', out)
        self.assertIn('NOT', out)
