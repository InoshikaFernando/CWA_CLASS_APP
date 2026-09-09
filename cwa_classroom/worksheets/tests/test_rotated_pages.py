"""Crops on ROTATED pages, and scans rendered at their own resolution.

A page with a /Rotate entry (a landscape scan stored sideways) is rendered —
``page.rect``, the screenshot, ``get_pixmap(clip=)`` — in displayed
coordinates, but PyMuPDF reports its drawings, text and image placements in
the unrotated content-stream space. The crop path compared the two directly,
so on the rotated mark-scheme pages of a real statistics PDF a figure box in
the bottom third found "no raster image" under it and was dropped as spurious.
``worksheets/pdf_geometry.py`` maps every reported rectangle into displayed
space first; these tests pin that down on synthetic rotated pages (no tokens).
"""
import io

import fitz
from PIL import Image

from worksheets import services
from worksheets.pdf_geometry import displayed_rect, raster_native_dpi


def _grey_png(w=200, h=100):
    buf = io.BytesIO()
    Image.new('RGB', (w, h), (128, 128, 128)).save(buf, format='PNG')
    return buf.getvalue()


def _reopen(doc):
    data = doc.tobytes()
    doc.close()
    return fitz.open(stream=data, filetype='pdf')


def _rotated_vector_page(rotation=90):
    """Landscape 800x500 page with a grey rect and a header above it, rotated."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=500)
    page.insert_text((60, 40), 'Questions', fontsize=14)
    page.draw_rect(fitz.Rect(50, 60, 250, 200), color=(0, 0, 0), fill=(0.5, 0.5, 0.5))
    page.set_rotation(rotation)
    return _reopen(doc)


def _rotated_scan_page(rotation=270):
    """Landscape page entirely covered by one raster image, rotated for display."""
    doc = fitz.open()
    page = doc.new_page(width=800, height=500)
    page.insert_image(page.rect, stream=_grey_png(1600, 1000))   # 144 DPI placement
    page.set_rotation(rotation)
    return _reopen(doc)


def _centre_pixel(pix):
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    return im.getpixel((im.width // 2, im.height // 2))


def _is_grey(px):
    """The 0.5 fill renders as 127 or 128 depending on the rasteriser's rounding."""
    return all(abs(c - 127.5) <= 1 for c in px[:3])


# --- displayed_rect ---------------------------------------------------------

def test_displayed_rect_is_identity_on_an_unrotated_page():
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    assert displayed_rect(page, (10, 20, 30, 40)) == fitz.Rect(10, 20, 30, 40)


def test_displayed_rect_lands_where_the_content_is_rendered():
    doc = _rotated_vector_page()
    page = doc[0]
    raw = page.get_drawings()[0]['rect']
    shown = displayed_rect(page, raw)
    assert shown != fitz.Rect(raw)                  # rotation moved it
    assert _is_grey(_centre_pixel(page.get_pixmap(dpi=72, clip=shown)))
    assert _centre_pixel(page.get_pixmap(dpi=72, clip=raw)) == (255, 255, 255)


# --- the region tests the crop path relies on --------------------------------

def test_tight_drawings_rect_finds_a_figure_on_a_rotated_page():
    doc = _rotated_vector_page()
    page = doc[0]
    shown = displayed_rect(page, page.get_drawings()[0]['rect'])
    search = fitz.Rect(shown.x0 - 20, shown.y0 - 20, shown.x1 + 20, shown.y1 + 20)
    tight = services._tight_drawings_rect(page, search)
    assert tight is not None
    assert tight.contains(shown)


def test_raster_check_sees_the_whole_rotated_scan():
    doc = _rotated_scan_page()
    page = doc[0]
    W, H = page.rect.width, page.rect.height        # displayed: 500 x 800
    assert (round(W), round(H)) == (500, 800)
    bottom_third = fitz.Rect(0.1 * W, 0.72 * H, 0.9 * W, 0.95 * H)
    assert services._region_has_raster_image(page, bottom_third) is True


def test_bleeding_header_is_found_and_redacted_on_a_rotated_page():
    doc = _rotated_vector_page()
    page = doc[0]
    figure = displayed_rect(page, page.get_drawings()[0]['rect'])
    header = displayed_rect(page, fitz.Rect(page.get_text('blocks')[0][:4]))
    # A clip that starts inside the header and covers the figure.
    clip = fitz.Rect(min(figure.x0, header.x0) - 5, (header.y0 + header.y1) / 2,
                     max(figure.x1, header.x1) + 5, figure.y1 + 5)
    bleeding = services._bleeding_text_blocks(page, clip)
    assert len(bleeding) == 1
    pix = services._render_clean_diagram(page, clip, dpi=72)
    im = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
    # The header's half inside the clip is whited out; the figure is still there.
    header_px = im.getpixel((int(header.x0 - clip.x0) + 3, 1))
    assert header_px == (255, 255, 255)
    assert _is_grey(im.getpixel((int((figure.x0 + figure.x1) / 2 - clip.x0),
                                 int((figure.y0 + figure.y1) / 2 - clip.y0))))


# --- render_question_images end to end on rotated pages ----------------------

def test_a_figure_box_on_a_rotated_scan_is_cropped_not_dropped():
    doc = _rotated_scan_page()
    try:
        pages = services.extract_worksheet_pages(doc)
        p = pages['pages'][0]
        W, H = p['screenshot_w'], p['screenshot_h']
        result = {'questions': [{
            'question_text': 'bottom third', 'has_image': True, 'page_num': 1,
            'image_bbox': [0.1 * W, 0.72 * H, 0.9 * W, 0.95 * H],
        }]}
        result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()
    q = result['questions'][0]
    assert q['image_ref'] == 'worksheet_img_q1_p1.png'
    assert q['has_image'] is True
    assert list(images) == ['worksheet_img_q1_p1.png']


def test_a_vector_figure_on_a_rotated_page_is_cropped_from_where_it_shows():
    doc = _rotated_vector_page()
    try:
        page = doc[0]
        shown = displayed_rect(page, page.get_drawings()[0]['rect'])
        pages = services.extract_worksheet_pages(doc)
        p = pages['pages'][0]
        sx, sy = p['screenshot_w'] / p['pdf_w'], p['screenshot_h'] / p['pdf_h']
        result = {'questions': [{
            'question_text': 'grey box', 'has_image': True, 'page_num': 1,
            'image_bbox': [(shown.x0 - 15) * sx, (shown.y0 - 15) * sy,
                           (shown.x1 + 15) * sx, (shown.y1 + 15) * sy],
        }]}
        result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()
    q = result['questions'][0]
    assert q['image_ref'] in images
    frac = q['image_bbox_frac']
    assert frac[0] < (shown.x0 + shown.x1) / 2 / 500 < frac[2]
    assert frac[1] < (shown.y0 + shown.y1) / 2 / 800 < frac[3]
    im = Image.open(io.BytesIO(__import__('base64').b64decode(images[q['image_ref']])))
    assert _is_grey(im.getpixel((im.width // 2, im.height // 2)))


# --- raster_native_dpi and the render cap ------------------------------------

def test_raster_native_dpi_reads_the_scan_resolution_through_the_rotation():
    doc = _rotated_scan_page()
    page = doc[0]
    dpi = raster_native_dpi(page, page.rect)
    assert dpi is not None and abs(dpi - 144) < 2       # 1600 px over 800 pt


def test_raster_native_dpi_is_none_for_a_vector_region():
    doc = _rotated_vector_page()
    page = doc[0]
    assert raster_native_dpi(page, page.rect) is None


def test_a_scan_only_crop_renders_at_the_scan_resolution_not_print_dpi():
    doc = _rotated_scan_page()
    try:
        pages = services.extract_worksheet_pages(doc)
        p = pages['pages'][0]
        W, H = p['screenshot_w'], p['screenshot_h']
        result = {'questions': [{
            'question_text': 'scan region', 'has_image': True, 'page_num': 1,
            'image_bbox': [0.1 * W, 0.1 * H, 0.6 * W, 0.4 * H],
        }]}
        result, images = services.render_question_images(doc, pages, result)
    finally:
        doc.close()
    q = result['questions'][0]
    frac = q['image_bbox_frac']
    width_pt = (frac[2] - frac[0]) * 500
    im = Image.open(io.BytesIO(__import__('base64').b64decode(images[q['image_ref']])))
    # ~144 DPI (the scan's own), not the 300 DPI print default. A uniform grey
    # region is not trimmed, so the pixel width reflects the DPI directly.
    assert abs(im.width / (width_pt / 72) - 144) < 6
