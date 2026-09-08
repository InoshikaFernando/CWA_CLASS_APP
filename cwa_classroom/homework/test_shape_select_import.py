"""``shape_select`` through the homework PDF-upload pipeline.

"Colour all the triangles" was the one structured type the PDF path could not
produce — not because the pieces were missing, but because they were never
connected. ``maths.shape_detect`` already traced an image into a ``shape_spec``
(it powered a management command only), and both savers already validated and
persisted ``shape_spec``. What was missing was the classifier being allowed to
say "this is a shapes scene, the target is triangles" and something running the
tracer over the crop.

This pins the saver half and the classifier contract. The tracing step itself is
covered in maths/tests/test_shape_select_extraction.py.
"""
import base64
import io

from django.test import TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from classroom.models import School, SchoolTeacher, Subject, Topic, Level
from homework.models import HomeworkUploadSession
from homework.views import _save_homework_pdf_questions
from maths.geometry_grading import shape_target_ids
from maths.models import Question as MQ
from maths.shape_detect import trace_shape_select_scenes
from worksheets.services import WORKSHEET_CLASSIFICATION_TOOL

QUESTION_TEXT = 'Colour all the triangles.'


def _sheet_b64():
    from PIL import Image, ImageDraw

    img = Image.new('RGB', (600, 400), 'white')
    d = ImageDraw.Draw(img)
    d.polygon([(60, 40), (140, 40), (100, 120)], outline='black', width=3)
    d.rectangle([(220, 40), (320, 140)], outline='black', width=3)
    d.polygon([(80, 220), (180, 220), (130, 320)], outline='black', width=3)
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()


def _traced_spec():
    q = {'question_type': 'shape_select', 'shape_target_type': 'triangle',
         'image_ref': 'scene.png'}
    trace_shape_select_scenes([q], {'scene.png': _sheet_b64()})
    return q['shape_spec']


class ExtractionSchemaTests(TestCase):
    def test_shape_select_in_enum_with_its_target_type(self):
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        self.assertIn('shape_select', props['question_type']['enum'])
        self.assertIn('shape_target_type', props)

    def test_the_model_is_only_asked_which_shape_never_the_geometry(self):
        props = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']
                 ['questions']['items']['properties'])
        # A string enum of shape kinds — there is no field for outlines at all.
        self.assertEqual(props['shape_target_type']['type'], 'string')
        self.assertIn('triangle', props['shape_target_type']['enum'])
        self.assertNotIn('shape_spec', props)

    def test_the_prompt_says_the_app_traces_the_shapes(self):
        from worksheets.services import WORKSHEET_SYSTEM_PROMPT
        self.assertIn('FIND / COLOUR THE SHAPES', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('shape_target_type', WORKSHEET_SYSTEM_PROMPT)
        self.assertIn('TRACES', WORKSHEET_SYSTEM_PROMPT)
        # And what is NOT this type, so a "name this shape" isn't swept in.
        self.assertIn('name this shape', WORKSHEET_SYSTEM_PROMPT)


class _TeacherFixture(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_user('ss_hw', 'ss_hw@test.internal', 'pw1!')
        teacher_role, _ = Role.objects.get_or_create(
            name=Role.TEACHER, defaults={'display_name': 'Teacher'})
        cls.user.roles.add(teacher_role)
        cls.school = School.objects.create(name='SS School', slug='ss-school', admin=cls.user)
        SchoolTeacher.objects.get_or_create(
            school=cls.school, teacher=cls.user, defaults={'role': 'teacher'})
        cls.subject = Subject.objects.create(name='Mathematics', slug='mathematics')
        cls.level = Level.objects.create(level_number=3, display_name='Year 3')
        cls.topic = Topic.objects.create(name='Shapes', slug='shapes', subject=cls.subject)


class SaveShapeSelectTests(_TeacherFixture):

    def _save(self, questions):
        session = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )
        session.extracted_images = {'scene.png': _sheet_b64()}
        return _save_homework_pdf_questions(
            questions, {'year_level': 3, 'subject': 'Mathematics', 'topic': 'Shapes'},
            self.user, self.school, session, save_images=False,
        )

    def _question(self, **overrides):
        q = {
            'question_text': QUESTION_TEXT,
            'question_type': 'shape_select',
            'shape_spec': _traced_spec(),
            'validation_type': 'auto', 'difficulty': 1, 'points': 1,
            'has_image': False, 'answers': [],
        }
        q.update(overrides)
        return q

    def test_a_traced_scene_imports_with_its_spec(self):
        saved = self._save([self._question()])
        self.assertEqual(len(saved), 1)
        q = saved[0]
        self.assertEqual(q.question_type, MQ.SHAPE_SELECT)
        self.assertEqual(q.shape_spec['target_type'], 'triangle')
        self.assertEqual(q.answers.count(), 0)

    def test_the_answer_key_is_derived_from_the_figure_not_stored(self):
        q = self._save([self._question()])[0]
        self.assertEqual(len(shape_target_ids(q.shape_spec)), 2)

    def test_the_imported_scene_grades_through_the_maths_plugin(self):
        import json
        from maths.plugin import MathsPlugin

        q = self._save([self._question()])[0]
        right = sorted(shape_target_ids(q.shape_spec))
        plugin = MathsPlugin()
        good = plugin.grade_answer(
            q.pk, {f'answer_{q.id}': json.dumps({'selected': right})})
        missed = plugin.grade_answer(
            q.pk, {f'answer_{q.id}': json.dumps({'selected': right[:1]})})
        self.assertTrue(good['is_correct'])
        self.assertFalse(missed['is_correct'])

    def test_a_malformed_spec_is_skipped_not_imported_broken(self):
        saved = self._save([self._question(
            question_text='Broken scene.',
            shape_spec={'target_type': 'triangle', 'shapes': []},
        )])
        self.assertEqual(saved, [])
        self.assertFalse(MQ.objects.filter(question_text='Broken scene.').exists())

    def test_it_never_carries_the_raster_crop(self):
        """The app redraws the traced scene, so the crop would be a duplicate."""
        q = self._save([self._question(has_image=True, image_ref='scene.png')])[0]
        self.assertFalse(q.image)


class PreviewKeepsTheTypeTests(_TeacherFixture):

    def test_the_dropdown_offers_the_extracted_type_selected(self):
        s = HomeworkUploadSession.objects.create(
            user=self.user, school=self.school, pdf_filename='hw.pdf',
            status=HomeworkUploadSession.STATUS_DONE, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 3, 'subject': 'Mathematics', 'topic': 'Shapes',
                'questions': [{
                    'question_text': QUESTION_TEXT,
                    'question_type': 'shape_select',
                    'shape_spec': _traced_spec(),
                    'validation_type': 'auto', 'difficulty': 1, 'points': 1,
                    'answers': [], 'include': True,
                }],
            },
            extracted_images={},
        )
        self.client.force_login(self.user)
        html = self.client.get(reverse('homework:pdf_preview', args=[s.pk])).content.decode()
        self.assertIn('value="shape_select" selected', html)
