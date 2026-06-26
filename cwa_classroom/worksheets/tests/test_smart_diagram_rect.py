"""Tests for the smart diagram-crop logic (`_smart_diagram_rect`).

The crop must snap to the actual vector drawing plus its tightly-attached labels
(e.g. the "A B C D" beneath each arrow) while leaving the question sentence that
sits below the diagram outside the frame — that stray text bleeding in was the
bug this logic fixes.
"""
import fitz

from worksheets.services import (
    _region_has_raster_image,
    _smart_diagram_rect,
    _tight_drawings_rect,
    render_question_images,
)


def _pages_meta(page):
    """extracted_pages metadata where screenshot px == PDF pts (scale 1:1),
    so test bboxes can be given directly in PDF points."""
    return {
        'pages': [{
            'page_num': 1,
            'text': page.get_text('text'),
            'screenshot': '',
            'screenshot_w': page.rect.width,
            'screenshot_h': page.rect.height,
            'pdf_w': page.rect.width,
            'pdf_h': page.rect.height,
        }],
        'page_count': 1,
    }


def _doc_with_diagram_labels_and_sentence():
    """A page with a vector diagram, two short labels just below it, and a wide
    question sentence further down.

    Geometry (PDF points, 400×500 page):
      diagram (filled rect)   y ~100–200
      labels  "A" / "B"       baseline y=215  (short, narrow blocks)
      sentence                baseline y=330  (wide running text)
    """
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 100, 280, 200), color=(0, 0, 0), fill=(0.8, 0.8, 0.8))
    page.insert_text((150, 215), "A", fontsize=12)
    page.insert_text((250, 215), "B", fontsize=12)
    page.insert_text(
        (40, 330),
        "An anticlockwise turn of 270 degrees gives the same direction as arrow.",
        fontsize=12,
    )
    return doc, page


def test_keeps_attached_labels_but_drops_sentence():
    doc, page = _doc_with_diagram_labels_and_sentence()
    try:
        # A deliberately over-tall search region (as Claude's rough bbox would be)
        # spanning the diagram, the labels AND the sentence.
        rect = _smart_diagram_rect(page, fitz.Rect(40, 90, 360, 360))
    finally:
        doc.close()

    assert rect is not None
    # The labels (block bottoms ~y217) are absorbed...
    assert rect.y1 >= 210, f'labels should be inside the crop, got y1={rect.y1}'
    # ...but the question sentence (block top ~y320) is excluded.
    assert rect.y1 < 300, f'sentence should be outside the crop, got y1={rect.y1}'


def test_keeps_narrow_label_above_the_diagram():
    """A short label sitting just ABOVE the drawing (e.g. "North", a graph title,
    an axis-max value) is absorbed, not cropped off / redacted."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((150, 108), "N", fontsize=12)  # label baseline just above core
    page.draw_rect(fitz.Rect(120, 120, 200, 220), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    try:
        rect = _smart_diagram_rect(page, fitz.Rect(100, 80, 260, 300))
    finally:
        doc.close()

    assert rect is not None
    # Grew upward past the drawing core (~y114) to include the label (~y97-110).
    assert rect.y0 < 114, f'label above diagram should be kept, got y0={rect.y0}'


def test_wide_header_above_diagram_is_left_out():
    """A wide running-text header above the diagram is NOT absorbed (width filter),
    so it can still be cropped/redacted away."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=400)
    page.insert_text((10, 108),
                     "Find the bearing of B from A in this question here",
                     fontsize=12)  # wide header just above
    page.draw_rect(fitz.Rect(120, 120, 200, 220), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    try:
        rect = _smart_diagram_rect(page, fitz.Rect(0, 80, 300, 300))
    finally:
        doc.close()

    assert rect is not None
    # Crop top stays at the drawing core (~y114), not up at the wide header (~y97).
    assert rect.y0 >= 108, f'wide header must stay out, got y0={rect.y0}'


def test_wide_sentence_is_not_treated_as_a_label():
    """Even when the sentence sits within the gap tolerance, its width marks it
    as running text, so it is never absorbed."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 100, 280, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    # Wide sentence immediately below the diagram (small gap, but full-width).
    page.insert_text(
        (30, 212),
        "This is a long running question sentence that spans most of the page width.",
        fontsize=12,
    )
    try:
        rect = _smart_diagram_rect(page, fitz.Rect(20, 90, 380, 300))
    finally:
        doc.close()

    assert rect is not None
    # Crop stays at the diagram core (~y200 + small margins), not down to the
    # sentence (block bottom ~y214). Anything <= core+margin proves it didn't grow.
    assert rect.y1 <= 211, f'wide text must not extend the crop, got y1={rect.y1}'


def test_returns_none_for_raster_page_without_drawings():
    """No vector drawings → caller falls back to Claude's bbox."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((50, 50), "just some text", fontsize=12)
    try:
        assert _smart_diagram_rect(page, fitz.Rect(0, 0, 300, 300)) is None
    finally:
        doc.close()


def test_core_matches_tight_drawings_when_no_labels():
    """With no nearby text, the smart rect is just the tight drawing bounds
    (plus the small cosmetic margin)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=400)
    page.draw_rect(fitz.Rect(100, 100, 250, 220), color=(0, 0, 0), fill=(0.7, 0.7, 0.7))
    try:
        core = _tight_drawings_rect(page, fitz.Rect(50, 50, 350, 350))
        smart = _smart_diagram_rect(page, fitz.Rect(50, 50, 350, 350))
    finally:
        doc.close()

    assert core is not None and smart is not None
    # Smart rect contains the tight core and is at most a few points larger.
    assert smart.y1 >= core.y1 - 1
    assert smart.y1 <= core.y1 + 6


# ---------------------------------------------------------------------------
# Spurious-image guard: a bbox over plain text (no real figure) is dropped
# ---------------------------------------------------------------------------

def test_region_has_raster_image_true_for_embedded_image():
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 60))
    pix.set_rect(pix.irect, (200, 100, 100))
    page.insert_image(fitz.Rect(50, 50, 250, 250), stream=pix.tobytes('png'))
    try:
        assert _region_has_raster_image(page, fitz.Rect(40, 40, 260, 260)) is True
    finally:
        doc.close()


def test_region_has_raster_image_false_for_text_only():
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((30, 150), "only text here", fontsize=12)
    try:
        assert _region_has_raster_image(page, fitz.Rect(0, 0, 300, 300)) is False
    finally:
        doc.close()


def test_render_drops_spurious_text_only_image():
    """has_image=True but the bbox points at plain text → image is dropped,
    not rendered as a meaningless text crop (the reported bug)."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((40, 200), "from the direction will give the same bearing",
                     fontsize=14)
    result = {'questions': [
        {'has_image': True, 'page_num': 1, 'image_bbox': [30, 150, 380, 260]},
    ]}
    try:
        out, images = render_question_images(doc, _pages_meta(page), result)
    finally:
        doc.close()

    q = out['questions'][0]
    assert q['has_image'] is False
    assert q.get('image_ref') is None
    assert images == {}


def test_render_keeps_real_vector_diagram():
    """A genuine vector diagram in the bbox is rendered and stored."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 150, 280, 250), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    result = {'questions': [
        {'has_image': True, 'page_num': 1, 'image_bbox': [100, 130, 300, 270]},
    ]}
    try:
        out, images = render_question_images(doc, _pages_meta(page), result)
    finally:
        doc.close()

    q = out['questions'][0]
    assert q['has_image'] is True
    assert q['image_ref'] and q['image_ref'] in images
    assert images[q['image_ref']]  # non-empty base64
