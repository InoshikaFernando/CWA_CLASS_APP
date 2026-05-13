"""
Unit tests for CPP-276: WorksheetQuestion subject_slug/content_id fields
and WorksheetStudentAnswer.answer_data field.

Run with:
    pytest worksheets/tests/test_models.py -v
"""
from django.db import IntegrityError
from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import Level, School, Subject, Topic
from maths.models import Answer, Question
from worksheets.models import (
    Worksheet,
    WorksheetQuestion,
    WorksheetStudentAnswer,
    WorksheetAssignment,
    WorksheetSubmission,
)


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

class WorksheetModelTestBase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = CustomUser.objects.create_user(
            'ws_admin', 'ws_admin@example.com', 'pass1!',
        )
        admin_role, _ = Role.objects.get_or_create(
            name=Role.ADMIN, defaults={'display_name': 'Admin'},
        )
        cls.admin.roles.add(admin_role)

        cls.school = School.objects.create(
            name='WS Test School', slug='ws-test-school', admin=cls.admin,
        )
        cls.subject = Subject.objects.get_or_create(
            slug='mathematics', defaults={'name': 'Mathematics', 'is_active': True},
        )[0]
        cls.level = Level.objects.get_or_create(
            level_number=5, defaults={'display_name': 'Year 5'},
        )[0]
        cls.topic = Topic.objects.get_or_create(
            subject=cls.subject, name='WS Algebra',
            defaults={'slug': 'ws-algebra', 'is_active': True},
        )[0]
        cls.question = Question.objects.create(
            level=cls.level, topic=cls.topic,
            question_text='What is 2 + 2?',
            question_type='multiple_choice', difficulty=1, points=1,
        )
        Answer.objects.get_or_create(
            question=cls.question, answer_text='4',
            defaults={'is_correct': True, 'order': 1},
        )
        cls.worksheet = Worksheet.objects.create(
            school=cls.school,
            name='Test Worksheet',
            original_filename='test.pdf',
            created_by=cls.admin,
        )


# ---------------------------------------------------------------------------
# WorksheetQuestion field defaults
# ---------------------------------------------------------------------------

class TestWorksheetQuestionDefaults(WorksheetModelTestBase):
    def test_worksheet_question_subject_slug_defaults_to_mathematics(self):
        wq = WorksheetQuestion.objects.create(
            worksheet=self.worksheet,
            question=self.question,
            order=1,
        )
        self.assertEqual(wq.subject_slug, 'mathematics')

    def test_worksheet_question_content_id_defaults_to_zero(self):
        wq = WorksheetQuestion.objects.create(
            worksheet=self.worksheet,
            question=self.question,
            order=1,
        )
        self.assertEqual(wq.content_id, 0)

    def test_worksheet_question_subject_slug_and_content_id_explicit(self):
        wq = WorksheetQuestion.objects.create(
            worksheet=self.worksheet,
            question=self.question,
            order=1,
            subject_slug='mathematics',
            content_id=self.question.id,
        )
        self.assertEqual(wq.subject_slug, 'mathematics')
        self.assertEqual(wq.content_id, self.question.id)


# ---------------------------------------------------------------------------
# WorksheetQuestion unique constraints
# ---------------------------------------------------------------------------

class TestWorksheetQuestionConstraints(WorksheetModelTestBase):
    def test_unique_order_constraint_raises_on_duplicate(self):
        WorksheetQuestion.objects.create(
            worksheet=self.worksheet, question=self.question,
            order=1, content_id=self.question.id,
        )
        with self.assertRaises(IntegrityError):
            WorksheetQuestion.objects.create(
                worksheet=self.worksheet, question=self.question,
                order=1, content_id=self.question.id,
            )

    def test_unique_content_constraint_raises_on_duplicate(self):
        WorksheetQuestion.objects.create(
            worksheet=self.worksheet, question=self.question,
            order=1, subject_slug='mathematics', content_id=self.question.id,
        )
        with self.assertRaises(IntegrityError):
            # Same (worksheet, subject_slug, content_id) — different order
            WorksheetQuestion.objects.create(
                worksheet=self.worksheet, question=self.question,
                order=2, subject_slug='mathematics', content_id=self.question.id,
            )

    def test_same_content_id_different_subjects_allowed(self):
        """Same content_id but different subject_slug is a different question."""
        WorksheetQuestion.objects.create(
            worksheet=self.worksheet, question=self.question,
            order=1, subject_slug='mathematics', content_id=1,
        )
        # Should not raise — different subject_slug
        wq2 = WorksheetQuestion.objects.create(
            worksheet=self.worksheet, question=self.question,
            order=2, subject_slug='coding', content_id=1,
        )
        self.assertEqual(wq2.subject_slug, 'coding')


# ---------------------------------------------------------------------------
# WorksheetStudentAnswer.answer_data
# ---------------------------------------------------------------------------

class TestWorksheetStudentAnswerData(WorksheetModelTestBase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from classroom.models import ClassRoom, AcademicYear
        cls.academic_year = AcademicYear.objects.get_or_create(
            year=2026, school=cls.school,
            defaults={'start_date': '2026-01-01', 'end_date': '2026-12-31'},
        )[0]
        cls.classroom = ClassRoom.objects.create(
            school=cls.school,
            name='WS Class',
            code='WSCLS001',
            academic_year=cls.academic_year,
        )
        cls.assignment = WorksheetAssignment.objects.create(
            worksheet=cls.worksheet, classroom=cls.classroom,
        )
        cls.student = CustomUser.objects.create_user(
            'ws_student', 'ws_student@example.com', 'pass1!',
        )
        cls.submission = WorksheetSubmission.objects.create(
            assignment=cls.assignment,
            student=cls.student,
            total_questions=1,
        )

    def test_answer_data_defaults_to_empty_dict(self):
        answer = WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            question=self.question,
            is_correct=True,
            points_earned=1.0,
        )
        self.assertEqual(answer.answer_data, {})

    def test_answer_data_stores_arbitrary_json(self):
        payload = {'code': 'print("hello")', 'stdout': 'hello\n', 'language': 'python'}
        answer = WorksheetStudentAnswer.objects.create(
            submission=self.submission,
            question=self.question,
            is_correct=True,
            points_earned=1.0,
            answer_data=payload,
        )
        answer.refresh_from_db()
        self.assertEqual(answer.answer_data['code'], 'print("hello")')
        self.assertEqual(answer.answer_data['language'], 'python')


# ---------------------------------------------------------------------------
# Data migration backfill test
# ---------------------------------------------------------------------------

class TestDataMigrationBackfill(WorksheetModelTestBase):
    def test_data_migration_backfill_function_sets_content_id(self):
        """
        Directly call the migration's backfill function to verify it sets
        content_id = question_id for rows where content_id == 0.
        """
        from django.apps import apps

        # Create a row simulating the pre-migration state (content_id=0)
        wq = WorksheetQuestion.objects.create(
            worksheet=self.worksheet,
            question=self.question,
            order=1,
            subject_slug='mathematics',
            content_id=0,  # pre-migration default
        )
        self.assertEqual(wq.content_id, 0)

        # Import and call the migration function directly via importlib
        import importlib
        mod = importlib.import_module('worksheets.migrations.0003_backfill_content_id')
        mod.backfill_content_id(apps, None)

        wq.refresh_from_db()
        self.assertEqual(wq.content_id, self.question.id)

    def test_data_migration_skips_already_backfilled_rows(self):
        """Rows with content_id already set are not touched."""
        wq = WorksheetQuestion.objects.create(
            worksheet=self.worksheet,
            question=self.question,
            order=1,
            subject_slug='mathematics',
            content_id=self.question.id,  # already correct
        )
        import importlib
        from django.apps import apps
        mod = importlib.import_module('worksheets.migrations.0003_backfill_content_id')
        mod.backfill_content_id(apps, None)
        wq.refresh_from_db()
        self.assertEqual(wq.content_id, self.question.id)
