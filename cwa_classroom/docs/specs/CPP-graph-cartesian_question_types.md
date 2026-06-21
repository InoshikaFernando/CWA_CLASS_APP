# CPP: Graph & Cartesian-Plane Question Types

Four auto-graded question types for coordinate geometry and data-graph reading:
`plot_points`, `plot_line`, `identify_coords`, and `read_graph`.

## 1. Overview

CPP-330 added `draw_on_grid` and `measure` as the first interactive geometry
types. They cover an **unsigned** dot lattice (origin top-left, `0..cols`) and
tolerance-graded numeric reading. They do **not** cover the *signed Cartesian
plane* (four quadrants, negative coordinates, labelled axes — see the blank
−5…5 grid pupils plot on) nor *reading a value off a pre-drawn data graph*
(e.g. a distance-vs-time race graph: "how far had the car travelled at 40
minutes?").

This spec adds four types as **the next instances of the same
structured-interactive pattern** (`maths/models.py` fields +
`maths/geometry_grading.py` pure graders + the `grade_answer` dispatch in
`maths/plugin.py` + a take-item partial). Three share one signed-coordinate
spec (`plane_spec`); the fourth renders a data graph (`graph_spec`) and reuses
the existing `measure` tolerance grading verbatim.

| Type | Student does | Graded by |
|---|---|---|
| `plot_points` | clicks the plane to plot target coordinates | coordinate **set equality** |
| `plot_line` | taps points that auto-connect into a polyline | point + **segment set** equality |
| `identify_coords` | reads plotted point(s), **types** `(x, y)` | parse typed string → **coord set** equality |
| `read_graph` | reads a value off a rendered line graph, **types** a number | `grade_measure` (numeric ± tolerance) |

The user-visible outcome: teachers can author (and AI-PDF import can extract)
coordinate-plotting and graph-reading questions, and students self-mark them on
screen exactly like the paper.

## 2. User stories

- **As a Teacher**, I want to author "plot the point (3, −2)" on a signed
  Cartesian plane and have it marked instantly, instead of grading plotted dots
  by hand.
- **As a Teacher**, I want to author "plot and join (−2, 1), (0, 4), (3, 1)"
  and have the joined line marked, so straight-line graphing is auto-graded.
- **As a Teacher**, I want to upload a worksheet PDF with a Cartesian grid or a
  data graph and have the AI extract it as the right interactive type.
- **As a Student**, I want to tap a four-quadrant grid to plot coordinates and
  see exactly which points I placed (`You plotted: (3, −2)`) before I submit, so
  a mis-tap doesn't silently cost me the mark.
- **As a Student**, I want to read a value off a graph and type it, marked
  within a sensible tolerance, so I learn to read graphs accurately.
- **As a HoI / HoD**, I want these in the same bank, scoping, and reporting as
  every other maths question — no new analytics surface.
- **Parents** inherit results through the existing `is_correct` /
  `points_earned` path — no parent-specific work.

## 3. Data model

Following the established convention — **structured question data lives in
dedicated fields on `maths.Question`; no per-option `Answer` row** for the
auto-graded structured types. We add **two** JSON fields and **zero** new
answer fields (`read_graph` reuses the existing `measure` numeric fields).

### 3.1 New `question_type` choices

```python
# maths/models.py — Question
PLOT_POINTS     = 'plot_points'
PLOT_LINE       = 'plot_line'
IDENTIFY_COORDS = 'identify_coords'
READ_GRAPH      = 'read_graph'

QUESTION_TYPES = [
    ...,                                          # existing entries unchanged
    ('plot_points',     'Plot Points (Cartesian plane)'),
    ('plot_line',       'Plot a Line / Shape (Cartesian plane)'),
    ('identify_coords', 'Identify Coordinates (type the point)'),
    ('read_graph',      'Read a Graph (read off a value)'),
]
```

### 3.2 New fields on `maths.Question`

```python
# Cartesian-plane question data (plot_points / plot_line / identify_coords) -----
plane_spec = models.JSONField(
    null=True, blank=True,
    help_text=(
        "plot_points / plot_line / identify_coords only. Signed coordinate "
        "plane: bounds, interaction mode, given/target points & segments "
        "(signed integer coords). See §3.4."
    ),
)

# Data-graph question data (read_graph) ---------------------------------------
graph_spec = models.JSONField(
    null=True, blank=True,
    help_text=(
        "read_graph only. Render-only line-graph definition (axes, labels, "
        "units, series). The answer reuses numeric_answer / answer_tolerance / "
        "answer_unit (the measure fields). See §3.5."
    ),
)
```

Notes:
- `read_graph` adds **no** answer field — it reuses `numeric_answer`,
  `answer_tolerance`, `answer_unit` from CPP-332. `graph_spec` is **render-only**.
- All fields nullable, consulted only when `question_type` matches ⇒ **no
  backfill, every existing question unaffected.**
- Tenant scoping / visibility inherited unchanged (columns on `Question`).

### 3.3 `clean()` validation (model-level)

Add to `Question.clean()`, mirroring the `draw_on_grid` / `shape_select` blocks:

- `plot_points` / `plot_line` / `identify_coords` ⇒ `plane_spec` required and
  must pass `validate_plane_spec`; raise `ValidationError({'plane_spec': ...})`.
- `read_graph` ⇒ `numeric_answer` required (the value to read); if `graph_spec`
  is present it must pass `validate_graph_spec`. A `read_graph` with neither a
  `graph_spec` nor a `question.image` is still valid at the model level (the
  author may describe the graph in text) but the take-item template guards.
- The plane types and `read_graph` must have **no `Answer` rows** (not MCQ).

### 3.4 `plane_spec` JSON schema

One schema covers the three plane types; `mode` selects interaction + grader.
Coordinates are **signed integers** (negatives allowed), origin at (0, 0).

```jsonc
{
  "bounds": { "xmin": -5, "xmax": 5, "ymin": -5, "ymax": 5 },
  "mode": "points",                       // points | segments
  "given_points": [ [-2, 4] ],            // optional: shown pre-plotted (identify_coords / context)
  "target": {
    // mode=points    -> set of correct dots (plot_points; OR the typed answer for identify_coords)
    "points":   [ [3, -2], [1, 4] ],
    // mode=segments  -> set of correct line segments (plot_line; points auto-connect in tap order)
    "segments": [ { "x1": -2, "y1": 1, "x2": 0, "y2": 4 } ]
  },
  "allow_extra": false                    // extra mark => wrong (strict set match)
}
```

**Normalisation (critical for grading):** every segment is canonicalised by
ordering its two endpoints (`(min, max)` by `(x, y)`) — a line A→B equals B→A.
Points compare as an unordered set. Identical philosophy to
`grade_draw_on_grid`; the *only* logic difference is the bounds check accepts
negatives (`xmin <= x <= xmax`) instead of `0 <= x < cols`.

`identify_coords` uses `target.points` as the answer key and `given_points` to
render the plotted point(s) the student reads. Grading parses the typed string
(`parse_coords`) into a coordinate set and compares for equality.

### 3.5 `graph_spec` JSON schema (`read_graph`)

Render-only — defines the pre-drawn graph the student reads. The answer is the
`numeric_answer` (± `answer_tolerance`, suffixed `answer_unit`).

```jsonc
{
  "title": "Grand Prix Race",
  "x_axis": { "label": "Time", "unit": "min", "min": 0, "max": 110, "step": 10 },
  "y_axis": { "label": "Distance", "unit": "km", "min": 0, "max": 320, "step": 65 },
  "series": [ { "points": [ [20, 65], [40, 130], [60, 200], [80, 260], [100, 305] ] } ]
}
```

**PDF-extracted fallback:** a graph in an uploaded PDF arrives as a *raster*;
the AI cannot reconstruct exact series points reliably. So a PDF-extracted
`read_graph` keeps the **original image** (`question.image`) and the AI-supplied
`numeric_answer` / `tolerance` / `unit`; `graph_spec` is reserved for
hand-authored / generated questions. The take-item template renders the
`graph_spec` SVG when present, else falls back to `question.image`.

## 4. Resolution / inheritance rules

No new cascading config. Visibility resolution
(`school → department → classroom → global`) is unchanged. The only local
fallbacks: `read_graph` tolerance is `answer_tolerance or 0` (null-inheritance =
exact), and `read_graph` render is `graph_spec → question.image`.

## 5. Views, URLs, templates

The delivery path is already centralised in
`MathsPlugin.grade_answer(content_id, post_data)` (`maths/plugin.py`). We add
branches there + take-item render blocks. No new URLs for the student flow.
**Scope excludes the quiz engine** (`quiz/views.py`) — homework + worksheets
only.

### 5.1 Grading (server) — extend the existing dispatch

```python
elif q.question_type in (Question.PLOT_POINTS, Question.PLOT_LINE) and q.plane_spec:
    from maths.geometry_grading import grade_plane
    text_answer = post_data.get(f'answer_{q.id}', '')
    is_correct = grade_plane(q.plane_spec, text_answer)
elif q.question_type == Question.IDENTIFY_COORDS and q.plane_spec:
    from maths.geometry_grading import grade_identify_coords
    text_answer = post_data.get(f'answer_{q.id}', '').strip()
    is_correct = grade_identify_coords(q.plane_spec, text_answer)
elif q.question_type == Question.READ_GRAPH and q.numeric_answer is not None:
    from maths.geometry_grading import grade_measure
    text_answer = post_data.get(f'answer_{q.id}', '').strip()
    is_correct = grade_measure(q, text_answer)
```

New pure functions in **`maths/geometry_grading.py`**:

- `validate_plane_spec(plane_spec)` — structure + signed-bounds + non-empty
  target; raises `ValueError`.
- `validate_graph_spec(graph_spec)` — requires `x_axis` / `y_axis` (with numeric
  `min`/`max`) and a non-empty `series` whose points lie within axis range.
- `grade_plane(plane_spec, payload)` — signed-bounds clone of
  `grade_draw_on_grid`; reuses `_segment_key` / `_point_key`; set equality.
- `parse_coords(text)` — parse `"(-2, 4)"`, `"-2,4"`, `" ( -2 , 4 ) "`,
  multi-point `"(1,2) (3,4)"` → a set of `(x, y)` int tuples; `set()` on garbage,
  never raises.
- `grade_identify_coords(plane_spec, text)` — `parse_coords(text)` == the
  `target.points` set.

All pure (no DB, no request); a malformed submission is **wrong, not a 500**.

### 5.2 Rendering (student) — take-item partial

`templates/homework/partials/_maths_take_item.html` gains four branches,
mirroring the `draw_on_grid` / `shape_select` hidden-field-sync pattern:

- **`plot_points` / `plot_line`** — inline Cartesian SVG (axes, arrowheads,
  numbered ticks, distinct origin) from `plane_data`; a vanilla controller lets
  the student tap lattice points to plot (points mode) or auto-connect them into
  a polyline (segments mode); marks serialise to JSON in a hidden `answer_{id}`
  input. **Two UX guarantees:** (a) a **visible coordinate read-out** (`You
  plotted: (3, −2), …`) so a mis-tap is never silent, and (b) a **generous
  invisible hit-circle (≥ 44px target)** around each lattice point for mobile.
- **`identify_coords`** — the plane with `given_points` pre-plotted + a text
  input with an `(x, y)` format hint.
- **`read_graph`** — the `graph_spec` SVG (axes/labels/units/series) when
  present, else `question.image`; then a numeric input with the `answer_unit`
  suffix (reuses the `measure` input markup).

Render data is exposed on the model as `plane_data` / `graph_data` `@property`
helpers, mirroring `draw_on_grid_data` / `shape_select_data` — no per-view
plumbing.

### 5.3 Authoring (teacher) — AI-PDF pipelines + admin

Both AI-PDF pipelines learn the four types (raw `plane_spec` / `graph_spec`
accepted as JSON in admin; Sprint-later visual authoring widget):

- **`ai_import`** — add the four enum values to `CLASSIFICATION_TOOL`, prompt
  instructions, `question_types` options in `PreviewQuestionsView`, conditional
  POST parsing (target coords / bounds for plane types; numeric / unit for
  `read_graph`), and conditional preview UI. `validate_plane_spec` /
  `validate_graph_spec` run before save.
- **`homework` / `worksheets`** — same in `WORKSHEET_CLASSIFICATION_TOOL`, the
  prompt, `HomeworkPDFPreviewView`, `_save_homework_pdf_questions` `type_map`,
  and `upload_preview.html`.

PDF-extracted `read_graph` keeps `question.image` + measure fields; plane types
get AI-supplied `target` coords + `bounds` rendered via `plane_spec`.

## 6. Permissions

No new permissions — these are `maths.Question` rows and inherit the existing
matrix (HoI/HoD/Teacher author within scope; Student takes; Parent views own
child). Default-deny preserved.

## 7. Edge cases

- **Tenant isolation** — JSON columns on a school-scoped `Question`; no
  cross-tenant leakage. Cross-tenant access returns 404 (existing manager).
- **Malformed student payload** — `grade_plane` / `grade_identify_coords` return
  `False` (never raise) on invalid/empty JSON or garbage text.
- **Empty `plane_spec` / `numeric_answer`** — blocked by `clean()`; the dispatch
  guards (`and q.plane_spec` / `and q.numeric_answer is not None`) mean a
  misconfigured question can never be silently marked correct.
- **Negative coordinates** — first-class; bounds check accepts `xmin < 0`.
- **Extra plotted point** — `allow_extra=False` ⇒ any extra makes the set
  unequal ⇒ wrong ("plot *the* points").
- **Mis-tap on mobile** — generous snap radius + the read-out defend the silent
  wrong-mark failure mode (the highest-risk UX detail).
- **`identify_coords` format variance** — `parse_coords` tolerates parentheses,
  spaces, and bare `x,y`; a clear hint sets expectations.
- **`read_graph` with no graph_spec** — falls back to `question.image`; if
  neither, the question text must describe the graph (author's responsibility).
- **Float precision** — `read_graph` uses Decimal via `grade_measure`; plane
  coords are integers.

## 8. Migration & rollout

1. **Migration** (`maths/00XX_question_plane_graph_specs.py`) — `AddField`
   `plane_spec`, `graph_spec` + `AlterField` on `question_type` choices. All
   nullable ⇒ **non-destructive, no data migration, instant on MySQL 8**.
2. **No backfill** — existing rows ignore the new columns.
3. **No feature flag** — types are invisible until a teacher authors one.
4. **Rollback** — reverse migration drops the two columns and four choices;
   clean (nothing else references them).

## 9. Out of scope

- **Quiz engine** (`quiz/views.py`) — homework + worksheets only this PR.
- **Tap-on-graph for `read_graph`** — typed value only (matches the paper).
- **Free two-dot edge drawing for `plot_line`** — v1 auto-connects consecutive
  taps (open polyline / "plot and join").
- **Curved series / best-fit / gradient questions** — straight polylines only.
- **Visual `plane_spec` / `graph_spec` authoring widget** — raw JSON for now.
- **Reconstructing exact `graph_spec` from a PDF raster** — PDF `read_graph`
  uses image + numeric answer.
- **Partial credit** — all-or-nothing set match, matching 1-mark paper items.
