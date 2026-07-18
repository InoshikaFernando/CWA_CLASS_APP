"""Unit tests for question_source_page — resolving the 1-based page a question
maps to, so the "Adjust image" crop modal opens on the right page.
"""
from django.test import SimpleTestCase

from worksheets.services import question_source_page


class QuestionSourcePageTests(SimpleTestCase):
    def test_explicit_image_page_wins(self):
        q = {'image_page': 4, 'page_num': 2, 'image_ref': 'worksheet_img_q1_p2.png'}
        self.assertEqual(question_source_page(q), 4)

    def test_worksheet_ref_encodes_page(self):
        # No image_page/page_num — recover the page from the ref filename.
        q = {'image_ref': 'worksheet_img_q3_p5.png'}
        self.assertEqual(question_source_page(q), 5)

    def test_ai_import_embedded_ref_encodes_page(self):
        q = {'image_ref': 'page3_img1.png'}
        self.assertEqual(question_source_page(q), 3)

    def test_ai_import_figure_ref_encodes_page(self):
        q = {'image_ref': 'page7_figure2.png'}
        self.assertEqual(question_source_page(q), 7)

    def test_page_num_used_when_no_ref(self):
        q = {'page_num': 6}
        self.assertEqual(question_source_page(q), 6)

    def test_source_page_field(self):
        q = {'source_page': 8}
        self.assertEqual(question_source_page(q), 8)

    def test_ai_import_page_field(self):
        q = {'page': 9}
        self.assertEqual(question_source_page(q), 9)

    def test_ref_page_beats_stale_page_num_fallback(self):
        # A cropped question keeps its true page in the ref even if page_num is absent.
        q = {'image_ref': 'worksheet_img_q2_p3.png', 'source_page': None}
        self.assertEqual(question_source_page(q), 3)

    def test_defaults_to_one(self):
        self.assertEqual(question_source_page({}), 1)
        self.assertEqual(question_source_page({'image_ref': 'orig.png'}), 1)

    def test_zero_and_garbage_are_ignored(self):
        self.assertEqual(question_source_page({'image_page': 0, 'page_num': 2}), 2)
        self.assertEqual(question_source_page({'page_num': 'x', 'page': 3}), 3)
        self.assertEqual(question_source_page({'image_page': None}), 1)

    def test_string_numbers_are_coerced(self):
        self.assertEqual(question_source_page({'image_page': '5'}), 5)
