"""Unit tests for question_source_page — resolving the 1-based page a question
maps to, so the "Adjust image" crop modal opens on the right page — and for
answer_review_warning — flagging answer keys that disagree with their explanation.
"""
from django.test import SimpleTestCase

from worksheets.services import answer_review_warning, question_source_page


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


class AnswerReviewWarningTests(SimpleTestCase):
    def test_scratch_work_in_explanation_flags(self):
        # The real failure: explanation reasons correctly but second-guesses, and
        # the ticked answer (Oslo) disagrees with its conclusion (Buenos Aires).
        q = {
            'question_type': 'short_answer',
            'answers': [{'text': 'Oslo', 'is_correct': True}],
            'explanation': ('The differences are: Buenos Aires 45, Oslo 44. Wait — '
                            'Buenos Aires is 45 and Oslo is 44, so Buenos Aires is largest.'),
        }
        self.assertIsNotNone(answer_review_warning(q))

    def test_clean_explanation_does_not_flag(self):
        q = {
            'question_type': 'short_answer',
            'answers': [{'text': 'Buenos Aires', 'is_correct': True}],
            'explanation': 'Buenos Aires has the largest range at 45 degrees.',
        }
        self.assertIsNone(answer_review_warning(q))

    def test_mc_explanation_names_other_option_flags(self):
        q = {
            'question_type': 'multiple_choice',
            'answers': [
                {'text': 'Marrakesh', 'is_correct': True},
                {'text': 'Buenos Aires', 'is_correct': False},
            ],
            'explanation': 'Buenos Aires has the largest temperature range, so it is correct.',
        }
        self.assertIsNotNone(answer_review_warning(q))

    def test_mc_explanation_names_correct_option_ok(self):
        q = {
            'question_type': 'multiple_choice',
            'answers': [
                {'text': 'Buenos Aires', 'is_correct': True},
                {'text': 'Marrakesh', 'is_correct': False},
            ],
            'explanation': 'Buenos Aires has the largest range, so it is correct.',
        }
        self.assertIsNone(answer_review_warning(q))

    def test_short_numeric_options_do_not_false_positive(self):
        # "2" must not be "found" inside "12"; short options are skipped.
        q = {
            'question_type': 'multiple_choice',
            'answers': [
                {'text': '12', 'is_correct': True},
                {'text': '2', 'is_correct': False},
            ],
            'explanation': 'Twelve is the product, so the answer is 12.',
        }
        self.assertIsNone(answer_review_warning(q))

    def test_no_explanation_never_flags(self):
        self.assertIsNone(answer_review_warning({'question_type': 'short_answer', 'explanation': ''}))
        self.assertIsNone(answer_review_warning({'question_type': 'multiple_choice'}))
