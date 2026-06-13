# Jira Stories — Interactive Geometry & Measurement Question Types

**Parent epic:** [CPP-330](https://codewizardsaotearoa.atlassian.net/browse/CPP-330) (created)
**Spec:** `cwa_classroom/docs/specs/CPP-330_interactive_geometry_questions.md`
**Component:** none — CPP is a team-managed project with no `components` field on create.
**Labels applied:** `migration-required` (1.1 only), `student-facing` (all), `htmx` (1.4 only)

## Created tickets (Sprint 1)

| Story | Ticket | Points | Blocked by |
|---|---|---|---|
| 1.1 Measure fields + migration | [CPP-331](https://codewizardsaotearoa.atlassian.net/browse/CPP-331) | 2 | — |
| 1.2 Tolerance grading | [CPP-332](https://codewizardsaotearoa.atlassian.net/browse/CPP-332) | 2 | CPP-331 |
| 1.3 Generated angle SVG | [CPP-333](https://codewizardsaotearoa.atlassian.net/browse/CPP-333) | 3 | CPP-331 |
| 1.4 Authoring + answer UI | [CPP-334](https://codewizardsaotearoa.atlassian.net/browse/CPP-334) | 3 | CPP-331, 332, 333 |
| 1.5 Worksheet PDF render | [CPP-335](https://codewizardsaotearoa.atlassian.net/browse/CPP-335) | 2 | CPP-333 |

Issue type for all below: **Story**. Points use the skill's scale (2 = 1 day, 3 = 2 days, 5 = 3 days).

---

## Sprint 1 — `measure` question type, end-to-end

### Story 1.1 — Add `measure` question type fields and migration
**Summary:** `Add measure question type with numeric tolerance fields`
**Points:** 2

```markdown
## Background

Real maths papers contain "measure angle a" / "read the scale" questions whose
correct answer is a number accepted within a tolerance band (e.g. 135° ± 2°).
The maths bank currently grades only exact text / MCQ. This story adds the data
model for a new `measure` question type. First of the Sprint-1 chain for the
Interactive Geometry epic; see spec CPP-330_interactive_geometry_questions.md.

## User Story

As a Teacher, I want a measure question type that stores a true value and an
accepted tolerance, so that I can author "measure the angle" questions that mark
near-misses correct like the real mark scheme.

## Acceptance Criteria

- [ ] `maths.Question` gains `numeric_answer` (DecimalField, 10/3, null), `answer_tolerance` (DecimalField, 10/3, null), `answer_unit` (CharField(10), blank).
- [ ] `'measure'` added to `Question.QUESTION_TYPES` and the `MEASURE` constant.
- [ ] `Question.clean()` requires `numeric_answer` when type is `measure`, and forbids `Answer` rows on a `measure` question.
- [ ] Money/float rule respected: tolerance + value are DecimalField, never float.
- [ ] Existing questions unaffected (all new columns nullable/defaulted).
- [ ] Unit tests added (pytest-django) covering: `test_measure_requires_numeric_answer` and `test_measure_rejects_answer_rows` in `maths/tests/test_measure_model.py`.
- [ ] UI tests added (Playwright): none required — no UI surface in this story; covered by Story 1.4. (Justified: pure model/migration.)
- [ ] Migration applies cleanly on a fresh DB and on a copy of prod-shaped data.

## Technical Notes

- Follows the "structured data on the Question row" precedent of `long_division`
  (`dividend`/`divisor`) and `prime_factorization` (`target_number`).
- Columns are nullable adds → non-destructive on MySQL 8, no backfill.

## Definition of Done

- [ ] All acceptance criteria met
- [ ] pytest-django unit tests passing (`pytest maths/tests/`)
- [ ] Self-review with cpp-task-team skill
- [ ] Merged to test, migration applied cleanly on test
- [ ] Merged to main and deployed; Jira ticket Done
```

---

### Story 1.2 — Grade `measure` answers with tolerance in the central dispatch
**Summary:** `Grade measure answers with numeric tolerance`
**Points:** 2

```markdown
## Background

With the `measure` fields in place (Story 1.1), student answers must be graded.
All maths grading funnels through `MathsPlugin.grade_answer` in
`maths/plugin.py`; this story adds the `measure` branch and a pure, testable
grader. Blocked by Story 1.1.

## User Story

As a Student, I want my measured value marked correct when it falls within the
accepted range, so that an accurate measurement that's a degree off is not
unfairly marked wrong.

## Acceptance Criteria

- [ ] New `maths/geometry_grading.py` with `grade_measure(question, raw) -> bool`: parses `raw` to Decimal (stripping the unit char), returns `abs(value - numeric_answer) <= (answer_tolerance or 0)`; returns False on parse failure.
- [ ] `plugin.grade_answer` gains an `elif q.question_type == 'measure' and q.numeric_answer is not None:` branch calling `grade_measure`, returning the standard `is_correct`/`points_earned` dict.
- [ ] NULL tolerance behaves as exact match (0 band).
- [ ] "135°" and "135" both parse (unit char stripped).
- [ ] Unit tests added (pytest-django) covering: `test_within_tolerance_correct`, `test_boundary_inclusive` (133 and 137 for 135±2), `test_outside_tolerance_wrong`, `test_null_tolerance_is_exact`, `test_unit_suffix_stripped`, `test_non_numeric_returns_false` in `maths/tests/test_geometry_grading.py`.
- [ ] UI tests added (Playwright) covering: `test_student_measure_within_tolerance_marked_correct` in `tests/e2e/test_measure_question.py` (student flow; depends on 1.4 partial — may land with 1.4).

## Technical Notes

- Mirror the existing `prime_factorization` / `long_division` branches in
  `plugin.grade_answer`; keep the grader pure (no DB/request) like
  `Question.grade_text_answer`, so worksheet + homework grade identically.

## Definition of Done

- [ ] All acceptance criteria met
- [ ] pytest-django unit tests passing
- [ ] Self-review with cpp-task-team
- [ ] Merged to test and validated; merged to main + deployed; Jira Done
```

---

### Story 1.3 — Generate true-scale angle figures as inline SVG
**Summary:** `Render measure angle figures as generated SVG`
**Points:** 3

```markdown
## Background

A "measure the angle" question must render the figure true-to-scale so a pupil
can measure it on a printed worksheet. Rather than uploading an image, the
figure is drawn programmatically from `numeric_answer`. Part of Sprint 1 of the
Interactive Geometry epic. Blocked by Story 1.1.

## User Story

As a Teacher, I want the angle figure generated automatically from the value I
enter, so that I don't have to draw/upload an image and the printed figure is
guaranteed to match the answer at true scale.

## Acceptance Criteria

- [ ] New `maths/svg_geometry.py` with `angle_svg(degrees, *, size) -> str` returning inline SVG of two rays meeting at a vertex at the given angle, with the angle arc labelled `a`.
- [ ] Output is resolution-independent (uses viewBox, no rasterisation) so it prints true-to-scale.
- [ ] Helper is pure (value in, SVG string out) — no DB, no request.
- [ ] Unit tests added (pytest-django) covering: `test_angle_svg_geometry` (ray endpoints match the requested degrees within rounding), `test_angle_svg_viewbox_present`, `test_extreme_angles` (e.g. 10°, 170°) in `maths/tests/test_svg_geometry.py`.
- [ ] UI tests added (Playwright) covering: `test_measure_figure_visible_in_question` in `tests/e2e/test_measure_question.py` (figure renders in the student view).

## Technical Notes

- Trig in standard lib (`math`); render at integer-ish coordinates for crisp
  lines. Keep an extensible signature so `shape`-based measure figures can be
  added later without breaking callers.

## Definition of Done

- [ ] All acceptance criteria met; unit tests passing
- [ ] Self-review with cpp-task-team; merged to test → main; deployed; Jira Done
```

---

### Story 1.4 — Author and answer `measure` questions in the UI
**Summary:** `Add measure authoring fields and student answer partial`
**Points:** 3

```markdown
## Background

Ties Stories 1.1–1.3 into the teacher authoring form and the student quiz/
homework flow: conditional authoring fields with a live SVG preview, and a
student answer partial with a unit-suffixed numeric box. Blocked by 1.1, 1.2,
1.3.

## User Story

As a Teacher, I want to enter the angle, tolerance, and unit and see a live
preview, so that I can author a measure question confidently.
As a Student, I want to type my measured value into a degrees box and be marked
immediately, so that I get instant feedback.

## Acceptance Criteria

- [ ] Teacher question form shows `numeric_answer`, `answer_tolerance`, `answer_unit` only when type is `measure`, with a live SVG preview (Story 1.3 helper).
- [ ] New `templates/maths/partials/question_measure.html` renders the generated figure + a numeric input with the `answer_unit` suffix; serialises to the standard `answer_{id}` field.
- [ ] Partial is wired into the quiz/homework templates by `question.question_type`, mirroring the `long_division` / `prime_factorization` includes.
- [ ] Unit tests added (pytest-django) covering: `test_measure_form_validates_fields`, `test_measure_form_hides_fields_for_other_types` in `maths/tests/test_measure_form.py`.
- [ ] UI tests added (Playwright) covering: `test_teacher_authors_measure_question`, `test_student_answers_134_for_135_pm2_correct`, `test_student_answers_130_for_135_pm2_wrong` in `tests/e2e/test_measure_question.py`.
- [ ] Tenant isolation verified (a measure question scoped to school A is 404 for school B).

## Technical Notes

- Conditional fields: reuse the existing show/hide pattern used for
  `long_division` / `prime_factorization` authoring fields.

## Definition of Done

- [ ] All AC met; pytest-django + Playwright passing
- [ ] Self-review with cpp-task-team; merged to test → main; deployed; Jira Done
```

---

### Story 1.5 — Render `measure` questions on the worksheet PDF
**Summary:** `Render measure questions in the worksheet builder PDF`
**Points:** 2

```markdown
## Background

Measuring is a protractor-on-paper skill; the recommended delivery for `measure`
is the printed worksheet. The worksheet builder already iterates
`maths.Question`; this story adds a true-scale SVG render branch for `measure`.
Blocked by Story 1.3.

## User Story

As a Teacher, I want measure questions to appear on the worksheet PDF with a
true-scale figure and a labelled answer box, so that pupils can measure with a
real protractor and write the value.

## Acceptance Criteria

- [ ] Worksheet builder renders `measure` questions: the generated SVG figure (Story 1.3) plus an answer box showing the `answer_unit` suffix.
- [ ] Figure prints true-to-scale (SVG viewBox preserved through the PDF pipeline).
- [ ] Non-`measure` questions in the same worksheet render unchanged.
- [ ] Unit tests added (pytest-django) covering: `test_worksheet_includes_measure_svg`, `test_worksheet_other_types_unchanged` in `maths/tests/test_worksheet_measure.py`.
- [ ] UI tests added (Playwright) covering: `test_worksheet_pdf_shows_measure_figure` in `tests/e2e/test_worksheet_builder.py` (teacher builds a worksheet containing a measure question).

## Technical Notes

- Hook into the existing worksheet render loop; branch on `question_type` for the
  SVG path, same place MCQ/other types are rendered.

## Definition of Done

- [ ] All AC met; pytest-django + Playwright passing
- [ ] Self-review with cpp-task-team; merged to test → main; deployed; Jira Done
```

---

## Creation order (Sprint 1)

1. **Story 1.1** (model + migration) — no blockers.
2. **Story 1.3** (SVG helper) — depends only on nothing code-wise; can run parallel to 1.1.
3. **Story 1.2** (grading) — blocked by 1.1.
4. **Story 1.4** (UI authoring + answer) — blocked by 1.1, 1.2, 1.3.
5. **Story 1.5** (worksheet PDF) — blocked by 1.3.

Link all five **is-blocked-by** as above, and **relates-to** the parent epic + spec.

---

## ⚠️ Epic needed first

These stories have **no parent epic yet**. Per house rule a story without an epic
shouldn't exist. Proposed epic:

> **Epic: Interactive Geometry & Measurement Question Types**
> Adds `measure` and `draw_on_grid` auto-graded maths question types so SATs/
> NCEA-style geometry and measurement questions can be authored, self-marked, and
> printed. Spec: CPP-330_interactive_geometry_questions.md.

## Created tickets (Sprint 2 — `draw_on_grid`)

| Story | Ticket | Points | Blocked by |
|---|---|---|---|
| 2.1 draw_on_grid model + grid_spec JSON | [CPP-336](https://codewizardsaotearoa.atlassian.net/browse/CPP-336) | 2 | — |
| 2.2 Set-comparison grading | [CPP-337](https://codewizardsaotearoa.atlassian.net/browse/CPP-337) | 3 | CPP-336 |
| 2.3 grid_spec schema validator | [CPP-338](https://codewizardsaotearoa.atlassian.net/browse/CPP-338) | 2 | CPP-336 |
| 2.4 Click-to-draw partial (segments) | [CPP-339](https://codewizardsaotearoa.atlassian.net/browse/CPP-339) | 5 | CPP-336, 337 |
| 2.5 Seed symmetry + measure fixtures | [CPP-340](https://codewizardsaotearoa.atlassian.net/browse/CPP-340) | 2 | CPP-336, 331 |

Sprint 2 ≈ 14 points. Remaining grid modes (points, shape_complete), the visual
authoring widget, and the worksheet render branch for `draw_on_grid` are Sprint 3
(not yet ticketed).
