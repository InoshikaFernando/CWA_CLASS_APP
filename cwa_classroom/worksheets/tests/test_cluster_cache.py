"""Drawing clusters are computed once per page per render run.

``cluster_drawings()`` walks every path on a page — ~0.8 s on a textbook page
with 10,000 decorative paths — and the crop path used to call it two or three
times per figure. A 13-page algebra booklet spent 36 s of its render phase
re-clustering the same four pages. Now one clustering per page serves every
figure on it; the re-crop tool and ai_import, which pass no cache, still get
the clusters computed on demand.
"""
from unittest.mock import patch

import fitz

from worksheets import services


def _pdf_with_two_figures():
    doc = fitz.open()
    page = doc.new_page(width=400, height=600)
    page.draw_rect(fitz.Rect(50, 50, 150, 120), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.draw_rect(fitz.Rect(50, 300, 150, 380), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.insert_text((60, 500), 'plain text only', fontsize=12)
    return doc


def test_a_page_is_clustered_once_however_many_figures_it_has():
    doc = _pdf_with_two_figures()
    try:
        pages = services.extract_worksheet_pages(doc)
        p = pages['pages'][0]
        sx, sy = p['screenshot_w'] / p['pdf_w'], p['screenshot_h'] / p['pdf_h']
        boxes = [(40, 40, 160, 130), (40, 290, 160, 390), (40, 480, 300, 520)]
        result = {'questions': [
            {'question_text': f'q{i}', 'has_image': True, 'page_num': 1,
             'image_bbox': [x0 * sx, y0 * sy, x1 * sx, y1 * sy]}
            for i, (x0, y0, x1, y1) in enumerate(boxes)
        ]}
        real = fitz.Page.cluster_drawings
        with patch.object(fitz.Page, 'cluster_drawings', autospec=True,
                          side_effect=real) as spy:
            result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()

    # Two real figures cropped, the text-only box dropped — same outcome as before…
    assert len(images) == 2
    assert result['questions'][2]['has_image'] is False
    # …from ONE clustering of the page, not one (or more) per figure.
    assert spy.call_count == 1


def test_helpers_still_cluster_on_demand_without_a_cache():
    doc = _pdf_with_two_figures()
    try:
        page = doc[0]
        assert services._tight_drawings_rect(page, fitz.Rect(40, 40, 160, 130)) is not None
        assert services._region_has_drawing(page, fitz.Rect(40, 290, 160, 390)) is True
        assert services._region_has_drawing(page, fitz.Rect(40, 480, 300, 520)) is False
        cache = {}
        first = services._page_clusters(page, cache)
        assert services._page_clusters(page, cache) is first
        assert list(cache) == [0]
    finally:
        doc.close()
