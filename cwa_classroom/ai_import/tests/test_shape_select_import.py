"""``shape_select`` through the AI-import path.

Proves the enum offers the type and its target field, the importer stores the
traced spec with no answer rows, a malformed spec is reported and skipped, and
the pipeline actually runs the tracer over the finished crops — the wiring that
was missing, since every other piece already existed.
"""
import base64
import io

from django.test import TestCase

from accounts.models import CustomUser
from classroom.models import Level
from ai_import.models import AIImportSession
from ai_import.services import CLASSIFICATION_TOOL, save_questions_from_session
from maths.geometry_grading import shape_target_ids
from maths.models import Question
from maths.shape_detect import trace_shape_select_scenes

TEXT = 'Colour all the triangles.'


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


def _payload(q):
    return {
        'year_level': 3, 'subject': 'Mathematics', 'strand': 'Geometry',
        'topic': 'Shapes', 'questions': [q],
    }


class ExtractionSchemaTests(TestCase):
    def test_enum_includes_shape_select_with_its_target(self):
        props = (CLASSIFICATION_TOOL["input_schema"]["properties"]["questions"]
                 ["items"]["properties"])
        self.assertIn('shape_select', props['question_type']['enum'])
        self.assertIn('shape_target_type', props)

    def test_the_prompt_tells_the_model_not_to_describe_the_shapes(self):
        from ai_import.services import _build_classification_prompt
        prompt = _build_classification_prompt([], [])
        self.assertIn('shape_select', prompt)
        self.assertIn('shape_target_type', prompt)
        self.assertIn('TRACES', prompt)


class PipelineRunsTheTracerTests(TestCase):
    """The wiring that was missing: the tracer must run over the finished crops."""

    def test_tasks_traces_scenes_after_cropping(self):
        import inspect
        from ai_import import tasks

        src = inspect.getsource(tasks)
        crop_at = src.index('crop_figure_boxes(extracted, result')
        trace_at = src.index('trace_shape_select_scenes(')
        self.assertLess(crop_at, trace_at,
                        'the tracer needs the finished crops, so it must run after them')

    def test_worksheets_traces_scenes_after_rendering(self):
        import inspect
        from worksheets import services

        src = inspect.getsource(services)
        render_at = src.index('result, extracted_images = render_question_images(')
        trace_at = src.index('traced, untraceable = trace_shape_select_scenes(')
        self.assertLess(render_at, trace_at)


class SaveShapeSelectTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser(
            'ss_super', 'ss_super@test.internal', 'pw1!')
        Level.objects.get_or_create(level_number=3, defaults={'display_name': 'Year 3'})

    def _save(self, q):
        session = AIImportSession.objects.create(
            user=self.user, pdf_filename='ss.pdf', extracted_data=_payload(q))
        return save_questions_from_session(session, self.user, session.extracted_data)

    def test_it_imports_with_its_spec_and_no_answers(self):
        result = self._save({
            'question_text': TEXT, 'question_type': 'shape_select',
            'shape_spec': _traced_spec(), 'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 1)
        self.assertEqual(result['failed'], 0)
        q = Question.objects.get(question_type='shape_select')
        self.assertEqual(q.shape_spec['target_type'], 'triangle')
        self.assertEqual(len(shape_target_ids(q.shape_spec)), 2)
        self.assertEqual(q.answers.count(), 0)

    def test_a_scene_with_nothing_to_colour_is_reported_and_skipped(self):
        result = self._save({
            'question_text': 'Broken scene.', 'question_type': 'shape_select',
            'shape_spec': {'target_type': 'triangle', 'shapes': []},
            'difficulty': 1, 'points': 1,
        })
        self.assertEqual(result['inserted'], 0)
        self.assertEqual(result['failed'], 1)
        self.assertTrue(any('shape_spec' in e for e in result['errors']))
