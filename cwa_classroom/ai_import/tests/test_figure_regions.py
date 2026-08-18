"""_page_figure_regions: detect drawn-figure clusters, excluding the page border.

Regression for the G9-Trigonometry bug where a faint full-page border bridged a
grid of separate triangles into one page-sized cluster that the >80%-area filter
then discarded — leaving zero figure regions on a page full of diagrams.
"""
import fitz
from django.test import SimpleTestCase

from ai_import.services import (
    _expand_box_for_clipped_labels, _page_figure_regions,
)

W, H = 600.0, 800.0


def _word_bbox(page, text):
    for w in page.get_text('words'):
        if w[4] == text:
            return w[0], w[1], w[2], w[3]
    raise AssertionError(f'word {text!r} not found on page')


def _page(rects):
    """A single PDF page (kept alive by the returned doc) with each rect stroked."""
    doc = fitz.open()
    page = doc.new_page(width=W, height=H)
    for r in rects:
        page.draw_rect(fitz.Rect(*r), color=(0, 0, 0), width=1)
    return doc, page


class PageFigureRegionsTests(SimpleTestCase):
    def test_full_page_border_alone_yields_no_region(self):
        # A near-full-page rectangle is the page border, not a figure.
        doc, page = _page([(10, 10, W - 10, H - 10)])
        try:
            self.assertEqual(_page_figure_regions(page), [])
        finally:
            doc.close()

    def test_border_does_not_swallow_separate_figures(self):
        # The real bug: a page border plus two well-separated figures. The border
        # must be excluded so the figures cluster on their own instead of merging
        # into one page-sized blob that gets dropped.
        doc, page = _page([
            (8, 8, W - 8, H - 8),      # page border
            (60, 60, 180, 180),        # figure top-left
            (420, 620, 540, 740),      # figure bottom-right
        ])
        try:
            regions = _page_figure_regions(page)
            # Both figures recovered, and no region is the page-sized border.
            self.assertEqual(len(regions), 2)
            for x0, y0, x1, y1 in regions:
                area_frac = ((x1 - x0) / 100) * ((y1 - y0) / 100)
                self.assertLess(area_frac, 0.80)
        finally:
            doc.close()

    def test_specks_are_ignored(self):
        doc, page = _page([(300, 400, 302, 402)])  # ~0.3% x 0.25%
        try:
            self.assertEqual(_page_figure_regions(page), [])
        finally:
            doc.close()

    def test_degenerate_page_is_safe(self):
        doc = fitz.open()
        page = doc.new_page(width=0, height=0)
        try:
            self.assertEqual(_page_figure_regions(page), [])
        finally:
            doc.close()


class ExpandBoxForClippedLabelsTests(SimpleTestCase):
    def test_clipped_label_is_pulled_into_the_crop(self):
        # A box that covers most of a label but slices its right edge should grow
        # to contain the whole label (no half-cut "23.9km").
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((100, 100), "23.9km", fontsize=12)
        try:
            wx0, wy0, wx1, wy1 = _word_bbox(page, "23.9km")
            clip_x = wx0 + 0.7 * (wx1 - wx0)          # right 30% outside the box
            box = [(wx0 - 5) / W * 100, (wy0 - 5) / H * 100,
                   clip_x / W * 100, (wy1 + 5) / H * 100]

            out = _expand_box_for_clipped_labels(doc, 1, box)

            ox1 = out[2] / 100 * W
            self.assertGreaterEqual(ox1, wx1 - 0.5)    # right edge now past the word
        finally:
            doc.close()

    def test_neighbour_word_touched_at_edge_is_not_included(self):
        # A box whose edge only nicks the left sliver of a word (a neighbour, not a
        # clipped label) must NOT grow to swallow it.
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((100, 100), "NEIGHBOUR", fontsize=12)
        try:
            wx0, wy0, wx1, wy1 = _word_bbox(page, "NEIGHBOUR")
            clip_x = wx0 + 0.1 * (wx1 - wx0)          # only 10% of the word inside
            box = [(wx0 - 40) / W * 100, (wy0 - 5) / H * 100,
                   clip_x / W * 100, (wy1 + 5) / H * 100]

            out = _expand_box_for_clipped_labels(doc, 1, box)

            self.assertAlmostEqual(out[2], box[2], places=3)   # right edge unchanged
        finally:
            doc.close()

    def test_growth_is_capped(self):
        # A clipped label with a long tail beyond the cap only grows the box by
        # max_grow, never all the way to the far end.
        doc = fitz.open()
        page = doc.new_page(width=W, height=H)
        page.insert_text((80, 100), "AVERYVERYLONGLABELINDEED", fontsize=12)
        try:
            wx0, wy0, wx1, wy1 = _word_bbox(page, "AVERYVERYLONGLABELINDEED")
            clip_x = wx0 + 0.6 * (wx1 - wx0)          # 60% inside → a clipped label
            box = [(wx0 - 2) / W * 100, (wy0 - 2) / H * 100,
                   clip_x / W * 100, (wy1 + 2) / H * 100]

            out = _expand_box_for_clipped_labels(doc, 1, box, max_grow=2.0)

            self.assertLessEqual(out[2], box[2] + 2.0 + 0.01)   # capped
        finally:
            doc.close()

    def test_no_doc_returns_box_unchanged(self):
        box = [10.0, 10.0, 50.0, 50.0]
        self.assertEqual(_expand_box_for_clipped_labels(None, 1, box), box)
