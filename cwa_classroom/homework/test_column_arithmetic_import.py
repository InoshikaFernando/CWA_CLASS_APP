"""Column arithmetic (column_operation) support in the homework PDF-upload pipeline.

The homework PDF flow is separate from the standalone ai_import app and historically
only knew about long_division. These tests pin the wiring that lets stacked +/−/×
worksheets (e.g. "23 + 25") import as column_operation questions that grade themselves.
"""
from unittest.mock import patch

from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import School, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.models import Question as MQ, Answer as MA
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL


def _question_type_schema():
    return (
        WORKSHEET_CLASSIFICATION_TOOL["input_schema"]["properties"]
        ["questions"]["items"]["properties"]
    )


class ExtractionSchemaTests(TestCase):
    """The shared worksheet/homework extractor must be able to emit column_operation."""

    def test_enum_includes_column_operation(self):
        enum = _question_type_schema()["question_type"]["enum"]
        self.assertIn("column_operation", enum)
        # Long division should still be there — we added, not replaced.
        self.assertIn("long_division", enum)

    def test_operands_and_operator_fields_present(self):
        props = _question_type_schema()
        self.assertIn("operands", props)
        self.assertIn("operator", props)
        self.assertEqual(props["operator"]["enum"], ["+", "-", "*"])


class SaveColumnOperationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('ca_u', 'ca_u@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='CA School', slug='ca-school', admin=cls.user)
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Addition', slug='addition', subject=cls.subject)

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )

    def _global(self):
        return {'year_level': 4, 'subject': 'Mathematics', 'topic': 'Addition'}

    def _save(self, questions):
        return _save_homework_pdf_questions(
            questions, self._global(), self.user, self.school, self._session(),
        )

    def test_addition_imports_with_computed_answer(self):
        saved = self._save([{
            'question_text': '23 + 25',
            'question_type': 'column_operation',
            'operands': [23, 25],
            'operator': '+',
            'validation_type': 'auto',
            'difficulty': 1, 'points': 1, 'answers': [],
        }])

        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.COLUMN_OPERATION)
        self.assertEqual(q.operands, [23, 25])
        self.assertEqual(q.operator, '+')
        self.assertEqual(q.column_result, 48)
        # The correct answer is computed and stored — no manual answer row needed.
        answer = MA.objects.get(question=q, is_correct=True)
        self.assertEqual(answer.answer_text, '48')

    def test_subtraction_and_multiplication(self):
        saved = self._save([
            {'question_text': '68 - 20', 'question_type': 'column_operation',
             'operands': [68, 20], 'operator': '-', 'validation_type': 'auto',
             'difficulty': 1, 'points': 1, 'answers': []},
            {'question_text': '12 x 12', 'question_type': 'column_operation',
             'operands': [12, 12], 'operator': '*', 'validation_type': 'auto',
             'difficulty': 1, 'points': 1, 'answers': []},
        ])
        self.assertEqual(len(saved), 2)
        results = {q.question_text: q.column_result for q in saved}
        self.assertEqual(results['68 - 20'], 48)
        self.assertEqual(results['12 x 12'], 144)

    def test_invalid_column_operation_is_skipped(self):
        # Missing operands and a bad operator → cannot build a valid question, so skip
        # rather than import something broken with no usable answer.
        saved = self._save([
            {'question_text': 'broken op', 'question_type': 'column_operation',
             'operands': [5], 'operator': '+', 'validation_type': 'auto',
             'difficulty': 1, 'points': 1, 'answers': []},  # only one operand
            {'question_text': 'bad operator', 'question_type': 'column_operation',
             'operands': [5, 3], 'operator': '/', 'validation_type': 'auto',
             'difficulty': 1, 'points': 1, 'answers': []},  # unsupported operator
        ])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_type=MQ.COLUMN_OPERATION).exists())
