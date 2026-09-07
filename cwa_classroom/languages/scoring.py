"""Handwriting scoring for the letter-writing exercise (CPP-392).

Replaces the raw pixel-IoU metric (CPP-311), which compared a thin pen
stroke against a solid-filled font glyph — the fill area vastly outweighs
the stroke area, so even a perfectly traced letter topped out around
50-60% IoU regardless of which character was drawn. This module instead:

1. Crops both bitmaps to their ink bounding box and rescales to a common
   box *preserving aspect ratio* (the old client-side normaliser stretched
   width/height independently, which also warped narrow glyphs like "l"
   or "I").
2. Skeletonises the target glyph down to a 1px centreline (Zhang-Suen
   thinning) and builds a fixed-radius tolerance corridor around it, so
   the comparison no longer cares whether the pen stroke is thinner than
   the font's stem width.
3. Scores precision (did the student stay inside the corridor) and recall
   (did the student cover the full skeleton) as an F1/Dice score, which
   penalises both "drew outside the shape" and "missed part of the
   shape" — and stays low for a wrong letter or a scribble, since neither
   lines up with the target skeleton.

This is the authoritative score: the server recomputes it from the ink
snapshot the client posts, rather than trusting a client-submitted number.
"""
import base64
import io
import logging
import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

FONT_DIR = os.path.join(
    os.path.dirname(__file__), 'static', 'languages', 'fonts',
)

FONT_FILES = {
    'latin':   'NotoSans.ttf',
    'sinhala': 'NotoSansSinhala.ttf',
    'tamil':   'NotoSansTamil.ttf',
    # Subsetted (fontTools --text-file) from Noto Sans SC's *variable*
    # release down to exactly the 231 characters seed_language_exercises.py's
    # Mandarin SEED uses (numbers, all 214 Kangxi radicals, common words) —
    # variable, not the static per-weight build, so _load_font's
    # set_variation_by_axes(_BOLD_AXES) call below actually selects bold
    # instead of silently falling back with a warning (as it would on a
    # static source). A full CJK font is 10-20MB+ vs. this subset's ~55KB,
    # in line with the other vendored fonts here (tens-to-hundreds of KB).
    # If the Mandarin character set grows again, re-subset from a fresh
    # Noto Sans SC *Variable* download (Sans/Variable/OTF in
    # googlefonts/noto-cjk) with the new full character list, or
    # MIN_TEMPLATE_INK_PX below will silently treat any newly-added,
    # uncovered character as a missing/tofu glyph.
    'cjk':     'NotoSansSC.otf',
    # Subsetted (fontTools --text-file) from Noto Sans JP's *variable*
    # release down to exactly the 142 kana characters
    # seed_language_exercises.py's Japanese SEED uses (46 hiragana + 20
    # dakuten + 5 handakuten, x2 for katakana) — same rationale as 'cjk'
    # above (variable so set_variation_by_axes(_BOLD_AXES) works cleanly;
    # a full CJK-range font is 10-20MB+ vs. this subset's tens of KB).
    'kana':    'NotoSansJP.otf',
    # Subsetted (fontTools --text-file) from Noto Sans KR's *variable*
    # release down to exactly the 51 characters seed_language_exercises.py's
    # Korean SEED uses (14 basic + 5 doubled consonants, 10 basic + 11
    # compound vowels, 11 syllable-final consonant clusters) — Hangul
    # Compatibility Jamo codepoints (U+3131-U+318E), which render as
    # standalone letterforms outside a syllable block, unlike the
    # positional Hangul Jamo block (U+1100-U+11FF) meant for composing
    # precomposed syllables. Same variable-font rationale as cjk/kana above.
    'hangul':  'NotoSansKR.otf',
}
DEFAULT_FONT_FILE = 'NotoSans.ttf'

# Vendored Noto fonts expose variable axes in order [Weight, Width].
# 700/100 = bold, normal width — matches the client's `font: bold ...`.
# Must be a list, not a tuple — Pillow's set_variation_by_axes rejects
# tuples with a TypeError (easy to lose under a broad except/pass).
_BOLD_AXES = [700, 100]

TOP_PAD = 24  # mirrors whiteboard.js's TOP_PAD

# Comparison box the normaliser rescales both bitmaps into.
_BOX = 320
_BOX_PAD = 16

# Tolerance radius (px, in the normalized box) for the skeleton corridor.
# ~3.4% of the box — generous enough for natural handwriting jitter,
# tight enough that a wrong letter or scribble doesn't accidentally
# line up with the target skeleton. Calibrated against the fixture set
# in languages/tests/test_cpp392_scoring_metric.py.
TOLERANCE_RADIUS = 11

MAX_INK_IMAGE_B64_CHARS = 400_000  # ~300KB decoded; small near-binary PNG

# Below this many dark pixels, the rendered "glyph" is really a tofu box,
# missing glyph, or blank — the vendored font doesn't cover this character.
# Only latin/sinhala/tamil/cjk/kana/hangul are vendored (FONT_FILES, and
# cjk/kana/hangul are curated character subsets — see their comments
# there); anything else falls back to NotoSans.ttf, which is latin-only,
# so this guard is what stops an out-of-coverage script from silently
# being scored against an empty template.
MIN_TEMPLATE_INK_PX = 80


class ScoringError(Exception):
    """Raised when the posted ink image can't be decoded or scored."""


def _font_path(script_type):
    filename = FONT_FILES.get(script_type, DEFAULT_FONT_FILE)
    return os.path.join(FONT_DIR, filename)


def _load_font(script_type, size):
    font = ImageFont.truetype(_font_path(script_type), size)
    try:
        font.set_variation_by_axes(_BOLD_AXES)
    except AttributeError:
        pass  # static (non-variable) font — already at its one weight
    except Exception:
        logger.warning(
            'Failed to select bold weight for %s (variation axes %s) — '
            'template will render at the font default weight',
            _font_path(script_type), _BOLD_AXES, exc_info=True,
        )
    return font


def render_glyph_mask(char, script_type, canvas_config):
    """Rasterise the target character the same way whiteboard.js does."""
    w = 400
    line_height = canvas_config['line_height']
    descender = canvas_config['descender']
    h = TOP_PAD + line_height + descender + TOP_PAD
    font_size = int(line_height * 0.9)
    base_y = TOP_PAD + line_height

    img = Image.new('L', (w, h), color=255)
    draw = ImageDraw.Draw(img)
    font = _load_font(script_type, font_size)
    draw.text((w / 2, base_y), char, font=font, fill=0, anchor='ms')

    return np.asarray(img, dtype=np.uint8) < 128


def decode_ink_mask(png_b64):
    """Decode the client-posted canvas snapshot into a boolean ink mask.

    Uses the same luminance<128 threshold as whiteboard.js, so the pale
    ruled lines / watermark / trace-over guide baked into the snapshot
    (all light-coloured) are excluded automatically, same as before.
    """
    if not png_b64 or len(png_b64) > MAX_INK_IMAGE_B64_CHARS:
        raise ScoringError('missing or oversized ink image')
    try:
        raw = base64.b64decode(png_b64, validate=True)
        img = Image.open(io.BytesIO(raw)).convert('RGB')
    except Exception as exc:
        raise ScoringError(f'could not decode ink image: {exc}') from exc

    arr = np.asarray(img, dtype=np.float64)
    lum = 0.299 * arr[..., 0] + 0.587 * arr[..., 1] + 0.114 * arr[..., 2]
    return lum < 128


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return xs.min(), xs.max(), ys.min(), ys.max()


def _normalize(mask, box=_BOX, pad=_BOX_PAD):
    """Crop to ink bbox, scale to a common box preserving aspect ratio, centre."""
    bbox = _bbox(mask)
    if bbox is None:
        return np.zeros((box, box), dtype=bool)
    x0, x1, y0, y1 = bbox
    bw, bh = x1 - x0 + 1, y1 - y0 + 1

    target = box - 2 * pad
    scale = min(target / bw, target / bh)
    new_w = max(1, round(bw * scale))
    new_h = max(1, round(bh * scale))

    crop = Image.fromarray(mask[y0:y1 + 1, x0:x1 + 1].astype(np.uint8) * 255)
    resized = crop.resize((new_w, new_h), Image.NEAREST)

    out = Image.new('L', (box, box), color=0)
    out.paste(resized, ((box - new_w) // 2, (box - new_h) // 2))
    return np.asarray(out, dtype=np.uint8) > 127


def _dilate(mask, r):
    """Square (2r+1)-side box dilation, vectorised."""
    if r <= 0:
        return mask.copy()
    h, w = mask.shape
    padded = np.zeros((h + 2 * r, w + 2 * r), dtype=bool)
    padded[r:r + h, r:r + w] = mask

    acc = padded.copy()
    for shift in range(1, r + 1):
        acc[:, shift:] |= padded[:, :-shift]
        acc[:, :-shift] |= padded[:, shift:]

    acc2 = acc.copy()
    for shift in range(1, r + 1):
        acc2[shift:, :] |= acc[:-shift, :]
        acc2[:-shift, :] |= acc[shift:, :]

    return acc2[r:r + h, r:r + w]


def _skeletonize(mask):
    """Zhang-Suen thinning, vectorised with numpy neighbour shifts."""
    img = mask.astype(np.uint8)
    changed = True
    while changed:
        changed = False
        for sub_iter in (0, 1):
            padded = np.pad(img, 1, mode='constant')
            p2 = padded[0:-2, 1:-1]
            p3 = padded[0:-2, 2:]
            p4 = padded[1:-1, 2:]
            p5 = padded[2:, 2:]
            p6 = padded[2:, 1:-1]
            p7 = padded[2:, 0:-2]
            p8 = padded[1:-1, 0:-2]
            p9 = padded[0:-2, 0:-2]

            b = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            seq = (p2, p3, p4, p5, p6, p7, p8, p9, p2)
            a = np.zeros_like(img)
            for i in range(8):
                a += ((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8)

            cond = (img == 1) & (b >= 2) & (b <= 6) & (a == 1)
            if sub_iter == 0:
                cond &= (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                cond &= (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)

            if cond.any():
                img[cond] = 0
                changed = True
    return img.astype(bool)


def _reason(score, precision, recall):
    if score >= 85:
        return 'excellent_match'
    if score >= 70:
        return 'close_match'
    if precision < 0.5 and recall < 0.5:
        return 'shape_mismatch'
    if precision < recall:
        return 'strokes_outside_shape'
    if recall < precision:
        return 'shape_incomplete'
    return 'needs_practice'


def score_masks(student_mask, template_mask):
    """Core metric, operating on two raw (un-normalised) boolean masks.

    Returns (score: float 0-100, reason: str). Split out from
    compute_score() so tests can feed synthetic masks directly without
    going through PNG encoding / font rendering.
    """
    if not student_mask.any():
        return 0.0, 'no_ink'

    student_n = _normalize(student_mask)
    template_n = _normalize(template_mask)
    return _score_normalized(student_n, template_n)


def _score_normalized(student_n, template_n):
    """score_masks()'s comparison, given masks already run through
    _normalize() exactly once each. Split out so tests can build a
    synthetic "correct trace" directly from the template's own normalized
    skeleton without re-normalizing it a second time — cropping to bbox
    and independently rescaling twice compounds rounding error (each
    _normalize() picks its own best-fit scale from a bbox that shifts
    slightly once ink is skeletonised+dilated), which for narrow-bbox
    glyphs can drift enough to misalign the two masks entirely. Production
    code (score_masks/compute_score) always normalizes exactly once per
    side, same as this function assumes.
    """
    skeleton = _skeletonize(template_n)
    if not skeleton.any():
        skeleton = template_n  # degenerate glyph (shouldn't happen for letters)

    # _normalize()'s aspect-preserving upscale can turn a couple of sparse,
    # far-apart ink pixels into an empty NEAREST-resampled crop (student_n
    # all False, dividing by zero below), or turn a single accidental dot
    # into a filled blob big enough to coincidentally overlap a rounded
    # letter's corridor by sheer area, even though it's not stroke-shaped
    # at all. Both slip past the shape comparison itself (a big enough blob
    # legitimately covers plenty of the corridor), so check structure
    # first: a real letter, traced with a pen, only ever fills a modest
    # fraction of its own bounding box (~8-16% for the fixtures in
    # test_cpp392_scoring_metric.py) because it's a thin line, not a
    # filled area — a dot/blob's fill ratio is ~0.7+ regardless of scale
    # (fill ratio is scale-invariant, so this holds before or after
    # normalizing).
    if not student_n.any():
        return 0.0, 'no_ink'
    student_bbox = _bbox(student_n)
    x0, x1, y0, y1 = student_bbox
    fill_ratio = float(student_n.sum()) / float((x1 - x0 + 1) * (y1 - y0 + 1))
    if fill_ratio > 0.4:
        return 0.0, 'too_little_ink'

    corridor = _dilate(skeleton, TOLERANCE_RADIUS)
    student_dilated = _dilate(student_n, TOLERANCE_RADIUS)

    precision = float((student_n & corridor).sum()) / float(student_n.sum())
    recall = float((skeleton & student_dilated).sum()) / float(skeleton.sum())

    if precision + recall == 0:
        score = 0.0
    else:
        score = 100.0 * 2 * precision * recall / (precision + recall)

    score = round(score, 1)
    return score, _reason(score, precision, recall)


def compute_score(ink_png_b64, char, script_type, canvas_config):
    """Decode the posted ink snapshot and score it against `char`.

    Raises ScoringError if the ink image can't be decoded. If `script_type`
    isn't one of the vendored fonts (Language.SCRIPT_CHOICES also allows
    devanagari/arabic/cjk, none of which are vendored here, matching this
    ticket's scope of latin/sinhala/tamil), falls back to the same generous
    ink-presence heuristic CPP-311 used for this case ("template failed to
    render — give credit for drawing anything meaningful") rather than
    blocking every submission for that language outright. This is checked
    by script coverage, not by how much ink the fallback font happens to
    render for the character — FreeType draws a visible ".notdef" tofu box
    placeholder for an unmapped codepoint rather than nothing, so an ink-
    count check alone would score real submissions against a meaningless
    box shape instead of falling back.
    """
    student_mask = decode_ink_mask(ink_png_b64)

    if script_type not in FONT_FILES:
        logger.warning(
            "No vendored font for script_type=%r (char %r) — falling back "
            "to the ink-presence heuristic instead of scoring shape.",
            script_type, char,
        )
        return (72.0, 'unscored_fallback') if student_mask.sum() > MIN_TEMPLATE_INK_PX else (0.0, 'no_ink')

    template_mask = render_glyph_mask(char, script_type, canvas_config)
    if template_mask.sum() < MIN_TEMPLATE_INK_PX:
        # Defensive: a supported script whose font still failed to render
        # this specific character (e.g. an unmapped codepoint within an
        # otherwise-covered script) — surface it rather than scoring
        # against a near-blank template.
        raise ScoringError(
            f'target glyph {char!r} ({script_type}) rendered with too little '
            f'ink ({int(template_mask.sum())}px) despite a vendored font for this script'
        )
    return score_masks(student_mask, template_mask)
