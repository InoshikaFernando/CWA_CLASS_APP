"""Unit tests for crop_figure_boxes — cropping drawn figures from page screenshots."""
import base64
import io

from django.test import SimpleTestCase
from PIL import Image

from ai_import.services import crop_figure_boxes


def _screenshot_b64(width=200, height=100, colour=(255, 255, 255)):
    """A solid-colour JPEG screenshot, base64-encoded like extract_pdf_content emits."""
    buf = io.BytesIO()
    Image.new('RGB', (width, height), colour).save(buf, format='JPEG')
    return base64.b64encode(buf.getvalue()).decode('utf-8')


def _extracted(page_num=1, **kw):
    return {'pages': [{'page_num': page_num, 'screenshot': _screenshot_b64(**kw)}]}


class CropFigureBoxesTests(SimpleTestCase):
    def test_crops_box_and_rewrites_image_ref(self):
        # Box covering the left half: x 0-50%, y 0-100% of a 200x100 page.
        q = {'question_text': 'Q', 'image_page': 1,
             'image_box': {'x1': 0, 'y1': 0, 'x2': 50, 'y2': 100}}
        result = {'questions': [q]}

        crops = crop_figure_boxes(_extracted(width=200, height=100), result)

        ref = q['image_ref']
        self.assertIn(ref, crops)
        self.assertTrue(ref.endswith('.png'))
        # Transient locator fields must not survive onto the question.
        self.assertNotIn('image_box', q)
        self.assertNotIn('image_page', q)
        # The crop is the left half: 100x100.
        img = Image.open(io.BytesIO(base64.b64decode(crops[ref])))
        self.assertEqual(img.size, (100, 100))

    def test_normalises_swapped_corners(self):
        # x2<x1 / y2<y1 should be sorted, not produce an empty crop.
        q = {'image_page': 1, 'image_box': {'x1': 50, 'y1': 100, 'x2': 0, 'y2': 0}}
        crops = crop_figure_boxes(_extracted(width=200, height=100), {'questions': [q]})
        img = Image.open(io.BytesIO(base64.b64decode(crops[q['image_ref']])))
        self.assertEqual(img.size, (100, 100))

    def test_clamps_out_of_range_box(self):
        q = {'image_page': 1, 'image_box': {'x1': -10, 'y1': -10, 'x2': 150, 'y2': 150}}
        crops = crop_figure_boxes(_extracted(width=200, height=100), {'questions': [q]})
        img = Image.open(io.BytesIO(base64.b64decode(crops[q['image_ref']])))
        self.assertEqual(img.size, (200, 100))  # clamped to full page

    def test_embedded_image_ref_takes_precedence(self):
        # An existing embedded ref wins; no crop produced, box fields stripped.
        q = {'image_ref': 'page1_img1.png', 'image_page': 1,
             'image_box': {'x1': 0, 'y1': 0, 'x2': 50, 'y2': 50}}
        crops = crop_figure_boxes(_extracted(), {'questions': [q]})
        self.assertEqual(crops, {})
        self.assertEqual(q['image_ref'], 'page1_img1.png')
        self.assertNotIn('image_box', q)
        self.assertNotIn('image_page', q)

    def test_degenerate_box_skipped(self):
        q = {'image_page': 1, 'image_box': {'x1': 10, 'y1': 10, 'x2': 10, 'y2': 10}}
        crops = crop_figure_boxes(_extracted(), {'questions': [q]})
        self.assertEqual(crops, {})
        self.assertNotIn('image_ref', q)

    def test_missing_box_or_page_is_noop(self):
        q = {'question_text': 'no visual'}
        crops = crop_figure_boxes(_extracted(), {'questions': [q]})
        self.assertEqual(crops, {})
        self.assertNotIn('image_ref', q)

    def test_unknown_page_skipped(self):
        q = {'image_page': 9, 'image_box': {'x1': 0, 'y1': 0, 'x2': 50, 'y2': 50}}
        crops = crop_figure_boxes(_extracted(page_num=1), {'questions': [q]})
        self.assertEqual(crops, {})
        self.assertNotIn('image_ref', q)
