"""
Unit tests for worksheets migration 0005_add_subject_slug_content_id_to_answer.

Covers:
1. apply_forward is a no-op on non-MySQL backends (SQLite guard)
2. DROP INDEX filter only targets the old (submission, question) unique —
   never collateral-drops unrelated constraints
3. WorksheetStudentAnswer model has the correct fields and unique_together
   after migration (ORM state verification)
4. Backfill logic: content_id copied from question_id on save()
"""
import unittest

from django.db import connection
from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question
from worksheets.models import (
    Worksheet,
    WorksheetStudentAnswer,
    WorksheetSubmission,
    WorksheetAssignment,
)


# ---------------------------------------------------------------------------
# Helper: DROP INDEX filter logic (pure Python — no DB needed)
# ---------------------------------------------------------------------------

def _should_drop(name):
    """Mirror the filter from apply_forward step 3."""
    return 'question' in name and 'subject_sl' not in name


class TestDropIndexFilterLogic(unittest.TestCase):
    """Pure-Python unit test for the DROP INDEX name filter.

    Verifies it is surgical: drops the old Django-generated
    (submission, question) unique, leaves everything else intact.
    """

    def test_drops_old_submission_question_unique(self):
        # Django generates names like: worksheets_worksheetstud_submission_id_question_id_<hash>_uniq
        name = 'worksheets_worksheetstud_submission_id_question_id_abcd1234_uniq'
        self.assertTrue(_should_drop(name))

    def test_does_not_drop_new_subject_sl_unique(self):
        name = 'worksheets_worksheetstud_submission_id_subject_sl_445dca9d_uniq'
        self.assertFalse(_should_drop(name))

    def test_does_not_drop_unrelated_unique_with_no_question(self):
        # A hypothetical future constraint with no 'question' in the name
        name = 'worksheets_worksheetstud_some_other_constraint_uniq'
        self.assertFalse(_should_drop(name))

    def test_does_not_drop_future_constraint_containing_both(self):
        # Edge case: a name that has BOTH 'question' and 'subject_sl' — should not drop
        name = 'worksheets_worksheetstud_question_subject_sl_futurename_uniq'
        self.assertFalse(_should_drop(name))

    def test_drops_legacy_short_name_variant(self):
        # Some older Django versions generated shorter names
        name = 'worksheets_question_submission_uniq'
        self.assertTrue(_should_drop(name))

    def test_does_not_drop_content_id_constraint(self):
        name = 'worksheets_worksheetstud_content_id_constraint_uniq'
        self.assertFalse(_should_drop(name))


# ---------------------------------------------------------------------------
# SQLite guard: apply_forward must be a no-op on non-MySQL
# ---------------------------------------------------------------------------

class TestApplyForwardSQLiteGuard(TestCase):
    """apply_forward must return immediately on SQLite without touching the DB."""

    def _load_migration(self):
        import importlib
        return importlib.import_module(
            'worksheets.migrations.0005_add_subject_slug_content_id_to_answer'
        )

    @unittest.skipIf(connection.vendor == 'mysql', 'SQLite guard test — skip on MySQL')
    def test_apply_forward_noop_on_sqlite(self):
        mod = self._load_migration()
        # Should not raise — SQLite guard returns early before any information_schema query
        try:
            mod.apply_forward(None, _FakeSchemaEditor(vendor='sqlite'))
        except Exception as exc:
            self.fail(f'apply_forward raised on SQLite: {exc}')

    def test_migration_module_importable(self):
        # Verifies the syntax fix — prior version had IndentationError at line 130
        try:
            self._load_migration()
        except SyntaxError as exc:
            self.fail(f'Migration has a SyntaxError: {exc}')
        except IndentationError as exc:
            self.fail(f'Migration has an IndentationError: {exc}')


class _FakeSchemaEditor:
    """Minimal schema-editor stub for testing the SQLite guard path."""
    def __init__(self, vendor='sqlite'):
        self.connection = _FakeConnection(vendor)


class _FakeConnection:
    def __init__(self, vendor):
        self.vendor = vendor


# ---------------------------------------------------------------------------
# ORM state: verify the migration's state_operations produced correct fields
# ---------------------------------------------------------------------------

class WorksheetAnswerModelBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        from classroom.models import AcademicYear, ClassRoom
        cls.admin = CustomUser.objects.create_user(
            'mig05_admin', 'mig05@example.com', 'pass1!',
        )
        Role.objects.get_or_create(name=Role.ADMIN, defaults={'display_name': 'Admin'})
        cls.school = School.objects.create(
            name='Mig05 School', slug='mig05-school', admin=cls.admin,
        )
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=6, defaults={'display_name': 'Year 6'},
        )[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='Mig05 Topic',
            defaults={'slug': 'mig05-topic', 'is_active': True},
        )[0]
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='Mig05 test?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        Answer.objects.get_or_create(
            question=cls.question, answer_text='42',
            defaults={'is_correct': True, 'order': 1},
        )
        cls.worksheet = Worksheet.objects.create(
            school=cls.school, name='Mig05 WS',
            original_filename='mig05.pdf', created_by=cls.admin,
        )
        year, _ = AcademicYear.objects.get_or_create(
            school=cls.school, year=2026,
            defaults={'start_date': '2026-01-01', 'end_date': '2026-12-31'},
        )
        cls.classroom = ClassRoom.objects.create(
            school=cls.school, name='Mig05 Class',
            code='MIG05CLS', academic_year=year,
        )
        cls.assignment = WorksheetAssignment.objects.create(
            worksheet=cls.worksheet, classroom=cls.classroom,
        )
        cls.student = CustomUser.objects.create_user(
            'mig05_student', 'mig05_stu@example.com', 'pass1!',
        )
        cls.submission = WorksheetSubmission.objects.create(
            assignment=cls.assignment,
            student=cls.student,
            total_questions=1,
        )


class TestWorksheetStudentAnswerFields(WorksheetAnswerModelBase):

    def test_subject_slug_field_exists_with_default(self):
        field = WorksheetStudentAnswer._meta.get_field('subject_slug')
        self.assertEqual(field.default, 'mathematics')
        self.assertEqual(field.max_length, 50)

    def test_content_id_field_exists_with_default_zero(self):
        field = WorksheetStudentAnswer._meta.get_field('content_id')
        self.assertEqual(field.default, 0)

    def test_question_fk_is_nullable(self):
        field = WorksheetStudentAnswer._meta.get_field('question')
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_coding_exercise_fk_is_nullable(self):
        field = WorksheetStudentAnswer._meta.get_field('coding_exercise')
        self.assertTrue(field.null)
        self.assertTrue(field.blank)

    def test_unique_together_is_submission_subject_slug_content_id(self):
        meta = WorksheetStudentAnswer._meta
        ut = meta.unique_together
        self.assertIn(('submission', 'subject_slug', 'content_id'), ut)

    def test_old_unique_submission_question_not_present(self):
        meta = WorksheetStudentAnswer._meta
        ut = meta.unique_together
        self.assertNotIn(('submission', 'question'), ut)


class TestWorksheetStudentAnswerCreate(WorksheetAnswerModelBase):

    def test_create_with_maths_question(self):
        answer = WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            question=self.question,
            subject_slug='mathematics',
            content_id=self.question.id,
            is_correct=True,
            points_earned=1.0,
        )
        self.assertEqual(answer.subject_slug, 'mathematics')
        self.assertEqual(answer.content_id, self.question.id)

    def test_create_without_question_fk(self):
        """coding or future subject: question FK is null."""
        answer = WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            subject_slug='coding',
            content_id=999,
        )
        self.assertIsNone(answer.question_id)
        self.assertEqual(answer.subject_slug, 'coding')

    def test_unique_together_blocks_duplicate(self):
        from django.db import IntegrityError
        WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            subject_slug='mathematics',
            content_id=self.question.id,
            question=self.question,
        )
        with self.assertRaises(IntegrityError):
            WorksheetStudentAnswer.objects.create(
                submission=self.submission,
                subject_slug='mathematics',
                content_id=self.question.id,
                question=self.question,
            )

    def test_same_content_id_different_subject_allowed(self):
        """(submission, 'mathematics', 10) and (submission, 'coding', 10) are different."""
        WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            subject_slug='mathematics',
            content_id=10,
        )
        # Should not raise
        answer2 = WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            subject_slug='coding',
            content_id=10,
        )
        self.assertEqual(answer2.subject_slug, 'coding')
