"""Figure geometry on ROTATED pages in the AI import.

PyMuPDF reports drawings, words and image placements in the unrotated
content-stream space while the model's boxes are drawn on the displayed
screenshot. Without mapping between them a rotated full-page scan was
labelled "x 0–141%" of its page and a drawn figure was looked for in the
wrong place. Synthetic rotated pages; no tokens.
"""
import io

import fitz
from PIL import Image

from ai_import.services import (
    _box_has_drawing,
    _embedded_image_bbox_pct,
    _expand_box_for_clipped_labels,
    _page_figure_regions,
)
from worksheets.pdf_geometry import displayed_rect


def _reopen(doc):
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype='pdf')


def _rotated_page(rotation=90):
    doc = fitz.open()
    page = doc.new_page(width=800, height=500)
    page.draw_rect(fitz.Rect(50, 60, 250, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_text((260, 130), '23.9 km', fontsize=12)   # label just right of the figure
    page.set_rotation(rotation)
    return _reopen(doc)


def _rotated_scan_page(rotation=270):
    buf = io.BytesIO()
    Image.new('RGB', (1600, 1000), (128, 128, 128)).save(buf, format='PNG')
    doc = fitz.open()
    page = doc.new_page(width=800, height=500)
    page.insert_image(page.rect, stream=buf.getvalue())
    page.set_rotation(rotation)
    return _reopen(doc)


def test_embedded_image_bbox_stays_inside_the_displayed_page():
    doc = _rotated_scan_page()
    page = doc[0]
    xref = page.get_images(full=True)[0][0]
    assert _embedded_image_bbox_pct(page, xref) == [0.0, 0.0, 100.0, 100.0]


def test_figure_regions_are_reported_where_the_figure_is_displayed():
    doc = _rotated_page()
    page = doc[0]
    shown = displayed_rect(page, page.get_drawings()[0]['rect'])
    pw, ph = page.rect.width, page.rect.height
    regions = _page_figure_regions(page)
    assert len(regions) == 1
    x0, y0, x1, y1 = regions[0]
    assert abs(x0 - shown.x0 / pw * 100) < 1 and abs(y0 - shown.y0 / ph * 100) < 1
    assert abs(x1 - shown.x1 / pw * 100) < 1 and abs(y1 - shown.y1 / ph * 100) < 1


def test_box_has_drawing_uses_displayed_coordinates():
    doc = _rotated_page()
    page = doc[0]
    raw = fitz.Rect(page.get_drawings()[0]['rect'])
    shown = displayed_rect(page, raw)
    pw, ph = page.rect.width, page.rect.height
    as_pct = lambda r: [r.x0 / pw * 100, r.y0 / ph * 100, r.x1 / pw * 100, r.y1 / ph * 100]
    assert _box_has_drawing(doc, 1, as_pct(shown)) is True
    # The raw (unrotated) location holds nothing on the displayed page.
    assert _box_has_drawing(doc, 1, as_pct(raw)) is False


def test_clipped_label_growth_follows_the_rotation():
    doc = _rotated_page()
    page = doc[0]
    pw, ph = page.rect.width, page.rect.height
    figure = displayed_rect(page, page.get_drawings()[0]['rect'])
    word = displayed_rect(page, fitz.Rect(page.get_text('words')[0][:4]))
    # A box around the figure that slices the label roughly in half.
    mid = (word.y0 + word.y1) / 2 if word.height > word.width else word.y1
    box = fitz.Rect(min(figure.x0, word.x0), figure.y0,
                    max(figure.x1, word.x1), max(figure.y1, mid))
    if not box.intersects(word) or box.contains(word):
        box = fitz.Rect(figure) | fitz.Rect(word.x0, word.y0, word.x1, (word.y0 + word.y1) / 2)
    pct = [box.x0 / pw * 100, box.y0 / ph * 100, box.x1 / pw * 100, box.y1 / ph * 100]
    grown = _expand_box_for_clipped_labels(doc, 1, pct)
    grown_rect = fitz.Rect(grown[0] / 100 * pw, grown[1] / 100 * ph,
                           grown[2] / 100 * pw, grown[3] / 100 * ph)
    assert grown_rect.contains(word)
