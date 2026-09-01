# CPP-392: Letter-Writing Handwriting Scoring Fix

## Problem

The letter-writing exercise (CPP-310 canvas, CPP-311 scoring) under-scores
correctly-formed characters across every letter and script. A well-formed
capital "A" scored 56%; correct attempts consistently landed in the 1-star
band (50-60%) with a canned "try to fill the canvas height" tip, even though
the instructions on the same screen promise automatic size adjustment. The
2-star (≥70%) and 3-star (≥85%) bands were effectively unreachable.

## Root Cause

CPP-311's `computeScore()` (client-side, `whiteboard.js`) compared the
student's pen strokes against the target glyph with raw pixel IoU:

1. **Fill vs. stroke-width mismatch.** The target is a *solid-filled* font
   glyph; the student's ink is a ~3px pen line. Even a perfectly-traced
   letter has far less ink area than the glyph fill, so intersection/union
   is capped well below 100% regardless of shape accuracy. A fixed-radius
   dilation was applied to both bitmaps to compensate, but dilating an
   already-thick glyph fill doesn't fix the underlying area mismatch.
2. **Non-aspect-preserving normalisation.** `_normalizeScale` stretched the
   ink's bounding box to fill the canvas independently on each axis. For
   narrow glyphs (e.g. "l", "I") this could stretch a bounding box only a
   few pixels wide across the full canvas width, warping the shape.
3. Both bugs are character- and script-agnostic, matching the report that
   *every* character was affected.

## Solution

Replace the metric and move scoring authority to the server:

1. **Skeleton-corridor metric** (`languages/scoring.py`, new module):
   - Crop both bitmaps to their ink bounding box, rescale to a common box
     **preserving aspect ratio**, and centre (fixes bug 2).
   - Skeletonise the *target glyph* to a 1px centreline (Zhang-Suen
     thinning, vectorised with numpy) and build a fixed-radius tolerance
     corridor around it. Score precision (student ink inside the corridor)
     and recall (target skeleton covered by dilated student ink) as an F1
     score. This removes the fill-vs-stroke-width penalty entirely (fixes
     bug 1) while still penalising a wrong letter or a scribble, since
     neither lines up with the target skeleton.
   - Star thresholds (≥50/≥70/≥85) are unchanged — only the metric that
     feeds them was broken.
2. **Server-authoritative scoring.** The client previously computed the
   score and the server only clamped whatever number it was sent — a
   score-spoofing gap. The client now posts a PNG snapshot of the ink
   layer (`ink_image`); the server decodes it and calls
   `scoring.compute_score()` to produce the real score. A client-submitted
   `score` field, if sent at all, is no longer read.
3. **Client/server font parity.** The on-screen guide glyph for Latin
   exercises was rendered in the browser's generic `sans-serif`, while the
   server needs a concrete font file to rasterise its template from. Added
   `get_letter_writing_font_info()` (`languages/utils.py`) so the
   letter-writing guide renders in the same vendored Noto Sans family the
   server scores against — scoped to this exercise type only, since the
   shared `FONT_MAP`/`get_font_info()` is read by every other exercise
   type (crossword, MCQ, etc.) and changing it globally was out of scope.
   Sinhala/Tamil already used Noto Sans Sinhala/Tamil client-side, matching
   the vendored fonts, so no change was needed there.
4. **Reason-based feedback.** The canned "fill the canvas height" tip is
   gone. `compute_score()` returns a reason code (`excellent_match`,
   `close_match`, `shape_incomplete`, `strokes_outside_shape`,
   `shape_mismatch`, `needs_practice`, `no_ink`) reflecting which of
   precision/recall was low; `whiteboard.js` maps the code to copy.

## Components

**`languages/scoring.py`** (new) — `render_glyph_mask`, `decode_ink_mask`,
`_normalize`, `_dilate`, `_skeletonize`, `score_masks`, `compute_score`.
Fonts vendored at `languages/static/languages/fonts/` (Noto Sans, Noto Sans
Sinhala, Noto Sans Tamil — variable fonts, bold weight selected via
`set_variation_by_axes`). Guards: oversized/malformed ink image and
under-covered target glyph (font lacks the character) both raise
`ScoringError` rather than silently fabricating a score.

**`languages/views.py`** (`_letter_writing`) — POST handler now calls
`scoring.compute_score()` when strokes are present; returns HTTP 422 with
an explicit error on `ScoringError` instead of falling back to a
fabricated score (no-silent-failure). No strokes → score 0 / `no_ink`,
unchanged.

**`languages/static/languages/js/whiteboard.js`** — removed the entire
client-side IoU pipeline (`_threshold`, `_dilate`, `_autoCenter`,
`_normalizeScale`, `_iou`, `computeScore`, `starsFromScore`). Submit now
captures an ink PNG (`captureInkPng`), POSTs it, shows a brief "Scoring…"
state, and renders whatever the server returns. `REASON_TIPS` replaces the
static `STAR_TIPS` array.

## Testing

- `languages/tests/test_cpp392_scoring_metric.py` — pytest-django, no
  browser required. Exercises `scoring.score_masks()` directly against
  synthetic ink (a "correct" trace = the target glyph's own skeleton
  dilated back to pen width): straight/curved/complex Latin characters,
  Sinhala and Tamil samples, size/position invariance, wrong-letter and
  scribble rejection, reason codes, and full view-integration (real PNG
  POST through the Django test client).
- `ui_tests/test_cpp392_scoring_metric.py` — Playwright, real browser +
  real server. Traces the actual on-screen guide glyph's skeleton in the
  browser (self-contained JS, not a reuse of app internals) and injects it
  as a fabric.Path, so the "3-star result" assertion depends on the real
  scorer recognising a well-formed shape rather than on being able to
  drive a mouse pixel-perfectly.
- Existing CPP-308/310/311/312/348 tests that posted a trusted client
  `score` field were updated to mock `languages.views.scoring.compute_score`
  — they test view-level persistence/clamping/threshold logic, which is now
  decoupled from the scoring algorithm itself.

## Bugs found during implementation (not in the original ticket)

Both surfaced only once the metric was validated against a *real Chromium
trace* through the full server pipeline, not just PIL-vs-PIL synthetic
fixtures — worth recording since they'd otherwise silently recur:

1. **Bold weight was never applied.** `_load_font()` called
   `font.set_variation_by_axes(_BOLD_AXES)` with `_BOLD_AXES` as a tuple;
   Pillow's variable-font API requires a `list` and raises `TypeError` on a
   tuple, which a blanket `except Exception: pass` silently swallowed —
   every template glyph rendered at the font's default (regular) weight
   instead of bold, for every character, every script, from the first
   version of this fix. Fixed by using a list and narrowing the `except`
   to only swallow `AttributeError` (static, non-variable fonts have no
   `set_variation_by_axes` method at all); any other failure now logs a
   warning instead of failing silently, per this repo's no-silent-failure
   convention.
2. **Double-normalization compounds rounding error.** `score_masks()`
   normalizes both masks exactly once — but an early version of the test
   suite built its "correct trace" fixture by normalizing the template
   into a *separate* box, skeletonising and dilating that, then handing
   the result to `score_masks()`, which normalizes it a *second* time.
   Two independent crop-to-bbox+rescale passes don't compose cleanly:
   dilation shifts a shape's effective bounding box slightly, so the
   second pass can pick a measurably different scale/position than the
   first, especially for narrow-bbox glyphs (e.g. "L") — in the worst
   observed case this produced *zero* overlap between an otherwise-correct
   trace and its own template. Fixed by splitting `score_masks()` into a
   normalize-once entry point plus `_score_normalized()`, which operates
   on already-normalized masks; tests now build fixtures the same way
   `score_masks()` itself does internally (normalize once, then
   skeletonise), rather than normalizing twice.

## Out of scope

- Devanagari/Arabic/CJK letter-writing: no exercises use these
  `script_type`s currently; `MIN_TEMPLATE_INK_PX` guard fails loudly
  (`ScoringError` → HTTP 422) rather than silently scoring against a blank
  template if one is ever added before those fonts are vendored.
- Re-architecting the client into an async "optimistic then corrected"
  score display — the server round-trip is a single same-origin POST, so
  a brief "Scoring…" state was preferred over maintaining two parallel
  implementations of the metric that could drift out of sync.
