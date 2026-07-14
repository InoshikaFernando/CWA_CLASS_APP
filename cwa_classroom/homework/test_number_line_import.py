"""``number_line`` type in the homework PDF-upload pipeline.

Pins the wiring: the extraction enum offers number_line, the save path persists
the number_line_spec with no answer rows, and a malformed/off-tick spec is
skipped rather than imported broken. Mirrors test_measure_geometry_import.py.
"""
from django.test import TestCase

from accounts.models import CustomUser, Role
from classroom.models import School, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.models import Question as MQ
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL


def _props():
    return (WORKSHEET_CLASSIFICATION_TOOL["input_schema"]["properties"]
            ["questions"]["items"]["properties"])


class ExtractionSchemaTests(TestCase):
    def test_number_line_added_to_enum(self):
        enum = _props()["question_type"]["enum"]
        self.assertIn('number_line', enum)

    def test_number_line_spec_field_present(self):
        self.assertIn('number_line_spec', _props())


class SaveNumberLineTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('nl_hw', 'nl_hw@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='NL School', slug='nl-school', admin=cls.user)
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Number Line', slug='number-line', subject=cls.subject)

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )

    def _save(self, questions):
        return _save_homework_pdf_questions(
            questions, {'year_level': 4, 'subject': 'Mathematics', 'topic': 'Number Line'},
            self.user, self.school, self._session(), save_images=False,
        )

    def test_mark_imports_spec_no_answers(self):
        saved = self._save([{
            'question_text': 'Draw a number line from -3 to 7 and mark 2.',
            'question_type': 'number_line',
            'number_line_spec': {'min': -3, 'max': 7, 'step': 1,
                                 'mode': 'mark', 'target': [2]},
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.NUMBER_LINE)
        self.assertEqual(q.number_line_spec['target'], [2])
        self.assertEqual(q.answers.count(), 0)

    def test_read_imports_spec(self):
        saved = self._save([{
            'question_text': 'What value does the arrow point to?',
            'question_type': 'number_line',
            'number_line_spec': {'min': 0, 'max': 10, 'step': 2,
                                 'mode': 'read', 'given': [6]},
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].number_line_spec['given'], [6])

    def test_invalid_spec_is_skipped(self):
        saved = self._save([{
            'question_text': 'Broken number line.',
            'question_type': 'number_line',
            'number_line_spec': {'min': 0, 'max': 10, 'step': 2,
                                 'mode': 'mark', 'target': [3]},  # 3 is off-tick
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken number line.').exists())

    def test_imported_question_grades_through_the_homework_plugin(self):
        # End-to-end: import → the maths plugin grades the posted marks (mark mode)
        # off the stored spec, awarding the question's points on a correct set.
        from maths.plugin import MathsPlugin
        saved = self._save([{
            'question_text': 'Mark 2 (gradeable).',
            'question_type': 'number_line',
            'number_line_spec': {'min': -3, 'max': 7, 'step': 1,
                                 'mode': 'mark', 'target': [2]},
            'validation_type': 'auto', 'difficulty': 1, 'points': 3,
            'has_image': False, 'answers': [],
        }])
        q = saved[0]
        plugin = MathsPlugin()
        good = plugin.grade_answer(q.pk, {f'answer_{q.id}': '{"marks": [2]}'})
        bad = plugin.grade_answer(q.pk, {f'answer_{q.id}': '{"marks": [3]}'})
        self.assertTrue(good['is_correct'])
        self.assertEqual(good['points_earned'], 3)
        self.assertFalse(bad['is_correct'])
        self.assertEqual(bad['points_earned'], 0)
