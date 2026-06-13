"""Unit tests for the PDF-import robustness fixes:

1. _build_classification_prompt must not crash on its literal "{dividend}" /
   "{divisor}" braces (regression: unescaped f-string braces → NameError).
2. _downscale_embedded_image caps oversized embedded images (avoids Claude's
   2000px many-image limit → HTTP 400).
3. classify_questions batches over ALL pages instead of truncating at 20.
"""
import base64
import io

from django.test import SimpleTestCase
from PIL import Image

from ai_import import services
from ai_import.services import (
    MAX_EMBEDDED_IMAGE_DIM,
    _build_classification_prompt,
    _downscale_embedded_image,
    classify_questions,
)


def _png_bytes(width, height, mode='RGB', colour=(128, 128, 128)):
    buf = io.BytesIO()
    Image.new(mode, (width, height), colour).save(buf, format='PNG')
    return buf.getvalue()


class BuildPromptTests(SimpleTestCase):
    def test_prompt_builds_without_raising(self):
        # Regression: literal {dividend}/{divisor} in the f-string used to raise
        # NameError, killing every import. Must build cleanly with empty inputs.
        prompt = _build_classification_prompt([], [])
        self.assertIsInstance(prompt, str)

    def test_literal_placeholders_survive_verbatim(self):
        # The long-division instruction must still show the {dividend}/{divisor}
        # tokens to the model (they're literal guidance, not interpolated values).
        prompt = _build_classification_prompt(
            [{'name': 'Fractions', 'slug': 'fractions'}],
            [{'level_number': 5, 'display_name': 'Year 5'}],
        )
        self.assertIn('{dividend}', prompt)
        self.assertIn('{divisor}', prompt)
        # Real interpolations still happen.
        self.assertIn('Fractions', prompt)
        self.assertIn('Year 5', prompt)


class DownscaleEmbeddedImageTests(SimpleTestCase):
    def test_small_image_returned_unchanged(self):
        raw = _png_bytes(100, 80)
        out, ext = _downscale_embedded_image(raw, 'png')
        self.assertEqual(out, raw)
        self.assertEqual(ext, 'png')

    def test_large_image_capped_to_limit(self):
        raw = _png_bytes(3000, 2000)
        out, ext = _downscale_embedded_image(raw, 'png')
        self.assertLess(len(out), len(raw))
        im = Image.open(io.BytesIO(out))
        self.assertLessEqual(max(im.size), MAX_EMBEDDED_IMAGE_DIM)
        # Aspect ratio preserved (3:2).
        self.assertEqual(im.size, (MAX_EMBEDDED_IMAGE_DIM, round(MAX_EMBEDDED_IMAGE_DIM * 2 / 3)))

    def test_large_non_png_reencodes_to_jpeg(self):
        raw = _png_bytes(3000, 2000)
        _, ext = _downscale_embedded_image(raw, 'jpeg')
        self.assertEqual(ext, 'jpeg')

    def test_undecodable_bytes_returned_unchanged(self):
        out, ext = _downscale_embedded_image(b'not an image', 'png')
        self.assertEqual(out, b'not an image')
        self.assertEqual(ext, 'png')


class _FakeUsage:
    def __init__(self, i, o):
        self.input_tokens = i
        self.output_tokens = o


class ClassifyBatchingTests(SimpleTestCase):
    """classify_questions must process every page, not just the first 20."""

    def _patch_batch(self, recorder):
        """Replace _classify_page_batch with a stub that records batch sizes and
        returns one question per page in the batch."""
        def fake_batch(client, system_prompt, pages, total_page_count):
            recorder.append([p['page_num'] for p in pages])
            return {
                'year_level': 5, 'subject': 'Mathematics', 'strand': 'Number',
                'topic': 'General',
                'questions': [
                    {'question_text': f'Q for page {p["page_num"]}',
                     'question_type': 'short_answer', 'difficulty': 1,
                     'answers': []}
                    for p in pages
                ],
                'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
            }
        return fake_batch

    def _run(self, page_count, monkey_env=None):
        extracted = {
            'page_count': page_count,
            'pages': [{'page_num': n, 'text': '', 'images': [], 'screenshot': ''}
                      for n in range(1, page_count + 1)],
            'all_text': '',
        }
        batches = []
        orig_batch = services._classify_page_batch
        orig_client = services._get_anthropic_client
        orig_prompt = services._build_classification_prompt
        services._classify_page_batch = self._patch_batch(batches)
        services._get_anthropic_client = lambda: object()
        services._build_classification_prompt = lambda t, l: 'sys'
        try:
            result = classify_questions(extracted, [], [])
        finally:
            services._classify_page_batch = orig_batch
            services._get_anthropic_client = orig_client
            services._build_classification_prompt = orig_prompt
        return result, batches

    def test_all_pages_covered_beyond_20(self):
        result, batches = self._run(35)
        # 35 pages, default chunk 20 → batches of 20 + 15.
        self.assertEqual([len(b) for b in batches], [20, 15])
        # Every page 1..35 is represented exactly once.
        seen = sorted(p for b in batches for p in b)
        self.assertEqual(seen, list(range(1, 36)))
        # One merged question per page.
        self.assertEqual(len(result['questions']), 35)

    def test_usage_is_summed_across_batches(self):
        result, batches = self._run(35)
        self.assertEqual(len(batches), 2)
        self.assertEqual(result['usage']['input_tokens'], 20)   # 10 per batch
        self.assertEqual(result['usage']['output_tokens'], 10)  # 5 per batch
        self.assertEqual(result['usage']['total_tokens'], 30)

    def test_single_batch_for_short_pdf(self):
        result, batches = self._run(8)
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(result['questions']), 8)
