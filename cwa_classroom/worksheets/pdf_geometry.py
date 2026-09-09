"""PDF page geometry the two importers share: rotated pages and raster resolution.

**Rotated pages.** A scanned or photographed page often carries a ``/Rotate``
entry (a landscape scan stored sideways and rotated 270° for display, say). In
PyMuPDF the rendered page — ``page.rect``, ``get_pixmap()`` and its ``clip`` —
is in the page's DISPLAYED coordinates, but everything the page *reports*
about its content — ``get_drawings()``, ``cluster_drawings()``,
``get_text('words' / 'blocks')``, ``get_image_rects()`` — is in the UNROTATED
coordinates of the underlying content stream. On an unrotated page the two
coincide and nothing here matters. On a rotated page they do not: a crop box
drawn on the screenshot (displayed) was being compared against image and
drawing rectangles that had never been rotated, so a figure box in the bottom
third of a rotated scan found "no raster image" under it and was dropped as
spurious, and the AI import labelled a full-page scan as sitting at
"x 0–141%" of its page. Run every reported rectangle through
:func:`displayed_rect` before comparing it with anything drawn on the
screenshot. The one thing that wants the raw rectangle back is a redaction
annotation (``add_redact_annot``), which is placed in unrotated coordinates.

**Raster resolution.** A figure box on a scanned page is re-rendered from the
PDF at print DPI. For a vector drawing that buys sharpness; for a region that
is nothing but an embedded scan it only upsamples the scan's own pixels — a
1.7 MB PNG of a 180-DPI photocopy. :func:`raster_native_dpi` reports the
resolution the scan actually has so the renderer can stop there.
"""


def displayed_rect(page, rect):
    """``rect`` (as reported by the page's text/drawing/image extraction) in the
    page's displayed coordinates — the space of ``page.rect``, the screenshot
    and ``get_pixmap(clip=...)``. Identity on an unrotated page."""
    import fitz

    return fitz.Rect(rect) * page.rotation_matrix


def raster_native_dpi(page, clip_rect, min_overlap_frac=0.12):
    """The highest native resolution (DPI) of the embedded raster images that
    materially overlap ``clip_rect`` (displayed coordinates), or ``None`` when
    none does — i.e. the region is vector art, text, or empty.

    Resolution is the image's pixel size over the size it is placed at on the
    page. The longer sides are compared so a scan placed sideways on a rotated
    page still reads correctly. Best-effort: any PyMuPDF hiccup yields ``None``
    and the caller renders at its default.
    """
    import fitz

    try:
        clip = fitz.Rect(clip_rect)
        clip_area = abs(clip.get_area())
        if clip_area <= 0:
            return None
        doc = page.parent
        best = None
        for img in page.get_images(full=True):
            xref = img[0]
            try:
                px_w = int(doc.xref_get_key(xref, 'Width')[1])
                px_h = int(doc.xref_get_key(xref, 'Height')[1])
            except (ValueError, TypeError, IndexError):
                continue
            for raw in page.get_image_rects(xref):
                shown = displayed_rect(page, raw)
                inter = fitz.Rect(shown)
                inter.intersect(clip)
                if not inter.is_valid or abs(inter.get_area()) < min_overlap_frac * clip_area:
                    continue
                long_pt = max(shown.width, shown.height)
                if long_pt <= 0:
                    continue
                dpi = max(px_w, px_h) / (long_pt / 72.0)
                if best is None or dpi > best:
                    best = dpi
        return best
    except Exception:
        return None
