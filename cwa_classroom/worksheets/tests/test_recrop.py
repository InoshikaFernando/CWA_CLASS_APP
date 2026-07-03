"""Tests for the manual re-crop core (Adjust-image tool) and the underline
auto-crop fix.

These exercise the pipeline-agnostic helpers that power the teacher "Adjust
image" control: rendering a full page for the modal, re-rendering an exact
boxed region (works for scanned + vector PDFs), plus the thin-rule filter that
stops answer-blank underlines from being mistaken for figures.
"""
import io

import fitz
import pytest
from PIL import Image

from worksheets.services import (
    _tight_drawings_rect,
    recrop_pdf_region,
    render_pdf_page_png,
)


def _pdf_with_rect():
    """A one-page PDF (400x500 pt) with a filled rectangle 'figure' mid-page."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.draw_rect(fitz.Rect(120, 150, 280, 260), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    data = doc.tobytes()
    doc.close()
    return data


# --- render_pdf_page_png -----------------------------------------------------

def test_render_pdf_page_png_returns_png_and_point_dims():
    png, pw, ph = render_pdf_page_png(_pdf_with_rect(), 0, dpi=100)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    assert (round(pw), round(ph)) == (400, 500)          # PDF points, DPI-independent
    w, h = Image.open(io.BytesIO(png)).size
    assert abs(w - round(400 / 72 * 100)) <= 2   # pixels follow DPI
    assert abs(h - round(500 / 72 * 100)) <= 2


# --- recrop_pdf_region -------------------------------------------------------

def test_recrop_renders_exact_fraction_box_at_high_dpi():
    # Box the middle-left region as fractions of the page.
    png = recrop_pdf_region(_pdf_with_rect(), 0, [0.25, 0.25, 0.75, 0.60], dpi=300)
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    w, h = Image.open(io.BytesIO(png)).size
    # 0.50*400pt wide, 0.35*500pt tall, at 300 DPI
    assert abs(w - round(0.50 * 400 / 72 * 300)) <= 2
    assert abs(h - round(0.35 * 500 / 72 * 300)) <= 2


def test_recrop_degenerate_box_raises():
    with pytest.raises(ValueError):
        recrop_pdf_region(_pdf_with_rect(), 0, [0.5, 0.5, 0.5001, 0.5001])


def test_recrop_normalises_swapped_corners():
    a = recrop_pdf_region(_pdf_with_rect(), 0, [0.2, 0.2, 0.8, 0.7])
    b = recrop_pdf_region(_pdf_with_rect(), 0, [0.8, 0.7, 0.2, 0.2])   # swapped
    assert Image.open(io.BytesIO(a)).size == Image.open(io.BytesIO(b)).size


def test_recrop_works_on_a_page_with_no_vectors():
    """Scanned-style page (text/raster only) still re-crops — get_pixmap
    rasterises whatever is on the page, so Adjust works regardless of PDF type."""
    doc = fitz.open()
    page = doc.new_page(width=300, height=300)
    page.insert_text((40, 150), "scanned-style text", fontsize=14)
    data = doc.tobytes()
    doc.close()
    png = recrop_pdf_region(data, 0, [0.05, 0.4, 0.95, 0.6])
    assert png[:8] == b'\x89PNG\r\n\x1a\n'


# --- underline / thin-rule filter -------------------------------------------

def test_thin_horizontal_rule_is_not_treated_as_a_figure():
    """A lone answer-blank underline (thin, wide) must not count as a drawing,
    so a self-contained text question doesn't render a spurious crop."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    # ~1pt tall, 120pt wide filled rule — an underline.
    page.draw_rect(fitz.Rect(60, 150, 180, 151), color=(0, 0, 0), fill=(0, 0, 0))
    try:
        rect = _tight_drawings_rect(page, fitz.Rect(40, 120, 360, 180))
    finally:
        doc.close()
    assert rect is None


def test_real_boxed_figure_still_detected():
    doc = fitz.open()
    page = doc.new_page(width=400, height=300)
    page.draw_rect(fitz.Rect(120, 120, 250, 210), color=(0, 0, 0), fill=(0.7, 0.7, 0.7))
    try:
        rect = _tight_drawings_rect(page, fitz.Rect(80, 90, 320, 250))
    finally:
        doc.close()
    assert rect is not None and rect.height > 10
