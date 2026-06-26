"""measure / draw_on_grid / shape_select types in the homework PDF-upload pipeline.

These geometry types existed on the Question model (and rendered/graded fine in
the quiz engine) but were never wired into the homework PDF-upload picker, so a
worksheet that used them could not be imported as homework. These tests pin that
wiring: the picker offers the types, the save path persists each one's structured
spec with no answer rows, a malformed/empty spec is skipped rather than imported
broken, and ``measure`` (only) is added to the AI extraction enum.

Mirrors test_plane_graph_import.py.
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


def _grid_spec():
    return {
        'grid': {'cols': 11, 'rows': 9},
        'shape': {'type': 'polygon', 'points': [[2, 3], [5, 2], [5, 5], [2, 5]]},
        'mode': 'segments',
        'target': {'segments': [{'x1': 4, 'y1': 0, 'x2': 4, 'y2': 8}]},
        'allow_extra': False,
    }


def _shape_spec():
    return {
        'target_type': 'triangle',
        'viewbox': [680, 400],
        'shapes': [
            {'id': 's0', 'type': 'triangle', 'cx': 60, 'cy': 60, 'size': 30, 'rot': 0},
            {'id': 's1', 'type': 'circle', 'cx': 200, 'cy': 60, 'size': 28, 'rot': 0},
        ],
    }


class ExtractionSchemaTests(TestCase):
    def test_measure_added_to_enum(self):
        enum = _props()["question_type"]["enum"]
        self.assertIn('measure', enum)
        # The earlier types must still be present (added, not replaced).
        for t in ('read_graph', 'plot_points', 'column_operation'):
            self.assertIn(t, enum)

    def test_grid_and_shape_kept_out_of_ai_enum(self):
        # Authoring grid_spec / shape_spec from a raw PDF image is error-prone, so
        # those types are reachable via the picker + JSON import, not AI extraction.
        enum = _props()["question_type"]["enum"]
        self.assertNotIn('draw_on_grid', enum)
        self.assertNotIn('shape_select', enum)


class SaveGeometryTypesTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('mg_u', 'mg_u@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='MG School', slug='mg-school', admin=cls.user)
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Geometry', slug='geometry', subject=cls.subject)

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )

    def _global(self):
        return {'year_level': 4, 'subject': 'Mathematics', 'topic': 'Geometry'}

    def _save(self, questions):
        return _save_homework_pdf_questions(
            questions, self._global(), self.user, self.school, self._session(),
            save_images=False,
        )

    def test_measure_imports_numeric_fields_no_answers(self):
        saved = self._save([{
            'question_text': 'Measure this angle.',
            'question_type': 'measure',
            'numeric_answer': 135, 'answer_tolerance': 2, 'answer_unit': '°',
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.MEASURE)
        self.assertEqual(int(q.numeric_answer), 135)
        self.assertEqual(int(q.answer_tolerance), 2)
        self.assertEqual(q.answer_unit, '°')
        self.assertEqual(q.answers.count(), 0)

    def test_measure_without_numeric_answer_is_skipped(self):
        saved = self._save([{
            'question_text': 'No value to measure.',
            'question_type': 'measure',
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='No value to measure.').exists())

    def test_draw_on_grid_imports_with_spec_no_answers(self):
        saved = self._save([{
            'question_text': 'Draw all lines of symmetry.',
            'question_type': 'draw_on_grid',
            'grid_spec': _grid_spec(),
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.DRAW_ON_GRID)
        self.assertEqual(q.grid_spec['target']['segments'][0]['x1'], 4)
        self.assertEqual(q.answers.count(), 0)

    def test_shape_select_imports_with_spec_no_answers(self):
        saved = self._save([{
            'question_text': 'Colour all the triangles.',
            'question_type': 'shape_select',
            'shape_spec': _shape_spec(),
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.SHAPE_SELECT)
        self.assertEqual(q.shape_spec['target_type'], 'triangle')
        self.assertEqual(q.answers.count(), 0)

    def test_invalid_grid_spec_is_skipped(self):
        saved = self._save([{
            'question_text': 'Broken grid.',
            'question_type': 'draw_on_grid',
            'grid_spec': {'grid': {'cols': 0, 'rows': 0}, 'shape': {}, 'mode': 'segments',
                          'target': {'segments': []}},
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken grid.').exists())

    def test_invalid_shape_spec_is_skipped(self):
        saved = self._save([{
            'question_text': 'Broken shapes.',
            'question_type': 'shape_select',
            'shape_spec': {'target_type': 'triangle'},  # no shapes / viewbox
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken shapes.').exists())

    def test_answer_options_are_not_saved_for_geometry_types(self):
        # Even if upstream supplies answer rows, these types must persist none —
        # the model's clean() rejects answer options on them.
        saved = self._save([{
            'question_text': 'Colour all the triangles (with stray answers).',
            'question_type': 'shape_select',
            'shape_spec': _shape_spec(),
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False,
            'answers': [{'text': 'triangle', 'is_correct': True}],
        }])
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].answers.count(), 0)
