"""The AI import detects shape questions the same way the worksheet upload does.

Rules 19 (name-the-shape items, one question per shape, detected per item) and
5b (a "tick the cylinder" question keeps its picture and offers POSITION
options) were added to the worksheet / homework classifier first; the AI
import kept its own prompt and could still emit "the can-shaped solid" as an
option or leave a shape sheet as one lumped question. Both rules now live in
this prompt too, ``name_the_shape`` is in its schema, and each item is
normalised into the multiple-choice question the app grades — marked for the
🔷 badge on the preview — before any later check sees it. Zero-token: the
Anthropic client is mocked.
"""
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from accounts.models import CustomUser
from classroom.models import School

from ai_import.models import AIImportSession
from ai_import.services import (
    CLASSIFICATION_TOOL,
    NAME_THE_SHAPE_TEXT,
    NAME_THE_SHAPE_TYPE,
    _build_classification_prompt,
    _normalise_name_the_shape,
    classify_questions,
)
from ai_import.verification import flag_missing_figures


def _shape(**over):
    q = {
        'question_text': NAME_THE_SHAPE_TEXT, 'question_type': NAME_THE_SHAPE_TYPE,
        'source_page': 1, 'image_page': 1,
        'image_box': {'x1': 10, 'y1': 10, 'x2': 30, 'y2': 30},
        'answers': [{'text': 'Triangle', 'is_correct': True},
                    {'text': 'Square', 'is_correct': False},
                    {'text': 'Rectangle', 'is_correct': False},
                    {'text': 'Rhombus', 'is_correct': False}],
    }
    q.update(over)
    return q


class PromptAndSchemaTests(SimpleTestCase):
    def test_the_prompt_carries_rule_19(self):
        prompt = _build_classification_prompt([], [])
        self.assertIn('NAME-THE-SHAPE ITEMS', prompt)
        self.assertIn('question_type = "name_the_shape"', prompt)
        self.assertIn(NAME_THE_SHAPE_TEXT, prompt)
        self.assertIn('image_box = a TIGHT', prompt)
        self.assertIn('box around ONLY that one shape', prompt)
        self.assertIn('exactly 3 plausible wrong names', prompt)

    def test_the_prompt_carries_rule_5b(self):
        prompt = _build_classification_prompt([], [])
        self.assertIn('PICK THE PICTURED ITEM', prompt)
        self.assertIn('"The first shape"', prompt)
        self.assertIn('NEVER name or describe what the pictures show', prompt)
        # The shape_select rule now hands "name this shape" and "tick the
        # cylinder" to their own rules instead of calling one "multiple choice".
        self.assertIn('"name this shape" (one shape — see NAME-THE-SHAPE ITEMS below)', prompt)
        self.assertIn('"tick the cylinder" (pick ONE pictured item', prompt)

    def test_the_model_may_say_name_the_shape(self):
        enum = (CLASSIFICATION_TOOL['input_schema']['properties']['questions']
                ['items']['properties']['question_type']['enum'])
        self.assertIn(NAME_THE_SHAPE_TYPE, enum)
        self.assertIn('shape_select', enum)   # untouched

    def test_the_two_pipelines_share_the_type_and_wording(self):
        from worksheets import services as ws
        self.assertEqual(NAME_THE_SHAPE_TYPE, ws.NAME_THE_SHAPE_TYPE)
        self.assertEqual(NAME_THE_SHAPE_TEXT, ws.NAME_THE_SHAPE_TEXT)


class NormaliseNameTheShapeTests(SimpleTestCase):
    def test_a_mixed_page_keeps_its_ordinary_questions_and_converts_the_shapes(self):
        ordinary = {'question_text': 'Find the area of this rectangle.',
                    'question_type': 'short_answer', 'source_page': 1, 'image_page': 1,
                    'image_box': {'x1': 1, 'y1': 2, 'x2': 3, 'y2': 4},
                    'answers': [{'text': '12', 'is_correct': True}]}
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
            self.assertEqual((q['subject'], q['strand'], q['topic']),
                             ('Mathematics', 'Geometry', '2D Shapes'))
            self.assertNotIn('needs_review', q)

    def test_a_blank_question_text_gets_the_standard_wording(self):
        q = _shape(question_text='  ')
        _normalise_name_the_shape([q])
        self.assertEqual(q['question_text'], NAME_THE_SHAPE_TEXT)

    def test_an_embedded_image_counts_as_the_shape_picture(self):
        q = _shape(image_page=None, image_box=None, image_ref='page1_img3.png')
        _normalise_name_the_shape([q])
        self.assertNotIn('needs_review', q)

    def test_a_shape_with_no_picture_is_sent_to_review_not_saved_blind(self):
        no_box = _shape(image_page=None, image_box=None)
        half_box = _shape(image_box={'x1': 10, 'y1': 10})
        _normalise_name_the_shape([no_box, half_box])
        for q in (no_box, half_box):
            self.assertTrue(q['needs_review'])
            self.assertIn('no box', q['review_reason'])
            self.assertEqual(q['question_type'], 'multiple_choice')   # still normalised

    def test_not_exactly_one_correct_option_is_sent_to_review(self):
        two = _shape(answers=[{'text': 'Square', 'is_correct': True},
                              {'text': 'Rectangle', 'is_correct': True}])
        none = _shape(answers=[{'text': 'Square', 'is_correct': False},
                               {'text': 'Rectangle', 'is_correct': False}])
        _normalise_name_the_shape([two, none])
        self.assertIn('2 options are ticked correct', two['review_reason'])
        self.assertIn('0 options are ticked correct', none['review_reason'])

    def test_an_existing_review_reason_is_kept(self):
        q = _shape(image_page=None, image_box=None,
                   needs_review=True, review_reason='GPT disagreed.')
        _normalise_name_the_shape([q])
        self.assertTrue(q['review_reason'].startswith('GPT disagreed.'))
        self.assertIn('Name-the-shape item', q['review_reason'])

    def test_explicit_classification_is_not_overwritten(self):
        q = _shape(topic='3D Shapes')
        _normalise_name_the_shape([q])
        self.assertEqual(q['topic'], '3D Shapes')

    def test_nothing_to_do_is_a_no_op(self):
        self.assertEqual(_normalise_name_the_shape(None), 0)
        self.assertEqual(_normalise_name_the_shape(['not a dict', {}]), 0)


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
        block.name = 'classify_questions'
        block.input = self.payload
        resp = MagicMock(stop_reason='tool_use')
        resp.content = [block]
        resp.usage.input_tokens = 1
        resp.usage.output_tokens = 1
        return resp


class ClassifyNormalisesShapesTests(SimpleTestCase):
    """The type never leaves classify_questions: by the time the preview, the
    figure guard or the save path sees the questions they are multiple choice."""

    def test_a_shape_item_from_the_model_reaches_the_caller_as_multiple_choice(self):
        payload = {'year_level': 2, 'subject': 'Mathematics', 'strand': 'Geometry',
                   'topic': '2D Shapes',
                   'questions': [_shape(), {'question_text': '3 + 4 =', 'question_type':
                                            'short_answer', 'source_page': 1,
                                            'answers': [{'text': '7', 'is_correct': True}]}]}
        client = MagicMock()
        client.messages.stream.side_effect = lambda **kw: _ToolStream(payload)
        with patch('ai_import.services._get_anthropic_client', return_value=client), \
                patch('ai_import.verification.verify_answers', return_value=None):
            result = classify_questions(
                {'pages': [{'page_num': 1, 'screenshot': 'x', 'text': '', 'images': []}],
                 'page_count': 1}, [], [])

        shape, plain = result['questions']
        self.assertEqual(shape['question_type'], 'multiple_choice')
        self.assertTrue(shape['shape_naming'])
        self.assertEqual(shape['question_text'], NAME_THE_SHAPE_TEXT)
        self.assertEqual(plain['question_type'], 'short_answer')
        self.assertNotIn('shape_naming', plain)
        self.assertNotIn('needs_review', shape)


class PickThePicturedItemGuardTests(SimpleTestCase):
    """Rule 5b's safety net: the guard that already runs in ai_import.tasks
    catches a "tick the cylinder" that still arrived without its picture."""

    def test_a_figureless_tick_the_shape_question_is_flagged(self):
        q = {'question_text': 'Tick the cylinder.', 'question_type': 'multiple_choice',
             'source_page': 2, 'answers': [{'text': 'The first shape', 'is_correct': False},
                                           {'text': 'The second shape', 'is_correct': True}]}
        self.assertEqual(flag_missing_figures([q]), 1)
        self.assertTrue(q['needs_review'])
        self.assertIn('no image was attached', q['review_reason'])

    def test_the_same_question_with_its_picture_is_not_flagged(self):
        q = {'question_text': 'Tick the cylinder.', 'question_type': 'multiple_choice',
             'source_page': 2, 'image_page': 2,
             'image_box': {'x1': 5, 'y1': 40, 'x2': 95, 'y2': 60}}
        self.assertEqual(flag_missing_figures([q]), 0)
        self.assertNotIn('needs_review', q)


class PreviewBadgeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = CustomUser.objects.create_superuser('aishape', 'aishape@x.com', 'pw')
        cls.school = School.objects.create(name='S', slug='aishapes', admin=cls.user)

    def test_a_normalised_shape_shows_the_badge_and_a_plain_question_does_not(self):
        session = AIImportSession.objects.create(
            user=self.user, school=self.school, pdf_filename='shapes.pdf',
            status=AIImportSession.STATUS_READY, page_count=1, is_confirmed=False,
            extracted_data={
                'year_level': 2, 'subject': 'Mathematics', 'strand': 'Geometry',
                'topic': '2D Shapes',
                'questions': [
                    {'question_text': NAME_THE_SHAPE_TEXT, 'question_type': 'multiple_choice',
                     'shape_naming': True, 'difficulty': 1, 'points': 1, 'include': True,
                     'answers': [{'text': 'Triangle', 'is_correct': True},
                                 {'text': 'Square', 'is_correct': False}]},
                    {'question_text': '3 + 4 =', 'question_type': 'short_answer',
                     'difficulty': 1, 'points': 1, 'include': True},
                ],
            },
        )
        self.client.force_login(self.user)
        html = self.client.get(reverse('ai_import:preview', args=[session.pk])).content.decode()
        self.assertIn('data-testid="shape-badge-0"', html)
        self.assertIn('🔷 Name the shape', html)
        self.assertNotIn('data-testid="shape-badge-1"', html)
