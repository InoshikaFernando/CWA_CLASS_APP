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
    _resolve_image_ref,
    _snap_box_to_figures,
    classify_questions,
    crop_figure_boxes,
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


class ResolveImageRefTests(SimpleTestCase):
    """_resolve_image_ref tolerates the extension the model often omits."""

    POOL = {'page3_img1.png': 'b64a', 'page5_img1.jpeg': 'b64b', 'page21_figure74.png': 'b64c'}

    def test_exact_match(self):
        self.assertEqual(_resolve_image_ref('page3_img1.png', self.POOL), 'page3_img1.png')

    def test_missing_extension_resolves_to_real_key(self):
        # Regression: the model returns "page3_img1"; the pool key is "...png".
        self.assertEqual(_resolve_image_ref('page3_img1', self.POOL), 'page3_img1.png')
        self.assertEqual(_resolve_image_ref('page5_img1', self.POOL), 'page5_img1.jpeg')

    def test_wrong_extension_resolves_by_stem(self):
        self.assertEqual(_resolve_image_ref('page5_img1.png', self.POOL), 'page5_img1.jpeg')

    def test_crop_ref_matches(self):
        self.assertEqual(_resolve_image_ref('page21_figure74', self.POOL), 'page21_figure74.png')

    def test_unknown_ref_returns_none(self):
        self.assertIsNone(_resolve_image_ref('page9_img1', self.POOL))
        self.assertIsNone(_resolve_image_ref(None, self.POOL))
        self.assertIsNone(_resolve_image_ref('page3_img1', {}))


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

    def test_each_batch_questions_keep_their_own_defaults(self):
        # Batch 1 default topic = Number, batch 2 = Geometry; each batch's
        # questions omit per-question topic. After merge, batch-2 questions must
        # carry Geometry, not inherit batch-1's Number.
        calls = {'n': 0}

        def fake_batch(client, system_prompt, pages, total_page_count):
            calls['n'] += 1
            topic = 'Number' if calls['n'] == 1 else 'Geometry'
            return {
                'year_level': 5, 'subject': 'Mathematics', 'strand': 'N', 'topic': topic,
                'questions': [
                    {'question_text': f'p{p["page_num"]}', 'question_type': 'short_answer',
                     'difficulty': 1, 'answers': []}
                    for p in pages
                ],
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
            }

        extracted = {
            'page_count': 25,
            'pages': [{'page_num': n, 'text': '', 'images': [], 'screenshot': ''}
                      for n in range(1, 26)],
            'all_text': '',
        }
        orig = (services._classify_page_batch, services._get_anthropic_client,
                services._build_classification_prompt)
        services._classify_page_batch = fake_batch
        services._get_anthropic_client = lambda: object()
        services._build_classification_prompt = lambda t, l: 'sys'
        try:
            result = classify_questions(extracted, [], [])
        finally:
            (services._classify_page_batch, services._get_anthropic_client,
             services._build_classification_prompt) = orig

        topics = [q['topic'] for q in result['questions']]
        self.assertEqual(topics[:20], ['Number'] * 20)   # batch 1 (pages 1-20)
        self.assertEqual(topics[20:], ['Geometry'] * 5)  # batch 2 (pages 21-25)

    def test_explicit_per_question_field_not_overwritten(self):
        # A per-question topic the model DID set must survive the default stamping.
        def fake_batch(client, system_prompt, pages, total_page_count):
            return {
                'year_level': 5, 'subject': 'Mathematics', 'strand': 'N', 'topic': 'Number',
                'questions': [
                    {'question_text': 'q', 'question_type': 'short_answer', 'difficulty': 1,
                     'answers': [], 'topic': 'Fractions'}
                ],
                'usage': {'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
            }

        extracted = {'page_count': 1, 'pages': [{'page_num': 1, 'text': '', 'images': [],
                                                 'screenshot': ''}], 'all_text': ''}
        orig = (services._classify_page_batch, services._get_anthropic_client,
                services._build_classification_prompt)
        services._classify_page_batch = fake_batch
        services._get_anthropic_client = lambda: object()
        services._build_classification_prompt = lambda t, l: 'sys'
        try:
            result = classify_questions(extracted, [], [])
        finally:
            (services._classify_page_batch, services._get_anthropic_client,
             services._build_classification_prompt) = orig

        self.assertEqual(result['questions'][0]['topic'], 'Fractions')


class SnapBoxToFiguresTests(SimpleTestCase):
    """_snap_box_to_figures refines an AI box onto detected vector-figure bounds."""

    def test_no_regions_returns_box_unchanged(self):
        box = [10, 10, 40, 40]
        self.assertEqual(_snap_box_to_figures(box, []), box)

    def test_non_overlapping_region_ignored(self):
        box = [10, 10, 40, 40]
        # Region far away (bottom-right) — no overlap, box kept.
        self.assertEqual(_snap_box_to_figures(box, [[70, 70, 90, 90]]), box)

    def test_too_loose_box_shrinks_to_figure(self):
        # Box runs from 10% to 90% down the page (grabbing the next question),
        # but the figure only occupies 12–40%. Snap should pull the bottom up.
        snapped = _snap_box_to_figures([5, 10, 60, 90], [[12, 12, 50, 40]])
        # Padded figure bounds (pad=2): [10, 10, 52, 42].
        self.assertAlmostEqual(snapped[3], 42, places=5)
        self.assertLess(snapped[3], 90)

    def test_too_tight_box_expands_to_figure(self):
        # Box clips the figure (only its lower half); snap expands to full figure.
        snapped = _snap_box_to_figures([20, 30, 45, 38], [[12, 12, 50, 40]])
        self.assertLessEqual(snapped[1], 12)   # top expanded up to (padded) figure top
        self.assertGreaterEqual(snapped[2], 50)

    def test_clamped_to_page_bounds(self):
        snapped = _snap_box_to_figures([0, 0, 100, 100], [[1, 1, 99, 50]])
        self.assertGreaterEqual(snapped[0], 0)
        self.assertLessEqual(snapped[2], 100)

    def test_tiny_fragment_does_not_collapse_crop(self):
        # A fragmented figure (one small overlapping speck) vs a large model box:
        # snapping would shrink it to a sliver, so the model box is kept.
        box = [5, 70, 95, 88]            # a wide number-line box
        fragment = [34, 77, 36, 82]      # one stray tick the clusterer split off
        self.assertEqual(_snap_box_to_figures(box, [fragment]), box)


class CropUsesFigureRegionsTests(SimpleTestCase):
    """crop_figure_boxes snaps to figure_regions when extraction provides them."""

    @staticmethod
    def _screenshot_b64(w, h):
        buf = io.BytesIO()
        Image.new('RGB', (w, h), (255, 255, 255)).save(buf, format='JPEG')
        return base64.b64encode(buf.getvalue()).decode('utf-8')

    def test_crop_snaps_to_region(self):
        # 1000x1000 page. Loose box covers the bottom 90%, but the figure region
        # is only the top quarter. Crop must follow the (padded) region, not the box.
        page = {'page_num': 1, 'screenshot': self._screenshot_b64(1000, 1000),
                'figure_regions': [[10, 10, 50, 30]]}
        q = {'image_page': 1, 'image_box': {'x1': 5, 'y1': 5, 'x2': 60, 'y2': 95}}
        crops = crop_figure_boxes({'pages': [page]}, {'questions': [q]})
        img = Image.open(io.BytesIO(base64.b64decode(crops[q['image_ref']])))
        # Padded region [8,8,52,32] of 1000px → ~440 wide x ~240 tall, NOT 550x900.
        self.assertLess(img.size[1], 400)
        self.assertAlmostEqual(img.size[0], 440, delta=4)
        self.assertAlmostEqual(img.size[1], 240, delta=4)

    def test_no_regions_keeps_model_box(self):
        # Without figure_regions the model box is honoured exactly (back-compat).
        page = {'page_num': 1, 'screenshot': self._screenshot_b64(1000, 1000)}
        q = {'image_page': 1, 'image_box': {'x1': 0, 'y1': 0, 'x2': 50, 'y2': 50}}
        crops = crop_figure_boxes({'pages': [page]}, {'questions': [q]})
        img = Image.open(io.BytesIO(base64.b64decode(crops[q['image_ref']])))
        self.assertEqual(img.size, (500, 500))
