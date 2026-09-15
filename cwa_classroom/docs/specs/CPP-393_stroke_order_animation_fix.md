# CPP-393: Letter-Writing Stroke-Order Animation Fix

## Problem

The Step 1 "Watch how it's written" guide animation drew every character
in an order and direction that has nothing to do with real handwriting, in
every script (English, Sinhala, Tamil) — not a Sinhala-specific bug.

## Root cause

`languages/static/languages/js/whiteboard.js`'s old guide-animation IIFE:
skeletonised the rendered glyph (Zhang-Suen thinning), then `traceSkeleton()`
picked a start pixel by "lowest y, then lowest x" and DFS-walked always
following the first neighbour in raster-scan order. Stroke order and
direction were an artefact of pixel scan order — nothing in that code path
knew what language or script it was drawing, so it happened to look
plausible for a few simple glyphs (like "O") and was wrong for everything
else, including "A" (drawn as one scribble instead of three strokes) and
Sinhala/Tamil (which the raster walk has no concept of loop-based
construction for at all).

## Solution

Stop deriving order from the bitmap; keep the skeleton only for shape.

1. **`languages/static/languages/js/stroke_order_data.js`** (new, data
   only) — for each character, an ordered list of strokes; each stroke is
   a short list of anchor points `[x, y]` normalised 0..1 against the
   glyph's own ink bounding box. Anchors only need to be approximately
   right — a teacher can correct one letter without touching engine code.

2. **`languages/static/languages/js/stroke_order.js`** (new engine) —
   skeletonises the rendered glyph (same Zhang-Suen algorithm as before,
   moved here), snaps each authored anchor to the nearest skeleton pixel,
   and walks the skeleton via BFS shortest-path between consecutive
   anchors — falling back to a straight line only when the skeleton is
   disconnected between them (e.g. the dot of "i", detached letter parts).
   A single-anchor stroke renders as a dot. `resolve()` returns `null` for
   a character with no authored data or a glyph that fails to render —
   callers must show the static glyph with no direction arrow, never a
   guessed path (this is what CPP-393 was filed over, and what keeps an
   unauthored or unreviewed script honest rather than silently wrong).

3. **`languages/static/languages/js/whiteboard.js`** — the guide-animation
   IIFE now: renders the ghost glyph once (`renderGhost()`, with its
   existing SVG-retry fallback for complex scripts intact), hands that
   *same* canvas to `StrokeOrder.resolve()` (via the new `opts.canvas`
   parameter) rather than re-rendering internally, and plays back whatever
   `resolve()` returns one stroke at a time: pen dot + direction arrow
   along the current stroke, a pen-lift pause between strokes, and a
   visible "Stroke n / total" badge. `traceSkeleton()` is gone;
   `thin()` moved into `stroke_order.js`. No data → `animateStaticFallback()`
   (the same fade-ghost-in/out behaviour the old code used when skeleton
   tracing failed), with no pen and no arrow.

4. **Template** (`letter_writing.html`) — loads `stroke_order_data.js` and
   `stroke_order.js` before `whiteboard.js`; `#whiteboard-wrapper` gained
   `data-script-type` (from `language.script_type`) so the animation knows
   which table to look the guide character up in.

## Scope — characters authored

All 119 characters seeded by `seed_language_exercises.py`'s `SEED`
constant (52 Latin, 37 Sinhala, 30 Tamil), enforced by
`test_cpp393_stroke_order_data.py`'s completeness test, which is driven
directly from `SEED` — not a hand-copied list — so a new letter or a whole
new seeded language without stroke data fails the build.

**Confidence differs sharply by script — see `stroke_order_data.js`'s own
header comment, repeated here because it matters for merge:**

- **Latin (52/52): hand-authored**, from conventional English
  manuscript/print handwriting order (the ticket's own reference link).
  Spot-checked against the ticket's explicit known values (A=3, b=2, O=1,
  E=4, i=2) and passes.
- **Sinhala (37/37) and Tamil (30/30): TEMPLATE-GENERATED, not verified
  per letter.** Sinhala gets a generic anticlockwise loop (matching the
  general shape the ticket itself describes Sinhala construction as),
  with a second stroke for the subset of letters guessed — from general
  familiarity with the script, not confirmed per-glyph — to carry a
  second visual component (a tail or an attached loop/hook: ර ල ව ළ ෆ ඟ
  ඤ ඦ ණ ඳ ඬ). Tamil gets one uniform generic sweeping-curve stroke per
  character. **These entries exist so the data-completeness test and the
  engine both have something to resolve — they are placeholders, not
  authored stroke order, and per the ticket's own explicit acceptance
  criteria MUST be reviewed and corrected letter-by-letter by a native
  writer of each script before this ships.** Shipping a plausible-but-wrong
  order is worse than the previous state, because students will copy it.

## Testing

- `languages/tests/test_cpp393_stroke_order_data.py` — pure Python, no
  browser. Parses `stroke_order_data.js` directly (regex + `json.loads`
  on the object literal the generator emits — no Node dependency, so it
  works in CI, and zero drift risk since it's the literal shipped file).
  Completeness (driven from `SEED`), structural validity (every stroke
  non-empty, every anchor a 2-element pair in 0..1), and stroke-count
  spot-checks (the ticket's Latin values, plus a labelled-as-unverified
  Sinhala/Tamil sample).
- `ui_tests/test_cpp393_stroke_order.py` — Playwright, real browser +
  real `stroke_order.js`/`stroke_order_data.js`. Engine resolves a path
  (not the fallback) for a guide character in each of the three
  languages; "A"'s first stroke starts in the lower-left quadrant of the
  glyph's own ink bbox and ends near the apex (catches a reversed/
  reordered first stroke); coverage (every skeleton pixel within
  tolerance of some authored stroke) — 0.9 for the hand-authored Latin
  sample, 0.4 for Sinhala/Tamil reflecting the untuned placeholder data
  (raise to 0.9 once native-reviewed, per the test's own docstring).

## Out of scope / follow-up required before this can ship

- **Native-speaker review and correction of the Sinhala and Tamil stroke
  data is a hard blocker per the ticket's own AC** — not done in this
  session (no native-speaker verification available). The engine, data
  format, English data, and full test suite are complete and should not
  need to change when that review happens — only `stroke_order_data.js`'s
  `sinhala`/`tamil` entries (and the two coverage-threshold comments in
  the UI test) need updating.
- devanagari/arabic/cjk: no letter-writing exercises are seeded for them
  yet (per `languages/utils.py`'s existing font/canvas config). As soon
  as one is, it inherits the "no authored data → static fallback" rule
  automatically — no code change needed, only new data.
