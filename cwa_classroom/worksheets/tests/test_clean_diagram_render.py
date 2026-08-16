"""Header redaction in the question-image crop (_render_clean_diagram).

Copying the page and rewriting its content stream to white out headers costs
around a second per question — minutes across a big worksheet — so it must only
happen when a text block actually bleeds into the crop. Text that sits wholly
above the crop is outside the rendered region and cannot dirty it.
"""
import fitz

from worksheets.services import _bleeding_text_blocks, _render_clean_diagram


def _page_with(header_rect_y, figure_rect):
    """One-page doc with a text header at *header_rect_y* and a drawn figure."""
    doc = fitz.open()
    page = doc.new_page(width=400, height=500)
    page.insert_text((60, header_rect_y), 'Questions', fontsize=24)
    page.draw_rect(fitz.Rect(*figure_rect), color=(0, 0, 0), fill=(0.6, 0.6, 0.6))
    return doc, page


def test_header_well_above_the_crop_is_not_treated_as_bleeding():
    doc, page = _page_with(80, (120, 200, 280, 300))
    try:
        clip = fitz.Rect(100, 190, 300, 320)
        assert _bleeding_text_blocks(page, clip) == []
    finally:
        doc.close()


def test_header_straddling_the_top_edge_is_flagged():
    doc, page = _page_with(200, (120, 210, 280, 320))
    try:
        # Clip starts mid-header: its descenders hang into the crop.
        clip = fitz.Rect(100, 190, 300, 340)
        assert _bleeding_text_blocks(page, clip)
    finally:
        doc.close()


def test_bleeding_header_is_whited_out_of_the_render():
    doc, page = _page_with(200, (120, 240, 280, 320))
    try:
        clip = fitz.Rect(100, 190, 300, 340)
        dirty = page.get_pixmap(clip=clip, dpi=72)
        clean = _render_clean_diagram(page, clip, dpi=72)
        # The redacted render must differ from the raw crop — the header is gone.
        assert clean.samples != dirty.samples
    finally:
        doc.close()


def test_render_without_a_bleeding_header_matches_the_plain_crop():
    """The fast path must be pixel-identical to what redaction produced."""
    doc, page = _page_with(80, (120, 200, 280, 300))
    try:
        clip = fitz.Rect(100, 190, 300, 320)
        plain = page.get_pixmap(clip=clip, dpi=72)
        rendered = _render_clean_diagram(page, clip, dpi=72)
        assert rendered.samples == plain.samples
    finally:
        doc.close()


def test_fast_path_does_not_copy_the_page(monkeypatch):
    doc, page = _page_with(80, (120, 200, 280, 300))
    try:
        calls = []
        real_open = fitz.open

        def spy_open(*args, **kwargs):
            calls.append(args)
            return real_open(*args, **kwargs)

        monkeypatch.setattr(fitz, 'open', spy_open)
        _render_clean_diagram(page, fitz.Rect(100, 190, 300, 320), dpi=72)
        assert calls == []
    finally:
        doc.close()


# --- _capped_render_dpi ------------------------------------------------------

def test_small_figure_keeps_the_full_render_dpi():
    from worksheets.services import IMAGE_RENDER_DPI, _capped_render_dpi
    small = fitz.Rect(0, 0, 120, 90)          # ~1.7in across
    assert _capped_render_dpi(small) == IMAGE_RENDER_DPI


def test_large_figure_is_capped_to_the_pixel_ceiling():
    from worksheets.services import IMAGE_MAX_PX, IMAGE_RENDER_DPI, _capped_render_dpi
    wide = fitz.Rect(0, 0, 520, 300)          # full page width
    dpi = _capped_render_dpi(wide)
    assert dpi < IMAGE_RENDER_DPI
    assert round(520 / 72 * dpi) <= IMAGE_MAX_PX


def test_degenerate_rect_falls_back_to_the_target_dpi():
    from worksheets.services import IMAGE_RENDER_DPI, _capped_render_dpi
    assert _capped_render_dpi(fitz.Rect(10, 10, 10, 10)) == IMAGE_RENDER_DPI


# --- redaction flags ---------------------------------------------------------
#
# apply_redactions() defaults to rewriting the pixels of every image the
# redaction rect touches. On real worksheets that path corrupts the heap in
# PyMuPDF 1.24.3 and aborts the process (SIGABRT), which in the RQ worker kills
# the work-horse before it can mark the upload failed — the teacher's page then
# polls a dead job forever. We only ever want the header TEXT gone, so both the
# image and line-art passes must stay off.

def test_redaction_touches_text_only(monkeypatch):
    doc, page = _page_with(200, (120, 240, 280, 320))
    try:
        seen = {}
        real_open = fitz.open

        def spy_open(*args, **kwargs):
            scratch = real_open(*args, **kwargs)

            class _Wrapper:
                def __init__(self, inner):
                    self._inner = inner

                def __getitem__(self, idx):
                    pg = self._inner[idx]
                    orig = pg.apply_redactions

                    def apply(*a, **kw):
                        seen.update(kw)
                        return orig(*a, **kw)

                    pg.apply_redactions = apply
                    return pg

                def __getattr__(self, name):
                    return getattr(self._inner, name)

            return _Wrapper(scratch)

        monkeypatch.setattr(fitz, 'open', spy_open)
        _render_clean_diagram(page, fitz.Rect(100, 190, 300, 340), dpi=72)

        assert seen.get('images') == fitz.PDF_REDACT_IMAGE_NONE
        assert seen.get('graphics') == fitz.PDF_REDACT_LINE_ART_NONE
    finally:
        doc.close()
