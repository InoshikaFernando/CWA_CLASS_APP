# CPP-330: Interactive Geometry & Measurement Question Types

`draw_on_grid` (lines of symmetry / reflection / plotting / marking) and
`measure` (read an angle or scale with tolerance grading).

## 1. Overview

The maths question bank grades multiple-choice and exact-text answers well, but
real SATs / NCEA-style papers are full of two families it can't represent:

- **Draw-on-a-grid** questions — "draw all lines of symmetry", "reflect the
  shape", "plot these coordinates", "mark the right angles".
- **Measure** questions — "measure angle *a*", "read the value on the scale",
  where the correct answer is a number accepted within a tolerance band.

This spec adds both as first-class auto-graded question types, modelled as the
**third and fourth instances of the existing structured-interactive question
pattern** already used by `long_division` and `prime_factorization`
(`maths/models.py` + the `grade_answer` dispatch in `maths/plugin.py`). The
user-visible outcome: teachers can author and students can self-mark geometry
and measurement questions on screen, and the same questions render correctly on
printed worksheets.

## 2. User stories

- **As a Teacher**, I want to author a "draw the lines of symmetry" question by
  defining a dot grid, a shape, and the correct set of symmetry lines, so that
  students get instant, consistent marking instead of me grading drawings by
  hand.
- **As a Teacher**, I want to author a "measure angle *a*" question by entering
  the true angle and an accepted tolerance, so that a pupil who measures 134°
  for a 135° angle is still marked correct, exactly like the real mark scheme.
- **As a Student**, I want to click grid dots to draw lines / plot points and
  get marked immediately, so that practising geometry feels like the paper test.
- **As a Student**, I want to type a measured value into a degrees box and be
  told if I'm within range, so that I learn to measure accurately.
- **As a HoI / HoD**, I want these question types included in the same bank,
  visibility scoping, and reporting as every other maths question, so that no
  new analytics surface is required.
- **Parents** are not directly involved beyond the existing child-progress views
  (the new types report through the same `is_correct` / `points_earned` path, so
  parent dashboards inherit them automatically — no parent-specific work).

## 3. Data model

Both types follow the established convention: **structured question data lives in
dedicated fields on `maths.Question`; there is no per-option `Answer` row.**
`long_division` uses `dividend`/`divisor`; `prime_factorization` uses
`target_number`. We add a JSON spec field for grid questions and two numeric
fields for measure questions.

### 3.1 New `question_type` choices

```python
# maths/models.py — Question.QUESTION_TYPES
DRAW_ON_GRID = 'draw_on_grid'
MEASURE      = 'measure'

QUESTION_TYPES = [
    ...,                                   # existing entries unchanged
    ('draw_on_grid', 'Draw on Grid (symmetry / reflection / plot)'),
    ('measure',      'Measure (angle / scale, tolerance-graded)'),
]
```

### 3.2 New fields on `maths.Question`

```python
# Draw-on-grid question data --------------------------------------------------
grid_spec = models.JSONField(
    null=True, blank=True,
    help_text=(
        "draw_on_grid only. Defines the dot grid, the rendered shape, the "
        "interaction mode, and the correct target set. See §3.4 for schema."
    ),
)

# Measure question data -------------------------------------------------------
numeric_answer = models.DecimalField(
    max_digits=10, decimal_places=3, null=True, blank=True,
    help_text="measure only. The true value (e.g. 135 for 135°).",
)
answer_tolerance = models.DecimalField(
    max_digits=10, decimal_places=3, null=True, blank=True, default=None,
    help_text=(
        "measure only. Accepted ± band. 135 ± 2 marks 133–137 correct. "
        "NULL or 0 = exact match."
    ),
)
answer_unit = models.CharField(
    max_length=10, blank=True, default='',
    help_text="measure only. Unit shown in the answer box, e.g. '°', 'cm', 'g'.",
)
```

Notes:
- `grid_spec` is `JSONField` (MySQL 8.0 native JSON) — no separate table; this
  matches the "structured data on the Question row" precedent and avoids a child
  model that would need its own tenant scoping.
- `numeric_answer` / `answer_tolerance` are **`DecimalField`, never float**
  (house rule). Tolerance is generic — it works for any "measure / estimate /
  read-off" question, not just angles, so this one field unlocks a whole class
  of paper questions.
- All fields are nullable and only consulted when `question_type` matches, so
  **every existing question is unaffected and no data backfill is needed.**
- Tenant scoping, soft behaviour, and visibility are **inherited unchanged** —
  these are columns on `Question`, which already carries
  `school` / `department` / `classroom` FKs and goes through
  `MathsQuestionsManager`. No new tenant surface is introduced.

### 3.3 `clean()` validation (model-level)

Add to `Question.clean()`:

- `draw_on_grid` ⇒ `grid_spec` must be present and validate against the schema
  (§3.4); raise `ValidationError({'grid_spec': ...})` otherwise.
- `measure` ⇒ `numeric_answer` must be set; `answer_tolerance` defaults to `0`
  if left null at grade time (treated as exact).
- Both new types ⇒ the question must have **no `Answer` rows** (they are not
  MCQ); flag in admin/import if any exist, to catch authoring mistakes early.

### 3.4 `grid_spec` JSON schema

One schema covers all draw-on-grid variants; the `mode` field selects the
interaction and the grader. Coordinates are **integer grid indices** (column
`x`, row `y`), origin top-left, matching the dot lattice — never pixels, so the
same spec renders at any zoom and on print.

```jsonc
{
  "grid":  { "cols": 11, "rows": 9 },          // dot lattice dimensions
  "shape": {                                    // the figure drawn on the grid
    "type": "polygon",
    "points": [[2,3],[5,2],[5,3],[6,3],[5,4],[5,5],[2,5]]   // grid coords
  },
  "mode": "segments",                           // segments | points | shape_complete
  "target": {
    // mode=segments  -> set of correct line segments (lines of symmetry, etc.)
    "segments": [ { "x1": 4, "y1": 0, "x2": 4, "y2": 8 } ],
    // mode=points    -> set of correct dots (coordinate plotting / marking)
    "points":   [ [3,3], [7,5] ],
    // mode=shape_complete -> the segments the student must add to finish a
    //                        reflection/symmetrical figure
    "expected_extra_segments": [ ... ]
  },
  "snap": "dots",                               // input snaps to nearest dot
  "allow_extra": false                          // extra marks => wrong (strict set match)
}
```

**Normalisation rule (critical for grading):** every segment is canonicalised
before comparison by ordering its two endpoints
(`(min_point, max_point)` by `(x, y)`), so a line drawn dot-A→dot-B equals the
same line drawn dot-B→dot-A. Points are compared as an unordered set. This is
what makes grading a deterministic **set equality** check — the same philosophy
as the order-independent `prime_factorization` grader (product of tokens).

For `measure` questions the figure is a **programmatically generated SVG drawn
from `numeric_answer`** (e.g. a 135° angle), so the author never uploads an
image and the rendered geometry is guaranteed true-to-scale on print. A small
`maths/svg_geometry.py` helper renders `{angle}` / `{shape}` to inline SVG.

## 4. Resolution / inheritance rules

These types introduce **no new cascading config.** Visibility resolution
(`school` → `department` → `classroom` → global) is unchanged and handled by the
existing `MathsQuestionsManager`. The only "fallback" is local and trivial:

- `measure` grading: `answer_tolerance` resolves as
  `tolerance = answer_tolerance if answer_tolerance is not None else 0`
  (i.e. NULL inherits "exact match"). This is null-inheritance, not a sentinel.

## 5. Views, URLs, templates

The delivery path is **already centralised** — answers are graded in
`MathsPlugin.grade_answer(content_id, post_data)` (`maths/plugin.py`), which
every surface (homework, worksheets, the maths quiz plugin) funnels through. We
add two branches there, plus authoring/rendering templates. No new URLs for the
student flow.

### 5.1 Grading (server) — extend the existing dispatch

`maths/plugin.py :: grade_answer` currently branches on
`prime_factorization` / `long_division` / else. Add:

```python
elif q.question_type == 'measure' and q.numeric_answer is not None:
    raw = post_data.get(f'answer_{q.id}', '').strip()
    is_correct = grade_measure(q, raw)          # maths/geometry_grading.py

elif q.question_type == 'draw_on_grid' and q.grid_spec:
    payload = post_data.get(f'answer_{q.id}', '')   # JSON string from the canvas
    is_correct = grade_draw_on_grid(q.grid_spec, payload)
```

New module **`maths/geometry_grading.py`**:

- `grade_measure(question, raw) -> bool` — parse `raw` to Decimal (strip the
  unit char), return `abs(value - q.numeric_answer) <= (q.answer_tolerance or 0)`;
  `False` on parse error.
- `grade_draw_on_grid(grid_spec, payload) -> bool` — parse the student JSON,
  normalise segments/points to canonical sets, compare against `target`. With
  `allow_extra=False`, sets must be **exactly equal**; with `allow_extra=True`,
  target must be a subset of the student's marks.

Both are pure functions (no DB, no request) so they are trivially unit-testable
and shared identically across worksheet and homework delivery — same rationale
as `grade_text_answer` living on the model.

### 5.2 Rendering (student) — HTMX question partials

- `templates/maths/partials/question_draw_on_grid.html` — renders the dot grid +
  shape as inline SVG from `grid_spec`, loads a small Alpine/vanilla controller
  (`static/maths/draw_on_grid.js`) that lets the student click dots to lay
  segments / toggle points, and serialises the marks to JSON in a hidden
  `answer_{id}` input on submit. Snap-to-dot; a "clear" button; drawn lines
  shown in colour over the grey shape.
- `templates/maths/partials/question_measure.html` — renders the generated SVG
  figure and a numeric input with the `answer_unit` suffix (the `°` box from the
  paper). No protractor widget in this epic (see §9).

Mirror the existing `prime_factorization` / `long_division` partials — same
include points in the quiz/homework templates, selected by `question.question_type`.

### 5.3 Authoring (teacher) — admin + question form

- Django admin + the teacher question form gain conditional fields:
  - `draw_on_grid` → a `grid_spec` editor. **Sprint 1 ships a raw-JSON textarea
    with server-side schema validation** (fast, unblocks content authoring and
    JSON-fixture import). A visual grid authoring widget is Sprint 3.
  - `measure` → `numeric_answer`, `answer_tolerance`, `answer_unit` inputs, with
    a live SVG preview of the generated figure.
- JSON bank import (`maths` upload path) accepts the new fields so questions can
  be seeded via fixtures / `loaddata`, consistent with how `long_division` and
  `prime_factorization` were seeded (migrations `0021`, `0022`).

### 5.4 Worksheet builder (print)

`measure` and `draw_on_grid` render to the worksheet PDF as **true-scale inline
SVG** (grid dots + shape; generated angle figure). This is the recommended
delivery for `measure` — the pupil uses a real protractor on the printout and
the typed value is graded with tolerance when entered back. The worksheet
builder already iterates `maths.Question`; it needs an SVG render branch for the
two new types. (Note: coding exercises remain excluded from the builder per the
existing Sprint-3 FK blocker — unrelated to this epic.)

## 6. Permissions

No new permissions. The new types are `maths.Question` rows and inherit the
existing matrix exactly. For completeness:

| Role | Author / edit geometry Qs | Take / be graded | See in reports |
|---|---|---|---|
| HoI | ✅ within school | — | ✅ school-wide |
| HoD | ✅ within department scope | — | ✅ department |
| Teacher | ✅ within class scope | — | ✅ class |
| Student | ❌ | ✅ | own results |
| Parent | ❌ | ❌ | ✅ own child |

Default-deny is preserved: authoring is gated by the same checks that already
guard `Question` create/edit views.

## 7. Edge cases

- **Tenant isolation** — `grid_spec` / `numeric_answer` are columns on a
  school-scoped `Question`; no cross-tenant leakage possible. Import must not let
  a school-scoped question reference another school's content (existing
  visibility manager already enforces this).
- **Malformed student payload** — `grade_draw_on_grid` returns `False` (not 500)
  on invalid/empty JSON; `grade_measure` returns `False` on non-numeric input.
- **Author leaves `grid_spec` / `numeric_answer` empty** — blocked by
  `clean()` (§3.3); the grading branch's `and q.grid_spec` / `and
  q.numeric_answer is not None` guard means a misconfigured question can never be
  silently marked correct.
- **`answer_tolerance` null** — treated as exact match (0 band).
- **Unit mismatch in input** — student types "135°" or "135"; grader strips the
  unit char before parsing, so both pass.
- **Extra symmetry lines drawn** — with `allow_extra=False`, any extra segment
  makes the set unequal ⇒ wrong, matching the mark scheme ("draw *all* lines"
  means the exact set).
- **Floating tolerance precision** — Decimal arithmetic only; no float compare.
- **Soft-deleted / role transitions** — inherited from existing `Question`
  behaviour; nothing type-specific.
- **Print vs screen scale** — coordinates are grid indices, not pixels, so the
  figure is correct at any render size; `measure` figures are generated SVG, so
  they are true-scale on paper by construction.

## 8. Migration & rollout

1. **Migration A** (`maths/00XX_add_geometry_question_types.py`) —
   `AlterField` on `question_type` choices + `AddField` for `grid_spec`,
   `numeric_answer`, `answer_tolerance`, `answer_unit`. All nullable / defaulted
   ⇒ **non-destructive, no data migration, instant on MySQL 8** (adds nullable
   columns).
2. **No backfill** — existing rows keep `question_type` and ignore the new
   columns.
3. **Feature flag** — not required; the types are invisible until a teacher
   authors one. Optionally gate the *authoring UI* behind a settings flag
   `ENABLE_GEOMETRY_QUESTIONS` during Sprint 1 so content is staged before
   students see it.
4. **Seed content** — a data migration mirroring `0021`/`0022` loads a starter
   set (the SATs paper questions that prompted this) from a JSON fixture.
5. **Rollback** — reverse migration drops the four columns and the two choices.
   Because nothing else references them and no other type depends on them, this
   is clean. Any authored geometry questions would be lost on rollback (call out
   in the release note).

## 9. Out of scope

- **On-screen draggable/rotatable virtual protractor** for `measure` — Sprint 4
  / separate epic. This epic delivers `measure` as generated-SVG + numeric
  tolerance, best consumed on printed worksheets.
- **Freehand canvas drawing** with computer-vision grading — explicitly
  rejected; we constrain input to grid dots so grading is deterministic set
  comparison.
- **Curved / circular geometry** (arcs, circle theorems) — `grid_spec` covers
  straight segments and points only.
- **Partial credit** for draw_on_grid (e.g. 2 of 3 lines) — Sprint-later; v1 is
  all-or-nothing, matching the 1-mark paper questions.
- **Visual grid authoring widget** beyond the raw-JSON editor — Sprint 3.
- Coding-exercise inclusion in the worksheet builder (unrelated blocker).

## 10. Sprint breakdown

### Sprint 1 — `measure` end-to-end (smallest, highest leverage)
- CPP-XX1: Migration — add `numeric_answer`, `answer_tolerance`, `answer_unit`
  + `measure` choice. *(unit test: migration applies/reverses)*
- CPP-XX2: `grade_measure` in `maths/geometry_grading.py` + branch in
  `plugin.grade_answer`. *(unit: 135±2 boundaries, unit-strip, parse failure)*
- CPP-XX3: SVG angle generator `maths/svg_geometry.py`. *(unit: angle→SVG ray
  geometry)*
- CPP-XX4: `question_measure.html` partial + authoring fields + live preview.
  *(UI test: author 135±2, student enters 134 → correct, 130 → wrong)*
- CPP-XX5: Worksheet-builder SVG render branch for `measure`. *(UI: PDF shows
  true-scale angle + degree box)*

### Sprint 2 — `draw_on_grid` grading core + symmetry
- CPP-XX6: Migration — add `grid_spec` + `draw_on_grid` choice.
- CPP-XX7: `grade_draw_on_grid` with segment/point normalisation + dispatch
  branch. *(unit: A→B == B→A, exact-set, allow_extra, malformed JSON)*
- CPP-XX8: `grid_spec` schema validator in `Question.clean()`. *(unit: rejects
  missing target, bad coords)*
- CPP-XX9: `question_draw_on_grid.html` + `draw_on_grid.js` click-to-draw
  controller (segments mode). *(UI: draw the symmetry line(s) → marked correct)*
- CPP-X10: Seed fixture — the SATs symmetry + measure questions. *(integration:
  loaddata + grade)*

### Sprint 3 — remaining modes + authoring UX
- CPP-X11: `points` mode (coordinate plotting / marking) in grader + JS.
- CPP-X12: `shape_complete` mode (reflect / finish the symmetrical shape).
- CPP-X13: Visual `grid_spec` authoring widget (click to place shape + target).
- CPP-X14: Worksheet-builder SVG render branch for `draw_on_grid`.

### Sprint 4 — enhancements (optional / separate epic)
- CPP-X15: On-screen draggable virtual protractor for `measure`.
- CPP-X16: Partial credit for `draw_on_grid` (subset scoring with per-line
  marks).
