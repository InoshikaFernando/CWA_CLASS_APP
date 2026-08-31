"""``sketch_graph`` through the homework PDF-upload pipeline.

The questions this type exists for: "Sketch the graph of y = x² + x − 2 showing
the coordinates of the vertex, x-axis and y-axis intercepts and equation of the
axis of symmetry" — a whole Year-10/11 quadratics paper of them. Every one used
to be routed to the teacher as an un-gradeable drawing, because "sketch … graph"
reads as a construction. It is not: the marks are for the FEATURES the stem
names, and the student can type those.

So this pins the whole path — the extractor may emit the type and its spec, the
review page offers it and posts it back, the saver imports it with the spec
intact and no answer options, and it grades through the maths plugin.

Mirrors test_table_of_values_import.py.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.models import Question as MQ
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL


QUESTION_TEXT = (
    'Sketch the graph of y = x² + x - 2 showing the coordinates of the vertex, '
    'x-axis and y-axis intercepts and equation of the axis of symmetry.'
)

_SKETCH_SPEC = {
    'equation': 'y = x^2 + x - 2',
    'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
    'curve': {'type': 'quadratic', 'a': 1, 'b': 1, 'c': -2},
    'features': [
        {'kind': 'vertex', 'points': [[-0.5, -2.25]]},
        {'kind': 'x_intercept', 'points': [[-2, 0], [1, 0]]},
        {'kind': 'y_intercept', 'points': [[0, -2]]},
        {'kind': 'axis_of_symmetry', 'value': -0.5},
    ],
}

_RIGHT = ('{"features": {"vertex": "(-0.5, -2.25)", '
          '"x_intercept": "(-2, 0), (1, 0)", "y_intercept": "(0, -2)", '
          '"axis_of_symmetry": "x = -0.5"}}')


class ExtractionSchemaTests(TestCase):
    def test_sketch_graph_in_enum_with_its_spec(self):
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('sketch_graph', props['question_type']['enum'])
        self.assertIn('sketch_spec', props)


class _TeacherFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('sk_hw', 'sk_hw@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='SK School', slug='sk-school', admin=cls.user)
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.user, defaults={'role': 'teacher'})
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=10, display_name='Year 10')
        cls.topic = Topic.objects.create(
            name='Quadratics', slug='quadratics', subject=cls.subject)


class SaveSketchGraphTests(_TeacherFixture):

    def _save(self, questions):
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )
        return _save_homework_pdf_questions(
            questions, {'year_level': 10, 'subject': 'Mathematics', 'topic': 'Quadratics'},
            self.user, self.school, session, save_images=False,
        )

    def _question(self, **overrides):
        q = {
            'question_text': QUESTION_TEXT,
            'question_type': 'sketch_graph',
            'sketch_spec': _SKETCH_SPEC,
            'validation_type': 'auto', 'difficulty': 2, 'points': 1,
            'has_image': False, 'answers': [],
        }
        q.update(overrides)
        return q

    def test_a_sketch_imports_as_a_sketch_not_a_short_answer(self):
        saved = self._save([self._question()])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.SKETCH_GRAPH)
        self.assertEqual(q.sketch_spec['equation'], 'y = x^2 + x - 2')
        self.assertEqual(q.answers.count(), 0)

    def test_it_stays_auto_graded_rather_than_going_to_the_teacher(self):
        q = self._save([self._question()])[0]
        self.assertEqual(q.validation_type, MQ.VALIDATION_AUTO)

    def test_the_imported_sketch_grades_through_the_maths_plugin(self):
        from maths.plugin import MathsPlugin
        q = self._save([self._question()])[0]
        plugin = MathsPlugin()
        good = plugin.grade_answer(q.pk, {f'answer_{q.id}': _RIGHT})
        bad = plugin.grade_answer(
            q.pk, {f'answer_{q.id}': '{"features": {"vertex": "(0, 0)"}}'})
        self.assertTrue(good['is_correct'])
        self.assertFalse(bad['is_correct'])

    def test_a_partly_right_sketch_keeps_the_marks_it_earned(self):
        from maths.plugin import MathsPlugin
        q = self._save([self._question(points=4)])[0]
        result = MathsPlugin().grade_answer(q.pk, {f'answer_{q.id}': (
            '{"features": {"vertex": "(0, 0)", "x_intercept": "(-2, 0), (1, 0)", '
            '"y_intercept": "(0, -2)", "axis_of_symmetry": "x = -0.5"}}')})
        self.assertFalse(result['is_correct'])
        self.assertEqual(result['points_earned'], 3.0)
        self.assertEqual(result['answer_data']['parts_correct'], 3)

    def test_a_malformed_sketch_spec_is_skipped_not_imported_broken(self):
        saved = self._save([self._question(
            question_text='Broken sketch.',
            sketch_spec={'bounds': {'xmin': -6, 'xmax': 6, 'ymin': -4, 'ymax': 8},
                         'features': []},
        )])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken sketch.').exists())

    def test_a_sketch_never_carries_a_figure_image(self):
        """The app draws the plane itself, so an attached crop would be noise."""
        q = self._save([self._question(has_image=True, image_ref='p1_fig1.png')])[0]
        self.assertFalse(q.image)


class ConstructionRoutingTests(TestCase):
    """The sweep that sends "draw it" questions to the teacher must let these
    through — that sweep is exactly what used to swallow them."""

    def test_a_sketch_with_features_stays_auto(self):
        from worksheets.services import (
            is_unanswerable_construction, route_constructions_to_teacher,
        )
        q = {'question_text': QUESTION_TEXT, 'question_type': 'sketch_graph',
             'validation_type': 'auto', 'answers': []}
        self.assertFalse(is_unanswerable_construction(q))
        questions = [q]
        route_constructions_to_teacher(questions)
        self.assertEqual(questions[0]['validation_type'], 'auto')

    def test_a_bare_drawing_instruction_still_goes_to_the_teacher(self):
        from worksheets.services import is_unanswerable_construction
        self.assertTrue(is_unanswerable_construction({
            'question_text': 'Draw a tree diagram to illustrate this situation.',
            'question_type': 'extended_answer', 'answers': [],
        }))


class PreviewKeepsTheTypeTests(_TeacherFixture):
    """The review page must offer — and post back — the type it was given."""

    def _session(self):
        return HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 10, 'subject': 'Mathematics', 'topic': 'Quadratics',
                'questions': [{
                    'question_text': QUESTION_TEXT,
                    'question_type': 'sketch_graph',
                    'sketch_spec': _SKETCH_SPEC,
                    'validation_type': 'auto', 'difficulty': 2, 'points': 1,
                    'answers': [], 'include': True,
                }],
            },
            extracted_images={},
        )

    def test_the_dropdown_offers_the_extracted_type_selected(self):
        s = self._session()
        self.client.force_login(self.user)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('value="sketch_graph" selected', html)
        # ...and the spec is editable rather than invisible.
        self.assertIn('q_0_sketch_spec', html)
