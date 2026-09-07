"""Position-aware embedded-image mapping.

The classifier's worst failure on figure-heavy worksheets is attaching the wrong
embedded image to a question when a page holds several look-alike diagrams (e.g. a
2x2 grid of angle figures). The images carry no visual cue to tell them apart, so
the model must map by POSITION. These tests cover the machinery that surfaces each
embedded image's page position to the model:

- extract_pdf_content records each embedded image's bounding box (bbox_pct);
- _embedded_image_label / _position_hint turn that into the text the model sees;
- _classify_page_batch actually sends the position alongside the image;
- the prompt tells the model to map by position, not appearance.
"""
import base64
import io

from django.test import SimpleTestCase
from PIL import Image, ImageDraw

from ai_import import services
from ai_import.services import (
    _build_classification_prompt,
    _classify_page_batch,
    _embedded_image_label,
    _looks_photographic,
    _position_hint,
    extract_pdf_content,
)


class PositionHintTests(SimpleTestCase):
    def test_corners(self):
        self.assertEqual(_position_hint(10, 10), 'top-left')
        self.assertEqual(_position_hint(90, 10), 'top-right')
        self.assertEqual(_position_hint(10, 90), 'bottom-left')
        self.assertEqual(_position_hint(90, 90), 'bottom-right')

    def test_centre_and_edges(self):
        self.assertEqual(_position_hint(50, 50), 'centre')
        self.assertEqual(_position_hint(50, 10), 'top')
        self.assertEqual(_position_hint(50, 90), 'bottom')
        self.assertEqual(_position_hint(10, 50), 'left')
        self.assertEqual(_position_hint(90, 50), 'right')


class EmbeddedImageLabelTests(SimpleTestCase):
    def test_no_bbox_falls_back_to_bare_ref(self):
        # Back-compat: an image with no known position labels exactly as before.
        self.assertEqual(
            _embedded_image_label('page3_img1.png', 3, None),
            '[Embedded image: page3_img1.png]',
        )

    def test_label_carries_position_and_region(self):
        label = _embedded_image_label('page3_img1.png', 3, [11, 13, 47, 30])
        self.assertIn('page3_img1.png', label)
        self.assertIn('page 3', label)
        self.assertIn('x 11-47%', label)
        self.assertIn('y 13-30%', label)
        self.assertIn('top-left', label)

    def test_small_image_flagged_as_marker(self):
        # A little angle-arc glyph (7%x4%) must be flagged so the model skips it.
        label = _embedded_image_label('page17_img5.png', 17, [22, 24, 29, 28])
        self.assertIn('decorative marker', label)

    def test_full_figure_not_flagged(self):
        label = _embedded_image_label('page3_img1.png', 3, [11, 13, 47, 30])
        self.assertNotIn('decorative marker', label)
        self.assertNotIn('whole page', label)

    def test_full_page_background_flagged(self):
        # A 100%x100% embedded image is a scanned page / poster background, never a
        # single question's figure — flag it so the model doesn't attach it.
        label = _embedded_image_label('page2_img1.jpeg', 2, [0, 0, 100, 100])
        self.assertIn('covers the whole page', label)

    def test_wide_real_figure_not_flagged_as_background(self):
        # The widest genuine figures (e.g. 84%x29%) must NOT trip the full-page
        # flag — only images large in BOTH dimensions do.
        label = _embedded_image_label('page9_img3.png', 9, [6, 12, 90, 41])
        self.assertNotIn('whole page', label)
        self.assertNotIn('decorative marker', label)

    def test_photo_flag_surfaces_in_label(self):
        # A mid-sized image detected as photographic is called out so the model
        # doesn't attach it in place of the real diagram.
        label = _embedded_image_label('page7_img1.jpeg', 7, [10, 5, 45, 35],
                                      photo_like=True)
        self.assertIn('photo / decorative illustration', label)

    def test_photo_flag_surfaces_without_bbox(self):
        # Back-compat path (no known position) still carries the photo warning.
        label = _embedded_image_label('page7_img1.jpeg', 7, None, photo_like=True)
        self.assertIn('photo / decorative illustration', label)

    def test_photo_flag_absent_when_not_photographic(self):
        label = _embedded_image_label('page3_img1.png', 3, [11, 13, 47, 30],
                                      photo_like=False)
        self.assertNotIn('photo / decorative illustration', label)

    def test_small_marker_flag_wins_over_photo(self):
        # A tiny image is a decorative marker regardless of the photo signal — the
        # more specific marker note is kept, not doubled up with the photo note.
        label = _embedded_image_label('page7_img5.png', 7, [22, 24, 29, 28],
                                      photo_like=True)
        self.assertIn('decorative marker', label)
        self.assertNotIn('photo / decorative illustration', label)


class LooksPhotographicTests(SimpleTestCase):
    """`_looks_photographic` separates continuous-tone photos / illustrations
    (attach only for a genuine picture question) from maths line-figures."""

    def _png_bytes(self, im):
        buf = io.BytesIO()
        im.save(buf, format='PNG')
        return buf.getvalue()

    def test_continuous_tone_illustration_flagged(self):
        # A full-bleed RGB gradient — no white background, hundreds of tones —
        # stands in for a decorative photo / painted illustration.
        im = Image.new('RGB', (80, 80))
        im.putdata([
            (x * 255 // 80, y * 255 // 80, 128)
            for y in range(80) for x in range(80)
        ])
        self.assertTrue(_looks_photographic(self._png_bytes(im)))

    def test_line_diagram_not_flagged(self):
        # White page with a few black strokes — the shape of a real maths figure.
        im = Image.new('RGB', (200, 200), (255, 255, 255))
        d = ImageDraw.Draw(im)
        d.line((20, 180, 180, 20), fill=(0, 0, 0), width=3)
        d.arc((40, 40, 160, 160), 0, 120, fill=(0, 0, 0), width=3)
        self.assertFalse(_looks_photographic(self._png_bytes(im)))

    def test_flat_colour_chart_on_white_not_flagged(self):
        # A colourful bar chart is flat fills on white — colourful but NOT a photo.
        im = Image.new('RGB', (200, 200), (255, 255, 255))
        d = ImageDraw.Draw(im)
        for i, colour in enumerate([(200, 20, 20), (20, 160, 40), (30, 60, 200)]):
            d.rectangle((20 + i * 55, 60, 60 + i * 55, 180), fill=colour)
        self.assertFalse(_looks_photographic(self._png_bytes(im)))

    def test_unreadable_bytes_are_not_flagged(self):
        self.assertFalse(_looks_photographic(b'not an image'))


class ExtractAttachesBboxTests(SimpleTestCase):
    """extract_pdf_content tags each embedded image with its page position."""

    def _pdf_with_image_at(self, page_w, page_h, rect, image=None):
        import fitz

        doc = fitz.open()
        page = doc.new_page(width=page_w, height=page_h)
        # A small solid PNG placed at `rect` on the page (unless a richer image
        # is supplied — e.g. a continuous-tone gradient standing in for a photo).
        buf = io.BytesIO()
        (image or Image.new('RGB', (40, 30), (200, 20, 20))).save(buf, format='PNG')
        page.insert_image(fitz.Rect(*rect), stream=buf.getvalue())
        pdf_bytes = doc.tobytes()
        doc.close()
        return io.BytesIO(pdf_bytes)

    def test_bbox_pct_reflects_placement(self):
        # 200x400 page, image placed top-left. The rect matches the image's 4:3
        # aspect ratio so PyMuPDF doesn't letterbox it inside the rect.
        pdf = self._pdf_with_image_at(200, 400, (20, 40, 100, 100))
        extracted = extract_pdf_content(pdf)
        imgs = extracted['pages'][0]['images']
        self.assertEqual(len(imgs), 1)
        bbox = imgs[0]['bbox_pct']
        self.assertIsNotNone(bbox)
        x0, y0, x1, y1 = bbox
        # 20/200=10%, 40/400=10%, 100/200=50%, 100/400=25%.
        self.assertAlmostEqual(x0, 10, delta=1)
        self.assertAlmostEqual(y0, 10, delta=1)
        self.assertAlmostEqual(x1, 50, delta=1)
        self.assertAlmostEqual(y1, 25, delta=1)
        # A flat solid image is not photographic.
        self.assertFalse(imgs[0]['photo_like'])

    def test_photo_like_set_for_continuous_tone_image(self):
        # A full-bleed gradient embedded on the page is tagged photo_like so the
        # classifier is warned off attaching it as a question's figure.
        grad = Image.new('RGB', (80, 60))
        grad.putdata([
            (x * 255 // 80, y * 255 // 60, 128)
            for y in range(60) for x in range(80)
        ])
        pdf = self._pdf_with_image_at(200, 400, (20, 40, 100, 100), image=grad)
        imgs = extract_pdf_content(pdf)['pages'][0]['images']
        self.assertEqual(len(imgs), 1)
        self.assertTrue(imgs[0]['photo_like'])


class _FakeUsage:
    input_tokens = 10
    output_tokens = 5


class _FakeBlock:
    type = 'tool_use'
    name = 'classify_questions'

    def __init__(self, payload):
        self.input = payload


class _FakeResponse:
    def __init__(self):
        self.content = [_FakeBlock({
            'year_level': 9, 'subject': 'Mathematics', 'strand': 'Geometry',
            'topic': 'Angles', 'questions': [],
        })]
        self.usage = _FakeUsage()


class _FakeStream:
    def __init__(self, captured):
        self._captured = captured

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def get_final_message(self):
        return _FakeResponse()


class _FakeMessages:
    def __init__(self, captured):
        self._captured = captured

    def stream(self, **kwargs):
        self._captured['messages'] = kwargs['messages']
        return _FakeStream(self._captured)


class _FakeClient:
    def __init__(self, captured):
        self.messages = _FakeMessages(captured)


class ClassifyBatchSendsPositionTests(SimpleTestCase):
    """_classify_page_batch puts each embedded image's position in the request so
    the model can map look-alike figures to the right question."""

    def _text_blocks(self, content):
        return [b['text'] for b in content if b.get('type') == 'text']

    def test_embedded_image_position_reaches_the_model(self):
        captured = {}
        client = _FakeClient(captured)
        pages = [{
            'page_num': 3,
            'text': 'Find the value of each pronumeral.',
            'screenshot': base64.b64encode(b'fakejpeg').decode('utf-8'),
            'images': [
                {'ref': 'page3_img1.png', 'ext': 'png', 'base64': 'AA==',
                 'bbox_pct': [11, 13, 47, 30]},
                {'ref': 'page3_img4.png', 'ext': 'png', 'base64': 'BB==',
                 'bbox_pct': [58, 48, 90, 65]},
            ],
        }]
        _classify_page_batch(client, 'sys', pages, total_page_count=3)

        joined = '\n'.join(self._text_blocks(captured['messages'][0]['content']))
        # Both images announced with their region so the model maps by position.
        self.assertIn('page3_img1.png', joined)
        self.assertIn('top-left', joined)
        self.assertIn('page3_img4.png', joined)
        self.assertIn('bottom-right', joined)


class PromptMappingRuleTests(SimpleTestCase):
    def test_prompt_tells_model_to_map_by_position(self):
        p = _build_classification_prompt([], [])
        self.assertIn('MATCHING THE RIGHT IMAGE', p)
        self.assertIn('POSITION', p)
        # Still keeps the older necessity / neighbour guards.
        self.assertIn('most questions need NO image', p)
        self.assertIn("never a neighbouring question's figure", p)
