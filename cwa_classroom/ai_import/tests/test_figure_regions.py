"""_page_figure_regions: detect drawn-figure clusters, excluding the page border.

Regression for the G9-Trigonometry bug where a faint full-page border bridged a
grid of separate triangles into one page-sized cluster that the >80%-area filter
then discarded — leaving zero figure regions on a page full of diagrams.
"""
import fitz
from django.test import SimpleTestCase

from ai_import.services import _page_figure_regions

W, H = 600.0, 800.0


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
