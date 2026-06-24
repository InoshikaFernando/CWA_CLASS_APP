# Shape-Select (find & colour) Question Type

`shape_select` — a scene of mixed 2D shapes where the student colours the ones
matching a target type ("colour all the triangles"). Auto-graded by set
comparison. The **fifth instance of the structured-interactive question
pattern** already used by `long_division`, `prime_factorization`, `measure`, and
`draw_on_grid` — see `docs/specs/CPP-330_interactive_geometry_questions.md` for
the shared philosophy.

## 1. Overview

Early-years geometry sheets are full of "find the shape" tasks: a page of mixed
shapes with an instruction like *"Find 3 triangles and colour them."* The bank
could only represent these as multiple-choice. This adds them as a first-class,
interactive, auto-graded type: the student taps shapes to colour them, exactly
like the paper sheet, and is marked instantly.

The figure is **procedurally generated** — there are no uploaded images and no
hand-placed coordinates. A seeded generator scatters shapes on a grid; the
correct-answer set is *derived* from the scene, so it can never drift from the
figure.

## 2. Scope

- **In:** the homework delivery surface (`MathsPlugin.grade_answer` +
  `_maths_take_item.html`), exactly where `draw_on_grid` lives. Model, schema
  validation, grading, render, a seeded starter question, and tests.
- **Out (Phase 2):** the AI/PDF import pipelines (`ai_import/services.py`,
  `worksheets/services.py`, the preview dropdowns). Generated scenes don't need
  AI coordinate extraction, so import is a separate, later piece of work.
- **Out (matches `draw_on_grid`):** the topic-quiz surface
  (`quiz/topic_question.html`). The interactive widget submits a JSON id-set,
  not a single text/MCQ answer, so — like `draw_on_grid` — these questions are
  delivered through homework, not mixed topic quizzes.

## 3. Data model

Follows the established convention: **structured question data lives in a
dedicated field on `maths.Question`; there is no per-option `Answer` row.**

### 3.1 New `question_type` choice

```python
SHAPE_SELECT = 'shape_select'
# ('shape_select', 'Shape Select (find & colour shapes)')
```

### 3.2 New field

```python
shape_spec = models.JSONField(null=True, blank=True)
```

Schema (validated by `validate_shape_spec`, called from `Question.clean()`):

```json
{
  "target_type": "triangle",
  "viewbox": [680, 400],
  "seed": 20260616,
  "shapes": [
    {"id": "s0", "type": "triangle", "cx": 68.0, "cy": 66.0, "size": 32.0, "rot": 12.0},
    {"id": "s1", "type": "circle", "cx": 200.0, "cy": 66.0, "size": 28.0, "rot": 0.0}
  ]
}
```

- `target_type` ∈ `SHAPE_TYPES` = triangle, circle, square, rectangle, ellipse,
  rhombus.
- Each shape: unique string `id`, known `type`, numeric `cx`/`cy`/`size`
  (>0)/`rot`.
- At least one shape must have `target_type` (else unanswerable).
- The **answer key is derived** — `shape_target_ids(spec)` = ids whose
  `type == target_type`. Never stored, so it can't disagree with the figure.

## 4. Grading

`grade_shape_select(shape_spec, payload)` (pure, in `maths/geometry_grading.py`,
never raises). `payload` is the student submission as JSON
`{"selected": ["s0", "s3", ...]}`. Grading is exact set equality:
`shape_target_ids(spec) == set(payload.selected)` — colouring an extra shape or
missing one is wrong ("colour *all* the triangles"). `validation_type = auto`;
no AI tokens. Wired into `MathsPlugin.grade_answer`, the same dispatch as
`draw_on_grid` / `measure`.

## 5. Generation & authoring

`maths/shape_select_gen.generate_shape_scene(target_type, target_count,
total_shapes, *, seed, ...)` — pure, deterministic in `seed` (uses
`random.Random`, never the global RNG). Produces a validated, self-contained
`shape_spec`. The expanded scene is stored (not just the seed), so grading is
independent of RNG-implementation drift. A fixed-seed starter ("Colour all the
triangles.", 14 shapes, 3 triangles) is seeded under the *2D Shapes* topic by
`maths/seed_geometry.py`.

## 6. Render

`Question.shape_select_data` bridges the pure `shape_select_svg` builder into the
take-item template (no per-view plumbing — same pattern as `draw_on_grid_data`).
The template draws the SVG, a hidden `answer_{id}` input, and a Clear button; the
inline JS toggles each shape's fill on tap/Enter and serialises the coloured ids
to the hidden input as `{"selected":[...]}`, syncing on form submit. Outline
stroke uses the `--svg-stroke` variable so the figure works on light/dark and in
print.

## 7. Migration notes

- `0033_question_shape_spec_alter_question_question_type` — adds the nullable
  `shape_spec` JSON column + the new choice. Additive, no table-lock risk.
- `0034_seed_shape_select_question` — idempotent `RunPython` calling the existing
  `seed_geometry.seed` (`get_or_create`), adding only the new starter.

## 8. Test plan

- **Unit** `test_shape_select_grading.py` — pure `grade_shape_select` (correct /
  missed / extra / empty / order-independent / malformed), `validate_shape_spec`,
  and the plugin dispatch (DB).
- **Unit** `test_shape_select_model.py` — type constant/choice, `shape_spec`
  round-trip, `clean()` (requires spec, rejects answers + malformed spec).
- **Unit** `test_shape_select_render.py` — `shape_select_svg`,
  `shape_select_data`, and the partial render.
- **Unit** `test_shape_select_gen.py` — determinism, exact target count, every
  scene validates, generated targets grade.
- **UI** `ui_tests/test_shape_select.py` — tap the triangles → correct; tap an
  extra shape → wrong.
