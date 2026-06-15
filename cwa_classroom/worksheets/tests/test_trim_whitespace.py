"""Regression test for the Pillow whitespace-trim fix.

A diagram pixmap can carry an alpha channel (``pix.n == 4``). The old code
hardcoded ``Image.frombytes('RGB', ...)``, which mis-aligned the RGBA buffer and
made ``img.save()`` raise ``SystemError: tile cannot extend outside image`` —
silently dropping the shape image. The fix builds the image with the real
channel count and normalises to RGB.
"""
from worksheets.services import _trim_whitespace


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
