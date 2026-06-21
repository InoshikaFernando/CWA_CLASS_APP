"""Cartesian-plane / read-graph types in the homework PDF-upload pipeline.

The homework PDF flow is separate from the standalone ai_import app. These tests
pin the wiring that lets plot_points / read_graph worksheets import with the right
structured spec and no answer rows, and that a malformed plane_spec is skipped.
Mirrors test_column_arithmetic_import.py.
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


def _plane_spec(mode='points', target=None):
    return {
        'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
        'mode': mode,
        'target': target or {'points': [[3, -2], [1, 4]]},
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_new_types(self):
        enum = _props()["question_type"]["enum"]
        for t in ('plot_points', 'plot_line', 'identify_coords', 'read_graph'):
            self.assertIn(t, enum)
        self.assertIn('column_operation', enum)   # added, not replaced

    def test_spec_fields_present(self):
        props = _props()
        self.assertIn('plane_spec', props)
        self.assertIn('graph_spec', props)
        self.assertIn('numeric_answer', props)


class SavePlaneGraphTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('pg_u', 'pg_u@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='PG School', slug='pg-school', admin=cls.user)
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=4, display_name='Year 4')
        cls.topic = Topic.objects.create(name='Coordinates', slug='coordinates', subject=cls.subject)

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )

    def _global(self):
        return {'year_level': 4, 'subject': 'Mathematics', 'topic': 'Coordinates'}

    def _save(self, questions):
        return _save_homework_pdf_questions(
            questions, self._global(), self.user, self.school, self._session(),
        )

    def test_plot_points_imports_with_spec_no_answers(self):
        saved = self._save([{
            'question_text': 'Plot the points.',
            'question_type': 'plot_points',
            'plane_spec': _plane_spec(),
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.PLOT_POINTS)
        self.assertEqual(q.plane_spec['target']['points'], [[3, -2], [1, 4]])
        self.assertEqual(q.answers.count(), 0)

    def test_read_graph_imports_numeric_fields(self):
        saved = self._save([{
            'question_text': 'Read the distance at 40 min.',
            'question_type': 'read_graph',
            'numeric_answer': 130, 'answer_tolerance': 5, 'answer_unit': 'km',
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.READ_GRAPH)
        self.assertEqual(int(q.numeric_answer), 130)
        self.assertEqual(int(q.answer_tolerance), 5)
        self.assertEqual(q.answer_unit, 'km')
        self.assertEqual(q.answers.count(), 0)

    def test_invalid_plane_spec_is_skipped(self):
        saved = self._save([{
            'question_text': 'Broken plane.',
            'question_type': 'plot_points',
            'plane_spec': {'bounds': {'xmin': 5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                           'mode': 'points', 'target': {'points': [[0, 0]]}},
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken plane.').exists())

    def test_read_graph_without_numeric_answer_is_skipped(self):
        saved = self._save([{
            'question_text': 'No value.',
            'question_type': 'read_graph',
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }])
        self.assertEqual(saved, [])

    def test_read_graph_dedups_by_text_not_image(self):
        # Two questions that read DIFFERENT values off the SAME graph image must
        # stay distinct — read_graph's identity is its numeric answer, not the
        # picture. (Regression: keying read_graph on the image path collapsed
        # them and dropped the second answer.)
        import base64
        ref = 'race_graph.png'
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
            extracted_images={ref: base64.b64encode(b'fakepng').decode()},
        )
        questions = [
            {'question_text': 'How far at 40 min?', 'question_type': 'read_graph',
             'numeric_answer': 130, 'answer_unit': 'km', 'image_ref': ref,
             'validation_type': 'auto', 'difficulty': 1, 'points': 1,
             'has_image': True, 'answers': []},
            {'question_text': 'How far at 80 min?', 'question_type': 'read_graph',
             'numeric_answer': 260, 'answer_unit': 'km', 'image_ref': ref,
             'validation_type': 'auto', 'difficulty': 1, 'points': 1,
             'has_image': True, 'answers': []},
        ]
        # save_images=False so the test doesn't hit S3/Spaces — we only assert dedup.
        saved = _save_homework_pdf_questions(
            questions, self._global(), self.user, self.school, session,
            save_images=False,
        )
        self.assertEqual(len(saved), 2)
        answers = sorted(int(q.numeric_answer) for q in saved)
        self.assertEqual(answers, [130, 260])
