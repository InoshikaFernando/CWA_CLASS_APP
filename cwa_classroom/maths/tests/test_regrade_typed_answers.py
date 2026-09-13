"""Giving back marks the old grader took — regrade_typed_answers.

A student who typed "40, 36, 28" for a stored "40, 36, 28" was scored WRONG:
the old grader split the stored answer on commas and looked for a whole answer
equal to "40", or "36", or "28" (CPP-378). That was fixed going forward, and
every past attempt was left saying the child got it wrong — in their history,
their teacher's view, and the statistics built on top.

Proven on production, Q23576: the recorded text "40 ,36 ,28" was marked wrong
at the time and grades correct against today's rules.
"""
import uuid
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from classroom.models import ClassRoom, Level, School, Subject, Topic
from maths.models import (
    Answer, Question, StudentAnswer, StudentFinalAnswer,
)

User = get_user_model()


class RegradeTypedAnswersTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='regrade-student', password='pass1234',
            email='regrade@test.com')
        cls.school = School.objects.create(
            name='Regrade School', slug='regrade-school', admin=cls.student)
        cls.classroom = ClassRoom.objects.create(
            name='Regrade Class', code='RG01', school=cls.school)
        subject = Subject.objects.create(name='Mathematics', slug='maths-rg')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=subject, name='Number Patterns', slug='patterns-rg')

        # The production question, with its three alternative answers.
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text=('Work out the number pattern rule and complete the '
                           'pattern: 48, 44, __, __, 32, __.'),
            question_type=Question.SHORT_ANSWER, points=1,
        )
        for text in ('-4; 40, 36, 28', 'subtract 4; 40, 36, 28', '40, 36, 28'):
            Answer.objects.create(question=cls.question, answer_text=text,
                                  is_correct=True)

        # A question the grader still rejects — the control.
        cls.other = Question.objects.create(
            level=cls.level, topic=cls.topic, question_text='What is 2 + 2?',
            question_type=Question.SHORT_ANSWER, points=1,
        )
        Answer.objects.create(question=cls.other, answer_text='4', is_correct=True)

    def _answer(self, question, text, correct=False):
        return StudentAnswer.objects.create(
            student=self.student, question=question, text_answer=text,
            is_correct=correct, attempt_id=uuid.uuid4())

    def _run(self, *args):
        out = StringIO()
        call_command('regrade_typed_answers', *args, stdout=out, stderr=out)
        return out.getvalue()

    # ---------------------------------------------------------------- finding

    def test_it_finds_an_answer_the_grader_now_accepts(self):
        row = self._answer(self.question, '40 ,36 ,28')
        output = self._run()
        self.assertIn('Marked wrong, now grade correct : 1', output)
        self.assertIn(f'Q{self.question.id}', output)
        row.refresh_from_db()
        self.assertFalse(row.is_correct)      # dry run writes nothing

    def test_a_genuinely_wrong_answer_is_left_alone(self):
        self._answer(self.other, '5')
        output = self._run()
        self.assertIn('Nothing to correct', output)

    def test_an_answer_already_marked_right_is_untouched(self):
        """One direction only. A mark awarded is never taken back."""
        row = self._answer(self.question, 'nonsense', correct=True)
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)

    # ---------------------------------------------------------------- applying

    def test_apply_corrects_the_mark_and_awards_the_points(self):
        row = self._answer(self.question, '40 ,36 ,28')
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, self.question.points)

    def test_the_attempt_score_is_recounted(self):
        """Fixing the answer and leaving the total wrong is half a fix."""
        self._answer(self.question, '40 ,36 ,28')
        result = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=2, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': self.question.id, 'question': 'pattern',
                 'student_answer': '40 ,36 ,28', 'is_correct': False},
                {'id': self.other.id, 'question': '2+2',
                 'student_answer': '5', 'is_correct': False},
            ],
        )
        self._run('--apply')
        result.refresh_from_db()
        self.assertEqual(result.score, 1)          # the pattern one only
        self.assertGreater(result.points, 0)
        self.assertTrue(result.questions_data[0]['is_correct'])
        self.assertFalse(result.questions_data[1]['is_correct'])

    def test_it_is_idempotent(self):
        self._answer(self.question, '40 ,36 ,28')
        self._run('--apply')
        output = self._run('--apply')
        self.assertIn('Nothing to correct', output)

    def test_a_numeric_typed_answer_in_the_payload_is_read_not_crashed_on(self):
        """questions_data is JSON, so a bare number stays a number.

        Production carries attempts where student_answer is an int rather than
        a string — the quiz view wrote what it was given. Reading that as text
        is the command's job; falling over on it strands every other mark in
        the same run.
        """
        numeric = Question.objects.create(
            topic=self.topic, level=self.level, question_text='What is 2 + 2?',
            question_type='short_answer', answer_format='text', points=1,
        )
        Answer.objects.create(question=numeric, answer_text='4',
                              is_correct=True)
        self._answer(numeric, '4')
        result = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=1, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': numeric.id, 'question': 'What is 2 + 2?',
                 'student_answer': 4, 'is_correct': False},
            ],
        )
        self._run('--apply')
        result.refresh_from_db()
        self.assertEqual(result.score, 1)
        self.assertTrue(result.questions_data[0]['is_correct'])

    def test_zero_is_an_answer_not_a_blank(self):
        """`0` is falsy in Python and correct in maths."""
        zero = Question.objects.create(
            topic=self.topic, level=self.level, question_text='What is 5 - 5?',
            question_type='short_answer', answer_format='text', points=1,
        )
        Answer.objects.create(question=zero, answer_text='0', is_correct=True)
        self._answer(zero, '0')
        result = StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=1, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': zero.id, 'question': 'What is 5 - 5?',
                 'student_answer': 0, 'is_correct': False},
            ],
        )
        self._run('--apply')
        result.refresh_from_db()
        self.assertEqual(result.score, 1)
        self.assertTrue(result.questions_data[0]['is_correct'])

    def test_the_dry_run_projects_a_numeric_payload_without_crashing(self):
        """The dry run reads the same payload the apply path does.

        A missing answer and a non-text one sit alongside the numeric entry:
        neither is a typed answer, so both are skipped, and neither may take
        the run down with it.
        """
        numeric = Question.objects.create(
            topic=self.topic, level=self.level, question_text='What is 2 + 2?',
            question_type='short_answer', answer_format='text', points=1,
        )
        Answer.objects.create(question=numeric, answer_text='4',
                              is_correct=True)
        self._answer(numeric, '4')
        StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=3, time_taken_seconds=60, points=0.0,
            questions_data=[
                {'id': numeric.id, 'question': 'What is 2 + 2?',
                 'student_answer': 4, 'is_correct': False},
                {'id': numeric.id, 'question': 'What is 2 + 2?',
                 'student_answer': None, 'is_correct': False},
                {'id': numeric.id, 'question': 'What is 2 + 2?',
                 'student_answer': ['4'], 'is_correct': False},
            ],
        )
        output = self._run()
        self.assertIn('Marks before', output)
        self.assertIn('0/3 \u2192 1/3', output)      # the numeric entry only

    # ------------------------------------------------------------ out of scope

    def test_ai_and_teacher_graded_answers_are_never_re_rolled(self):
        """Re-running a model over old text is a re-roll, not a correction."""
        for validation in (Question.VALIDATION_AI, Question.VALIDATION_HUMAN):
            question = Question.objects.create(
                level=self.level, topic=self.topic,
                question_text=f'Explain your reasoning ({validation}).',
                question_type=Question.SHORT_ANSWER,
                validation_type=validation)
            Answer.objects.create(question=question, answer_text='because',
                                  is_correct=True)
            row = self._answer(question, 'because')
            self._run('--apply')
            row.refresh_from_db()
            self.assertFalse(row.is_correct, validation)

    def test_a_choice_question_is_not_touched(self):
        """Those grade from the row the student picked, and that has not changed."""
        question = Question.objects.create(
            level=self.level, topic=self.topic, question_text='Pick one',
            question_type=Question.MULTIPLE_CHOICE)
        Answer.objects.create(question=question, answer_text='40, 36, 28',
                              is_correct=True)
        row = self._answer(question, '40, 36, 28')
        self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    # --------------------------------------------------- homework & worksheets

    def _homework_answer(self, text, review=None):
        from homework.models import (
            Homework, HomeworkStudentAnswer, HomeworkSubmission,
        )
        homework = Homework.objects.create(
            classroom=self.classroom, title='Patterns homework',
            due_date=timezone.now() + timedelta(days=3),
            created_by=self.student)
        submission = HomeworkSubmission.objects.create(
            homework=homework, student=self.student,
            score=0, total_questions=1)
        return HomeworkStudentAnswer.objects.create(
            submission=submission, question=self.question, text_answer=text,
            is_correct=False, content_id=self.question.id,
            review_status=review or HomeworkStudentAnswer.REVIEW_AUTO,
        ), submission

    def _worksheet_answer(self, text):
        from worksheets.models import (
            Worksheet, WorksheetAssignment, WorksheetStudentAnswer,
            WorksheetSubmission,
        )
        worksheet = Worksheet.objects.create(
            school=self.school, name='Patterns worksheet',
            original_filename='patterns.pdf', created_by=self.student)
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
        row, submission = self._homework_answer('40 ,36 ,28')
        self._run('--apply')
        row.refresh_from_db()
        submission.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(submission.score, 1)

    def test_a_worksheet_answer_is_corrected_and_the_total_recounted(self):
        row, submission = self._worksheet_answer('40 ,36 ,28')
        self._run('--apply')
        row.refresh_from_db()
        submission.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(submission.score, 1)

    def test_a_teacher_or_ai_marked_homework_row_is_left_to_them(self):
        """review_status records who marked it. Not this command's to overwrite."""
        from homework.models import HomeworkStudentAnswer

        for review in (HomeworkStudentAnswer.REVIEW_AI_DONE,
                       HomeworkStudentAnswer.REVIEW_TEACHER_DONE,
                       HomeworkStudentAnswer.REVIEW_PENDING_TEACHER):
            row, _ = self._homework_answer('40 ,36 ,28', review=review)
            self._run('--apply')
            row.refresh_from_db()
            self.assertFalse(row.is_correct, review)

    def test_source_can_be_limited_to_one_store(self):
        quiz_row = self._answer(self.question, '40 ,36 ,28')
        hw_row, _ = self._homework_answer('40 ,36 ,28')
        self._run('--apply', '--source', 'quiz')
        quiz_row.refresh_from_db()
        hw_row.refresh_from_db()
        self.assertTrue(quiz_row.is_correct)
        self.assertFalse(hw_row.is_correct)

    # ------------------------------------------------------ before → after

    def test_the_dry_run_shows_the_mark_before_and_after(self):
        """A count of answers is not something a teacher or parent can act on.
        The mark it was, and the mark it becomes, is."""
        self._answer(self.question, '40 ,36 ,28')
        StudentFinalAnswer.objects.create(
            student=self.student, topic=self.topic, level=self.level,
            score=0, total_questions=2, time_taken_seconds=60,
            questions_data=[
                {'id': self.question.id, 'student_answer': '40 ,36 ,28',
                 'is_correct': False},
                {'id': self.other.id, 'student_answer': '5', 'is_correct': False},
            ],
        )
        output = self._run()
        self.assertIn('Marks before → after:', output)
        self.assertIn('0/2 → 1/2', output)
        self.assertIn('(+1)', output)

    def _consistent_homework(self, typed, already_right=2):
        """A submission whose stored score matches its answer rows."""
        from homework.models import HomeworkStudentAnswer

        row, submission = self._homework_answer(typed)
        for i in range(already_right):
            HomeworkStudentAnswer.objects.create(
                submission=submission, question=self.other,
                text_answer='4', is_correct=True, content_id=self.other.id + i,
                review_status=HomeworkStudentAnswer.REVIEW_AUTO)
        submission.total_questions = 5
        submission.score = already_right
        submission.save(update_fields=['total_questions', 'score'])
        return row, submission

    def test_the_homework_mark_before_and_after_is_shown(self):
        self._consistent_homework('40 ,36 ,28')
        self.assertIn('2/5 → 3/5', self._run())

    def test_the_projection_matches_what_apply_actually_writes(self):
        """The dry run is a promise. It has to be kept."""
        _row, submission = self._consistent_homework('40 ,36 ,28')
        self.assertIn('2/5 → 3/5', self._run())
        self._run('--apply')
        submission.refresh_from_db()
        self.assertEqual(submission.score, 3)

    def test_a_recount_never_takes_a_mark_away(self):
        """Where a stored score is higher than its rows justify, recounting
        would drop the child's mark. That is not what this was asked to do."""
        _row, submission = self._homework_answer('40 ,36 ,28')
        submission.total_questions = 5
        submission.score = 4          # higher than the one row can justify
        submission.save(update_fields=['total_questions', 'score'])
        output = self._run('--apply')
        submission.refresh_from_db()
        self.assertEqual(submission.score, 4)      # kept, not lowered
        self.assertIn('no mark taken away', output)
        self.assertIn('disagree', output)

    def test_scope_can_be_narrowed(self):
        self._answer(self.question, '40 ,36 ,28')
        output = self._run('--student', str(self.student.id + 999))
        self.assertIn('Nothing to correct', output)


class RegradeColumnArithmeticTests(TestCase):
    """The marks the quiz's missing column branch took.

    A column sum carries no Answer row — it is worked out from its operands —
    and the quiz had no branch for the type, so it fell into the answer-row
    fallback and scored every submission zero. 867 × 8 answered 6936 is
    recorded as wrong for every child who ever typed it. Their text is stored,
    so the marks can be given back.
    """

    @classmethod
    def setUpTestData(cls):
        cls.student = User.objects.create_user(
            username='column-regrade', password='pass1234',
            email='column-regrade@test.com')
        cls.school = School.objects.create(
            name='Column School', slug='column-school', admin=cls.student)
        cls.classroom = ClassRoom.objects.create(
            name='Column Class', code='CG01', school=cls.school)
        subject = Subject.objects.create(name='Mathematics', slug='maths-col')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(
            subject=subject, name='Multiplication', slug='multiplication-col')

        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Work out 867 × 8 using column multiplication.',
            question_type=Question.COLUMN_OPERATION,
            operands=[867, 8], operator='*', points=1,
        )
        cls.division = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Work out 872 ÷ 4 using long division.',
            question_type=Question.LONG_DIVISION,
            dividend=872, divisor=4, points=1,
        )

    def _quiz_answer(self, question, text):
        return StudentAnswer.objects.create(
            student=self.student, question=question, text_answer=text,
            is_correct=False, attempt_id=uuid.uuid4())

    def _run(self, *args):
        out = StringIO()
        call_command('regrade_typed_answers', *args, stdout=out, stderr=out)
        return out.getvalue()

    def test_the_reported_answer_gets_its_mark_back(self):
        row = self._quiz_answer(self.question, '6936')
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)
        self.assertEqual(row.points_earned, self.question.points)

    def test_a_genuinely_wrong_product_keeps_its_mark(self):
        row = self._quiz_answer(self.question, '6836')
        self._run('--apply')
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    def test_a_long_division_spelled_without_spaces_is_owed_too(self):
        row = self._quiz_answer(self.division, '218r0')
        self._run('--apply')
        row.refresh_from_db()
        self.assertTrue(row.is_correct)

    def test_the_dry_run_names_the_question_and_changes_nothing(self):
        row = self._quiz_answer(self.question, '6936')
        output = self._run()
        self.assertIn('867', output)
        self.assertIn('Dry run', output)
        row.refresh_from_db()
        self.assertFalse(row.is_correct)

    def test_the_homework_and_worksheet_stores_are_swept_as_well(self):
        """Both graded column sums from the numbers all along, so they should
        come back clean — but they are swept rather than assumed clean, which
        is the point of running this over all three stores."""
        from datetime import timedelta

        from django.utils import timezone

        from homework.models import (
            Homework, HomeworkStudentAnswer, HomeworkSubmission,
        )
        from worksheets.models import (
            Worksheet, WorksheetAssignment, WorksheetStudentAnswer,
            WorksheetSubmission,
        )

        homework = Homework.objects.create(
            classroom=self.classroom, title='Column homework',
            due_date=timezone.now() + timedelta(days=3),
            created_by=self.student)
        hw_submission = HomeworkSubmission.objects.create(
            homework=homework, student=self.student, score=0,
            total_questions=1)
        hw_row = HomeworkStudentAnswer.objects.create(
            submission=hw_submission, question=self.question,
            text_answer='6936', is_correct=False,
            content_id=self.question.id,
            review_status=HomeworkStudentAnswer.REVIEW_AUTO,
        )

        worksheet = Worksheet.objects.create(
            school=self.school, name='Column worksheet',
            original_filename='column.pdf', created_by=self.student)
        assignment = WorksheetAssignment.objects.create(
            worksheet=worksheet, classroom=self.classroom)
        ws_submission = WorksheetSubmission.objects.create(
            assignment=assignment, student=self.student, score=0,
            total_questions=1)
        ws_row = WorksheetStudentAnswer.objects.create(
            submission=ws_submission, question=self.division,
            text_answer='218r0', is_correct=False,
            content_id=self.division.id,
        )

        self._run('--apply')
        hw_row.refresh_from_db()
        ws_row.refresh_from_db()
        hw_submission.refresh_from_db()
        ws_submission.refresh_from_db()
        self.assertTrue(hw_row.is_correct)
        self.assertEqual(hw_submission.score, 1)
        # "218r0" was refused by the worksheet's own long-division grader
        # before the three surfaces shared one.
        self.assertTrue(ws_row.is_correct)
        self.assertEqual(ws_submission.score, 1)

    def test_a_column_question_missing_its_numbers_is_left_to_its_answer_rows(self):
        broken = Question.objects.create(
            level=self.level, topic=self.topic,
            question_text='Work out the product.',
            question_type=Question.COLUMN_OPERATION, points=1,
        )
        Answer.objects.create(question=broken, answer_text='6936',
                              is_correct=True)
        owed = self._quiz_answer(broken, '6936')
        wrong = self._quiz_answer(broken, '6836')
        self._run('--apply')
        owed.refresh_from_db()
        wrong.refresh_from_db()
        self.assertTrue(owed.is_correct)
        self.assertFalse(wrong.is_correct)
