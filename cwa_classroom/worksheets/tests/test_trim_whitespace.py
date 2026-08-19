"""Regression test for the Pillow whitespace-trim fix.

A diagram pixmap can carry an alpha channel (``pix.n == 4``). The old code
hardcoded ``Image.frombytes('RGB', ...)``, which mis-aligned the RGBA buffer and
made ``img.save()`` raise ``SystemError: tile cannot extend outside image`` —
silently dropping the shape image. The fix builds the image with the real
channel count and normalises to RGB.
"""
import random

from worksheets.services import _content_bounds, _trim_whitespace


class _FakePix:
    """Minimal stand-in for a fitz Pixmap — only what _trim_whitespace reads."""

    def __init__(self, width, height, n, samples):
        self.width = width
        self.height = height
        self.n = n
        self.samples = samples


def _rgba_with_border():
    """4×4 RGBA: white border, black 2×2 centre — so trimming actually runs."""
    w = h = 4
    white = bytes((255, 255, 255, 255))
    black = bytes((0, 0, 0, 255))
    buf = bytearray()
    for y in range(h):
        for x in range(w):
            buf += black if (1 <= x <= 2 and 1 <= y <= 2) else white
    return _FakePix(w, h, 4, bytes(buf))


def test_trim_whitespace_rgba_returns_png_bytes():
    """RGBA (n==4) pixmaps trim to PNG bytes instead of crashing on save."""
    out = _trim_whitespace(_rgba_with_border())
    assert isinstance(out, (bytes, bytearray))
    assert bytes(out[:8]) == b'\x89PNG\r\n\x1a\n'   # valid PNG signature


def test_trim_whitespace_skips_unknown_colorspace():
    """CMYK (n==5) etc. is returned untrimmed rather than mis-read into RGB."""
    w = h = 4
    white = bytes((255, 255, 255, 255, 255))
    ink = bytes((0, 0, 0, 0, 0))
    buf = bytearray()
    for y in range(h):
        for x in range(w):
            buf += ink if (1 <= x <= 2 and 1 <= y <= 2) else white
    pix = _FakePix(w, h, 5, bytes(buf))
    # Trimming is attempted (non-blank centre) but the unsupported channel count
    # falls back to the original pixmap, never a corrupted image.
    assert _trim_whitespace(pix) is pix


# --- _content_bounds: vectorised edge detection ------------------------------
#
# The scan used to walk the buffer a pixel at a time in Python — about a second
# on a multi-megapixel crop, once per question image. These pin the vectorised
# replacement to the original semantics: blank means every pixel in the row or
# column averages >= 248 across RGB.

def _content_bounds_scalar(samples, w, h, n):
    """The original per-pixel scan, kept here as the reference implementation."""
    def row_blank(y):
        off = y * w * n
        for x in range(w):
            r, g, b = samples[off + x * n], samples[off + x * n + 1], samples[off + x * n + 2]
            if (r + g + b) // 3 < 248:
                return False
        return True

    def col_blank(x):
        for y in range(h):
            off = y * w * n + x * n
            r, g, b = samples[off], samples[off + 1], samples[off + 2]
            if (r + g + b) // 3 < 248:
                return False
        return True

    top = 0
    while top < h and row_blank(top):
        top += 1
    if top == h:
        return None                      # entirely blank
    bottom = h - 1
    while bottom > top and row_blank(bottom):
        bottom -= 1
    left = 0
    while left < w and col_blank(left):
        left += 1
    right = w - 1
    while right > left and col_blank(right):
        right -= 1
    return (top, bottom, left, right)


def _random_pix_buffer(w, h, n, seed):
    """Mostly-white noise with a few dark pixels — exercises both branches."""
    rng = random.Random(seed)
    buf = bytearray()
    for _ in range(w * h):
        dark = rng.random() < 0.15
        value = rng.randint(0, 200) if dark else rng.randint(246, 255)
        buf += bytes([value] * min(n, 3)) + bytes([255] * max(0, n - 3))
    return bytes(buf)


def test_content_bounds_matches_the_scalar_scan():
    for seed in range(8):
        samples = _random_pix_buffer(9, 7, 3, seed)
        assert _content_bounds(samples, 9, 7, 3) == \
            _content_bounds_scalar(samples, 9, 7, 3), f'seed {seed}'


def test_content_bounds_finds_a_centred_figure():
    pix = _rgba_with_border()
    assert _content_bounds(pix.samples, pix.width, pix.height, pix.n) == (1, 2, 1, 2)


def test_content_bounds_reports_an_all_white_buffer():
    white = bytes((255, 255, 255)) * 16
    assert _content_bounds(white, 4, 4, 3) is None


def test_all_white_pixmap_is_returned_untrimmed():
    pix = _FakePix(4, 4, 3, bytes((255, 255, 255)) * 16)
    assert _trim_whitespace(pix) is pix
