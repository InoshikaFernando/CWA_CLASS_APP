"""A sheet of shapes is detected per item, not switched on per upload.

The upload form used to carry a "Name-the-shape mode" checkbox that swapped the
whole system prompt: it worked only when the entire PDF was a shapes sheet, and
a mixed page (a row of shapes to name above ordinary questions) lost one half
or the other. Now the classifier emits ``name_the_shape`` per shape (rule 19)
and each is normalised into the multiple-choice question the app already
renders and grades, marked for the preview badge. Zero-token: mocked client.
"""
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import CustomUser, Role
from billing.testing import grant_ai_pages
from classroom.models import School, SchoolTeacher
from worksheets import services
from worksheets.models import WorksheetUploadSession
from worksheets.services import (
    EXTRACTED_QUESTION_TYPES,
    NAME_THE_SHAPE_TEXT,
    NAME_THE_SHAPE_TYPE,
    WORKSHEET_CLASSIFICATION_TOOL,
    _normalise_name_the_shape,
)


def _shape(**over):
    q = {
        'question_text': NAME_THE_SHAPE_TEXT, 'question_type': NAME_THE_SHAPE_TYPE,
        'has_image': True, 'image_bbox': [10, 10, 60, 60], 'page_num': 1,
        'answers': [{'text': 'Triangle', 'is_correct': True},
                    {'text': 'Square', 'is_correct': False},
                    {'text': 'Rectangle', 'is_correct': False},
                    {'text': 'Rhombus', 'is_correct': False}],
    }
    q.update(over)
    return q


class SchemaAndPromptTests(SimpleTestCase):
    def test_the_model_may_say_name_the_shape_but_the_review_dropdown_never_shows_it(self):
        enum = (WORKSHEET_CLASSIFICATION_TOOL['input_schema']['properties']['questions']
                ['items']['properties']['question_type']['enum'])
        self.assertIn(NAME_THE_SHAPE_TYPE, enum)
        self.assertNotIn(NAME_THE_SHAPE_TYPE, EXTRACTED_QUESTION_TYPES)

    def test_the_one_prompt_carries_the_rule(self):
        prompt = services._build_system_prompt([], [])
        self.assertIn('NAME-THE-SHAPE ITEMS', prompt)
        self.assertIn('question_type = "name_the_shape"', prompt)
        self.assertIn(NAME_THE_SHAPE_TEXT, prompt)
        self.assertIn('reading school homework worksheets', prompt)   # still the normal prompt

    def test_there_is_no_mode_switch_any_more(self):
        with self.assertRaises(TypeError):
            services._build_system_prompt([], [], shape_naming=True)
        with self.assertRaises(TypeError):
            services.classify_worksheet_questions({'pages': []}, [], [], shape_naming=True)


class NormaliseNameTheShapeTests(SimpleTestCase):
    def test_a_mixed_page_keeps_its_ordinary_questions_and_converts_the_shapes(self):
        ordinary = {'question_text': 'Find the area of this rectangle.',
                    'question_type': 'short_answer', 'has_image': True,
                    'image_bbox': [1, 2, 3, 4], 'answers': [{'text': '12', 'is_correct': True}]}
        questions = [ordinary, _shape(), _shape(answers=[
            {'text': 'Circle', 'is_correct': True}, {'text': 'Oval', 'is_correct': False},
            {'text': 'Sphere', 'is_correct': False}, {'text': 'Ellipse', 'is_correct': False}])]

        self.assertEqual(_normalise_name_the_shape(questions), 2)

        self.assertEqual(questions[0]['question_type'], 'short_answer')
        self.assertNotIn('shape_naming', questions[0])
        for q in questions[1:]:
            self.assertEqual(q['question_type'], 'multiple_choice')
            self.assertTrue(q['shape_naming'])
            self.assertEqual(q['validation_type'], 'auto')
            self.assertTrue(q['has_image'])
            self.assertEqual((q['subject'], q['strand'], q['topic']),
                             ('Mathematics', 'Geometry', '2D Shapes'))
            self.assertNotIn('needs_review', q)

    def test_a_blank_question_text_gets_the_standard_wording(self):
        q = _shape(question_text='  ')
        _normalise_name_the_shape([q])
        self.assertEqual(q['question_text'], NAME_THE_SHAPE_TEXT)

    def test_a_shape_with_no_box_is_sent_to_review_not_saved_blind(self):
        q = _shape(image_bbox=None)
        _normalise_name_the_shape([q])
        self.assertTrue(q['needs_review'])
        self.assertIn('no box', q['review_reason'])

    def test_not_exactly_one_correct_option_is_sent_to_review(self):
        two = _shape(answers=[{'text': 'Square', 'is_correct': True},
                              {'text': 'Rectangle', 'is_correct': True}])
        none = _shape(answers=[{'text': 'Square', 'is_correct': False},
                               {'text': 'Rectangle', 'is_correct': False}])
        _normalise_name_the_shape([two, none])
        self.assertIn('2 options are ticked correct', two['review_reason'])
        self.assertIn('0 options are ticked correct', none['review_reason'])

    def test_an_existing_review_reason_is_kept(self):
        q = _shape(image_bbox=None, needs_review=True, review_reason='GPT disagreed.')
        _normalise_name_the_shape([q])
        self.assertTrue(q['review_reason'].startswith('GPT disagreed.'))
        self.assertIn('Name-the-shape item', q['review_reason'])

    def test_explicit_classification_is_not_overwritten(self):
        q = _shape(topic='3D Shapes')
        _normalise_name_the_shape([q])
        self.assertEqual(q['topic'], '3D Shapes')


class _ToolStream:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        block = MagicMock()
        block.type = 'tool_use'
        block.name = 'classify_worksheet_questions'
        block.input = self.payload
        resp = MagicMock(stop_reason='tool_use')
        resp.content = [block]
        resp.usage.input_tokens = 1
        resp.usage.output_tokens = 1
        return resp


class ChunkNormalisesShapesTests(SimpleTestCase):
    def test_shape_items_come_out_of_the_chunk_as_marked_multiple_choice(self):
        payload = {'questions': [
            {'question_text': '3 + 4', 'question_type': 'short_answer', 'page_num': 1,
             'answers': [{'text': '7', 'is_correct': True}]},
            _shape(),
        ]}
        client = MagicMock()
        client.messages.stream.side_effect = lambda **kw: _ToolStream(payload)
        pages = [{'page_num': 1, 'screenshot': 'x', 'screenshot_w': 10,
                  'screenshot_h': 10, 'text': ''}]

        result = services._classify_page_chunk(client, 'sys', pages, 1)

        types = [q['question_type'] for q in result['questions']]
        self.assertEqual(types, ['short_answer', 'multiple_choice'])
        self.assertTrue(result['questions'][1]['shape_naming'])


class ExtractWorksheetPagesDpiTests(SimpleTestCase):
    """The screenshot DPI override survives (nothing uses it by default now)."""

    def _fake_doc(self, captured):
        page = MagicMock()
        page.get_text.return_value = 'txt'
        pix = MagicMock(width=10, height=12)
        pix.tobytes.return_value = b'img'

        def _get_pixmap(dpi):
            captured['dpi'] = dpi
            return pix
        page.get_pixmap.side_effect = _get_pixmap
        page.rect.width = 100.0
        page.rect.height = 140.0
        doc = MagicMock()
        doc.__len__.return_value = 1
        doc.__getitem__.return_value = page
        return doc

    def test_default_dpi(self):
        captured = {}
        services.extract_worksheet_pages(self._fake_doc(captured))
        self.assertEqual(captured['dpi'], services.SCREENSHOT_DPI)

    def test_override_dpi(self):
        captured = {}
        services.extract_worksheet_pages(self._fake_doc(captured), screenshot_dpi=222)
        self.assertEqual(captured['dpi'], 222)


class IncludeDefaultByValidationTypeTests(SimpleTestCase):
    """Teacher-graded (human_graded) questions are deselected by default; all
    other questions are included by default. Shared by the homework and worksheet
    PDF upload previews via extract_and_classify_worksheet."""

    def _run(self, classified_questions):
        with patch.dict('sys.modules', {'fitz': MagicMock()}), \
             patch('worksheets.services.extract_worksheet_pages',
                   return_value={'pages': [], 'page_count': 1}), \
             patch('worksheets.services.classify_worksheet_questions',
                   return_value={'questions': classified_questions,
                                 'usage': {'total_tokens': 0}}), \
             patch('worksheets.services.render_question_images',
                   side_effect=lambda doc, pages, result, progress=None: (result, {})):
            output = services.extract_and_classify_worksheet(
                MagicMock(read=lambda: b'%PDF-1.4'), [], [])
        return output['result']['questions']

    def test_human_graded_deselected_others_selected(self):
        questions = self._run([
            {'question_text': 'auto q', 'validation_type': 'auto'},
            {'question_text': 'ai q', 'validation_type': 'ai_graded'},
            {'question_text': 'teacher q', 'validation_type': 'human_graded'},
        ])
        by_type = {q['validation_type']: q for q in questions}
        self.assertTrue(by_type['auto']['include'])
        self.assertTrue(by_type['ai_graded']['include'])
        self.assertFalse(by_type['human_graded']['include'])

    def test_missing_validation_type_defaults_included(self):
        questions = self._run([{'question_text': 'no vt'}])
        self.assertTrue(questions[0]['include'])

    def test_explicit_include_is_not_overridden(self):
        questions = self._run([
            {'question_text': 'opted-in teacher q',
             'validation_type': 'human_graded', 'include': True},
        ])
        self.assertTrue(questions[0]['include'])


class WorksheetUploadNoModeSwitchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        owner_role, _ = Role.objects.get_or_create(
            name=Role.INSTITUTE_OWNER, defaults={'display_name': 'Institute Owner'})
        cls.owner = CustomUser.objects.create_user(
            'ws_v', 'ws_v@test.internal', 'pw1!',
            profile_completed=True, must_change_password=False)
        cls.owner.roles.add(owner_role)
        cls.school = School.objects.create(name='WS V', slug='ws-v', admin=cls.owner)
        SchoolTeacher.objects.get_or_create(school=cls.school, teacher=cls.owner)
        grant_ai_pages(cls.school)

    def setUp(self):
        self.client.force_login(self.owner)

    def test_upload_page_has_no_checkbox_and_says_shapes_are_detected(self):
        resp = self.client.get(reverse('worksheets:upload'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'name="shape_naming"')
        self.assertContains(resp, 'detected automatically')

    @patch('worksheets.tasks.process_worksheet_pdf')
    @patch('taskqueue.services.django_rq.get_queue')
    def test_a_stale_shape_naming_field_in_the_post_is_ignored(self, mock_get_queue, _task):
        mock_job = MagicMock(); mock_job.id = 'j1'
        mock_queue = MagicMock(); mock_queue.enqueue.return_value = mock_job
        mock_get_queue.return_value = mock_queue
        pdf = SimpleUploadedFile('q.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        self.client.post(reverse('worksheets:upload'), {'pdf_file': pdf, 'shape_naming': 'on'})
        session = WorksheetUploadSession.objects.get(user=self.owner)
        self.assertFalse(hasattr(session, 'shape_naming'))
