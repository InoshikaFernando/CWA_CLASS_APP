"""Giving back the marks a broken inequality key took — regrade_number_line_answers.

The reported pair: a student graphed ``k <= -2`` by marking -7 -6 -5 -4 -3 -2 and
``m > 1`` by marking 2 3 4 5 6 7, and both correct answers were marked wrong
because the stored key stopped one tick short. Repairing the question fixes it
for everyone from that moment on; it does not move the marks already recorded —
in the child's history, their teacher's view, or the statistics built on top.

These pin what the regrade gives back, what it refuses to touch, and — the part
that matters most — that it never takes a mark away from a child.
"""
import json
import uuid
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from classroom.models import ClassRoom, Level, School, Subject, Topic
from maths.models import Answer, Question, StudentAnswer, StudentFinalAnswer

User = get_user_model()

LINE = {'min': -7, 'max': 7, 'step': 1, 'mode': 'mark'}
# What the student marked for "k <= -2" — right, and marked wrong at the time.
RAY = json.dumps({'marks': [-2, -3, -4, -5, -6, -7]})
# The same graph with the boundary tick left off: what the BROKEN key accepted.
SHORT_RAY = json.dumps({'marks': [-7, -6, -5, -4, -3]})


class RegradeNumberLineAnswersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='nl-regrade-student', password='pass1234',
            email='nl-regrade@test.com')
        cls.school = School.objects.create(
            name='NL Regrade School', slug='nl-regrade-school', admin=cls.student)
        cls.classroom = ClassRoom.objects.create(
            name='NL Regrade Class', code='NLR1', school=cls.school)
        subject = Subject.objects.create(name='Mathematics', slug='maths-nlr')
        cls.level = Level.objects.create(level_number=9, display_name='Year 9')
        cls.topic = Topic.objects.create(
            subject=subject, name='Inequalities', slug='inequalities-nlr')

        # The reported question, after repair_number_line_inequalities ran: the
        # key is now derived from the inequality the question states.
        cls.question = cls._number_line(
            'Draw a graph for the inequality k <= -2.',
            dict(LINE, inequality={'op': '<=', 'value': -2},
                 target=[-7, -6, -5, -4, -3, -2]))
        # A number-line question that was never an inequality graph — its key
        # was hand-listed and nothing about it was corrected.
        cls.plain = cls._number_line(
            'Mark 2 and 5 on the number line.',
            {'min': -3, 'max': 7, 'step': 1, 'mode': 'mark', 'target': [2, 5]})

    @classmethod
    def _number_line(cls, text, spec):
        return Question.objects.create(
            level=cls.level, topic=cls.topic, question_text=text,
            question_type=Question.NUMBER_LINE, difficulty=1, points=1,
            number_line_spec=spec)

    def _answer(self, question, text, correct=False):
        return StudentAnswer.objects.create(
            student=self.student, question=question, text_answer=text,
            is_correct=correct, attempt_id=uuid.uuid4())

    def _run(self, *args):
        out = StringIO()
        call_command('regrade_number_line_answers', *args, stdout=out, stderr=out)
        return out.getvalue()

    # ---------------------------------------------------------------- finding

    def test_it_finds_the_reported_answer(self):
        row = self._answer(self.question, RAY)
        output = self._run()
        self.assertIn('Marked wrong, now grade correct : 1', output)
        self.assertIn(f'Q{self.question.id}', output)
        self.assertIn('key now <= -2', output)
        row.refresh_from_db()
        self.assertFalse(row.is_correct)          # dry run writes nothing

    def test_apply_corrects_the_mark_and_awards_the_points(self):
        row = self._answer(self.question, RAY)
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, self.question.points)

    def test_a_genuinely_wrong_graph_is_left_alone(self):
        row = self._answer(self.question, json.dumps({'marks': [0, 1, 2]}))
        self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    def test_a_blank_or_malformed_payload_is_left_alone(self):
        rows = [self._answer(self.question, payload)
                for payload in ('not json', '{"marks": []}', '{}')]
        self._run('--apply')
        for row in rows:
            row.refresh_from_db()
            self.assertFalse(row.is_correct)

    def test_it_is_idempotent(self):
        self._answer(self.question, RAY)
        self._run('--apply')
        output = self._run('--apply')
        self.assertIn('Nothing to correct', output)

    # ------------------------------------------------- never takes marks away

    def test_a_mark_earned_under_the_broken_key_is_kept(self):
        """The other side of the repair, and the one that must not bite.

        Under the old key, the graph that LEFT OUT the boundary tick was marked
        right. The repaired key says otherwise — but that is the misprint's
        doing, not the child's, and this command only ever moves wrong to right.
        """
        row = self._answer(self.question, SHORT_RAY, correct=True)
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)

    def test_a_wrong_mark_the_new_key_still_rejects_stays_wrong(self):
        row = self._answer(self.question, SHORT_RAY, correct=False)
        self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    # ------------------------------------------------------------- what's out

    def test_a_hand_listed_number_line_question_is_not_swept(self):
        """Its key was never derived, so a mismatch means someone EDITED the
        question — and the child answered the one they were shown."""
        self.plain.number_line_spec = dict(self.plain.number_line_spec,
                                           target=[2, 5, 6])
        self.plain.save(update_fields=['number_line_spec'])
        row = self._answer(self.plain, json.dumps({'marks': [2, 5, 6]}))
        output = self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)
        self.assertIn('Nothing to correct', output)

    def test_other_question_types_are_not_swept(self):
        calculation = Question.objects.create(
            level=self.level, topic=self.topic, difficulty=1, points=1,
            question_text='Solve for x when x + 3 > 5.',
            question_type=Question.CALCULATION)
        Answer.objects.create(question=calculation, answer_text='x > 2',
                              is_correct=True)
        row = self._answer(calculation, 'x > 2')
        output = self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)
        self.assertIn('Nothing to correct', output)

    def test_a_read_mode_question_is_not_swept(self):
        read = self._number_line(
            'What value does the arrow point to?',
            {'min': 0, 'max': 10, 'step': 2, 'mode': 'read', 'given': [6]})
        row = self._answer(read, '6')
        self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    def test_scope_can_be_narrowed(self):
        other = self._number_line(
            'Draw a graph for the inequality m > 1.',
            dict(LINE, inequality={'op': '>', 'value': 1}))
        mine = self._answer(self.question, RAY)
        theirs = self._answer(other, json.dumps({'marks': [2, 3, 4, 5, 6, 7]}))
        self._run('--question', str(self.question.id), '--apply')
        mine.refresh_from_db()
        theirs.refresh_from_db()
        self.assertTrue(mine.is_correct)
        self.assertFalse(theirs.is_correct)

    def test_source_can_be_limited_to_one_store(self):
        row = self._answer(self.question, RAY)
        output = self._run('--source', 'homework')
        self.assertNotIn('quiz  ', output)
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    # ------------------------------------------------------------- aggregates

    def test_the_attempt_score_and_payload_are_recounted(self):
        """Fixing the answer and leaving the total wrong is half a fix."""
        self._answer(self.question, RAY)
        result = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=2, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': self.question.id, 'question': 'k <= -2',
                 'student_answer': RAY, 'is_correct': False},
                {'id': self.plain.id, 'question': 'mark 2 and 5',
                 'student_answer': json.dumps({'marks': [2]}), 'is_correct': False},
            ],
        )
        self._run('--apply')
        result.refresh_from_db()
        self.assertEqual(result.score, 1)          # the inequality one only
        self.assertGreater(result.points, 0)
        self.assertTrue(result.questions_data[0]['is_correct'])
        self.assertFalse(result.questions_data[1]['is_correct'])

    def test_an_attempt_score_is_recounted_from_its_payload(self):
        """Pinned because it is the one place a total can go DOWN.

        An attempt has no record of itself but the review payload, so the score
        is recounted from it. Where the two already disagreed — a stored 5 over
        a payload showing one correct answer — the payload wins and the score
        drops. Longstanding behaviour of the typed regrade, inherited here, and
        pinned so it is a documented edge rather than a surprise to a teacher.
        """
        self._answer(self.question, RAY)
        result = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=5, total_questions=6, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': self.question.id, 'question': 'k <= -2',
                 'student_answer': RAY, 'is_correct': False},
            ],
        )
        self._run('--apply')
        result.refresh_from_db()
        self.assertEqual(result.score, 1)

    def test_the_dry_run_shows_the_mark_before_and_after(self):
        self._answer(self.question, RAY)
        StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=3, total_questions=5, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': self.question.id, 'question': 'k <= -2',
                 'student_answer': RAY, 'is_correct': False},
            ],
        )
        output = self._run()
        self.assertIn('Marks before → after:', output)
        self.assertIn('3/5 → 4/5', output)

    # --------------------------------------------------- homework & worksheets

    def _homework_answer(self, text, question=None, review=None):
        from homework.models import (
            Homework, HomeworkStudentAnswer, HomeworkSubmission,
        )
        question = question or self.question
        homework = Homework.objects.create(
            classroom=self.classroom, title='Inequalities homework',
            due_date=timezone.now() + timedelta(days=3),
            created_by=self.student)
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=self.student, score=0, total_questions=1)
        return HomeworkStudentAnswer.objects.create(
            submission=submission, question=question, text_answer=text,
            is_correct=False, content_id=question.id,
            review_status=review or HomeworkStudentAnswer.REVIEW_AUTO,
        ), submission

    def _worksheet_answer(self, text):
        from worksheets.models import (
            Worksheet, WorksheetAssignment, WorksheetStudentAnswer,
            WorksheetSubmission,
        )
        worksheet = Worksheet.objects.create(
            school=self.school, name='Inequalities worksheet',
            original_filename='inequalities.pdf', created_by=self.student)
        assignment = WorksheetAssignment.objects.create(
            worksheet=worksheet, classroom=self.classroom)
        submission = WorksheetSubmission.objects.create(
            assignment=assignment, student=self.student,
            score=0, total_questions=1)
        return WorksheetStudentAnswer.objects.create(
            submission=submission, question=self.question, text_answer=text,
            is_correct=False, content_id=self.question.id,
        ), submission

    def test_a_homework_answer_is_corrected_and_the_total_recounted(self):
        row, submission = self._homework_answer(RAY)
        self._run('--apply')
        row.refresh_from_db()
        submission.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(submission.score, 1)

    def test_a_worksheet_answer_is_corrected_and_the_total_recounted(self):
        row, submission = self._worksheet_answer(RAY)
        self._run('--apply')
        row.refresh_from_db()
        submission.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(submission.score, 1)

    def test_a_teacher_or_ai_marked_homework_row_is_left_to_them(self):
        from homework.models import HomeworkStudentAnswer

        for review in (HomeworkStudentAnswer.REVIEW_AI_DONE,
                       HomeworkStudentAnswer.REVIEW_TEACHER_DONE,
                       HomeworkStudentAnswer.REVIEW_PENDING_TEACHER):
            row, _ = self._homework_answer(RAY, review=review)
            self._run('--apply')
            row.refresh_from_db()
            self.assertFalse(row.is_correct, review)

    def test_a_recount_never_takes_a_mark_away(self):
        """A stored score higher than its rows justify stands, and is reported."""
        row, submission = self._worksheet_answer(RAY)
        submission.score = 5
        submission.save(update_fields=['score'])
        output = self._run('--apply')
        submission.refresh_from_db()
        self.assertEqual(submission.score, 5)
        self.assertIn('no mark taken', output)

    # ------------------------------------------------- the two halves together

    def test_repair_then_regrade_gives_the_reported_marks_back(self):
        """End to end on the reported data, in the order the runbook gives."""
        broken = self._number_line(
            'Draw a graph for the inequality m > 1.',
            dict(LINE, target=[2, 3, 4, 5, 6]))
        row = self._answer(broken, json.dumps({'marks': [2, 3, 4, 5, 6, 7]}))

        # Before either command: the question is wrong and so is the mark.
        self.assertIn('Nothing to correct', self._run('--apply'))
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

        call_command('repair_number_line_inequalities', '--apply',
                     stdout=StringIO(), stderr=StringIO())
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
