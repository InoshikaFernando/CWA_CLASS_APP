# maths

Maths curriculum and assessments. Owns the question/answer models for all maths topics, runs topic quizzes and mixed quizzes, basic-facts drills (multiplication, division), and times-tables challenges. Tracks per-student progress (scores, attempts, time per level/topic).

The actual quiz-taking flow is delegated to the generic `quiz` engine; `maths` provides the data, the dashboard, and the maths-specific routes.

The app registers a `MathsPlugin` with `classroom.subject_registry` from `AppConfig.ready()` so it appears in the subjects hub and sidebar.

## Key models

- **Question** — maths question (`question_type`: multiple_choice / true_false / short_answer / fill_blank / calculation; difficulty 1–3).
- **Answer** — correct answer + alternatives for a Question.
- **StudentAnswer** — student's per-question answer during a quiz attempt.
- **StudentFinalAnswer** — final submitted answer per question.
- **BasicFactsResult** — aggregate result for a basic-facts drill (level, score, total_questions, points, time_taken_seconds).
- **TimeLog** — time spent per user / level / subject (also used by `coding`).
- **TopicLevelStatistics** — cumulative best_score, attempts, avg_time per student / topic / level.

## URL prefix & key routes

Mounted at `/maths/` (namespace `maths`). The same prefix is shared with `quiz` (basic-facts, level-based) and `number_puzzles`.

- `/maths/` — maths dashboard
- `/maths/topics/`, `/maths/topic/<id>/levels/`, `/maths/level/<n>/`
- `/maths/profile/` — student profile & progress
- `/maths/api/update-time-log/` — time tracking

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'maths', ...]

ANSWER_NUMERIC_TOLERANCE = 0.05  # ± tolerance for numeric answer matching
```

In root `urls.py` — three includes share the `/maths/` prefix:

```python
path('maths/', include('maths.urls', namespace='maths')),
path('maths/', include('quiz.urls')),         # basic-facts, times-tables
path('maths/', include('quiz.level_urls')),   # level/<n>/... quiz routes
path('maths/', include('number_puzzles.urls')),
```

`AppConfig.ready()` registers the maths subject plugin with the subject registry — no further wiring needed.

## Previewing a question before it is imported (`draft_preview.py`)

The three PDF review screens (homework, worksheet, AI import) let a teacher
preview an extracted question exactly as a student will meet it, try answering
it, and see it marked. `maths/draft_preview.py` is what makes that honest:

- `preview_question(draft, promote_blanks=...)` builds a **real** `Question` +
  `Answer` rows from a draft dict inside a transaction it rolls back, so the
  student template and the real graders run unmodified. Nothing survives the
  request — never save an image inside that block, since image writes are not
  transactional.
- `grading_notes(question, draft, ...)` states the rule the marker will apply
  (accepted answers, tolerance, per-gap split) and warns about the traps: a
  comma inside one answer row silently cut across two gaps, a measurement with
  no tolerance, an algebraic answer matched as plain text.
- `promote_blanks` is a per-flow fact, not a preference: the AI Import saver
  calls `Question.apply_blank_format` and the homework PDF saver does not, so a
  "___" sentence imports differently depending on the screen. The preview
  reports what THAT flow does.

The HTTP layer lives in `worksheets/question_preview.py`, shared by all three
screens; each app keeps only its own session-ownership check.

## Where a `shape_select` scene comes from

"Colour all the triangles" is graded by set comparison against the shapes in
`Question.shape_spec`, which is *traced geometry* — polygon vertex lists and
ellipse radii, one entry per shape. There are three ways to author one, and the
PDF path is deliberately not "ask the model for coordinates":

| Route | Where |
|---|---|
| Procedural — scatter N shapes, M of them the target | `shape_select_gen.generate_shape_scene(seed=…)` |
| From an image the teacher uploads | `manage.py import_shape_image --image … --target triangle` |
| From a PDF import | the classifier gives only `shape_target_type`; `shape_detect.trace_shape_select_scenes` traces the crop |

On the PDF route the classifier is asked for **one** thing — which kind of shape
the question asks for — and never for the outlines. `shape_detect` reads those
off the crop with OpenCV contour detection (Claude vision only as an opt-in
fallback, `SHAPE_TRACE_ALLOW_AI=1`, since a worksheet's shapes are the clean
printed line-art the detector was tuned for). A scene that will not trace is
routed to the teacher with its picture kept, never imported as a question with
no shapes to colour.

The answer key is never stored: `geometry_grading.shape_target_ids` derives it
from the figure, so the two cannot drift apart.

## Sketch-a-graph questions (`sketch_graph`)

"Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex,
x-axis and y-axis intercepts and equation of the axis of symmetry" — a whole
family of Year 10–11 quadratics questions, and one the app used to hand to the
teacher as an un-gradeable drawing, because "sketch … graph" reads as a
construction (`worksheets.services._CONSTRUCTION_PATTERNS`).

It is not one. The question asks for two things and the app can take both:

* the **sketch** — the student taps lattice points on the plane the worksheet
  printed and the widget joins them into a smooth curve (the same "join the
  dots" curve a `plot_points` question draws). A freehand stroke is still not
  something this app can take, and it is not what a sketch is marked on: enough
  points, every one of them on the curve, and — for a parabola whose grid shows
  both arms — points either side of the turn.
* the **features the stem names** — one typed box each, marked within a
  tolerance.

Each is one part of a partial-credit grade, so a pupil who draws the curve and
finds three of four features keeps four fifths of the mark.

The pieces:

| Concern | Where |
|---|---|
| The spec (plane + features + optional coefficients) | `Question.sketch_spec`, validated by `geometry_grading.validate_sketch_spec` |
| The curve the sketch is marked against | `geometry_grading.sketch_curve` — the spec's `curve`, else the one the features imply |
| Grading, part by part (the sketch, then each feature) | `geometry_grading.grade_sketch_parts` / `sketch_drawing_part` → `Question.grade_text_answer_parts` |
| Render data (plottable plane for the student, answer figure for feedback) | `Question.sketch_data` |
| The drawn answer (curve, axis of symmetry, labelled key points) | `svg_geometry.sketch_answer_svg` |
| The widget | `templates/maths/partials/_sketch_graph_tool.html` + `static/js/sketch_graph.js` |
| Extraction from a PDF | rule 17 of `worksheets.services.WORKSHEET_SYSTEM_PROMPT` and the matching rule in `ai_import.services`; both fill `sketch_spec` |

`curve` stays optional in a spec — an importer often leaves it out — but a
sketch needs one to be right or wrong against, so `sketch_curve` recovers it
from the features when it can: a parabola from its vertex and any second point
on it (or from both roots and the y-intercept), a line from its two intercepts.
When neither is available the plane keeps no tappable points and no sketch part
is graded — the student is never marked on a drawing nobody can check — and the
preview's grading notes say so.

Feature kinds are `vertex`, `x_intercept`, `y_intercept` and `axis_of_symmetry`
— a spec lists only the ones its question actually asks for. Coordinates are
**decimals, not grid indices**: the vertex of y = x² + x − 2 is (−0.5, −2.25),
and the grader reads the fraction forms a pupil writes those in (`-1/2`,
`-2 1/4`) as the same value.

The correct values live in the spec, never in `Answer` rows, so
`correct_answer_display()` and `display_text_answer()` read them from there —
without that a student who got it wrong is shown a blank where the answer
belongs.

## Questions that cannot be answered: the figure check

A question can pass every answer check the bank has and still be impossible:
the picture it talks about never reaches the page. CPP-406 is the report — a
student met "Measure X" on a live homework with nothing above it and asked how
they were supposed to know what X was. The question was well-formed. It had the
right type, the right value and the right tolerance, and no option checks apply
to a `measure` question at all, so nothing had ever looked at it.

| Concern | Where |
|---|---|
| Is there anything on the page to look at? | `Question.renders_a_figure` — an uploaded image/video, or the figure the type draws for itself (`FIGURE_RENDER_PROPERTIES`) |
| Finding the rest of them | `answer_verification.verify_question_figure` → the `MISSING-FIGURE` code |
| What the student sees instead of a blank stage | `templates/maths/partials/_measure_tool.html`, `templates/worksheets/partials/_answer_measure.html` |
| Catching it at import instead | `ai_import.verification.flag_missing_figures`, which reads the same patterns |

Two ways a question earns `MISSING-FIGURE`, both needing `renders_a_figure` to
be false:

* **by type** — a `measure`, `read_graph`, `identify_coords` … question reads
  its answer *off* a figure. Only an ANGLE measure generates one (a centimetre
  cannot be drawn true-to-scale on an unknown screen), so a length or mass one
  needs an uploaded image or there is nothing to measure.
* **by wording** — the stem points at a figure (`FIGURE_REFERENCE_RE`: "this
  shape", "the diagram below", "shown opposite"; `LABEL_REFERENCE_RE`: "measure
  X") that was never attached.

Both patterns live in `maths/answer_verification.py` and are imported by
`ai_import`, so import-time and bank-time agree on what counts as a figure
reference. They are deliberately narrow — the code is blocking, and a pattern
that fired on questions spelled out in words ("a rectangle with perimeter
20cm") would bury the real backlog rather than surface it.

To find the affected questions in a live bank:

```bash
python manage.py verify_question_answers --check MISSING-FIGURE
```

There is no bulk fix, and there should not be: which picture belongs to a
question is a judgement only a person with the source can make. The code is in
`views_admin.MANUAL_ONLY_CODES` for that reason, and the check page reports and
filters it while sending the reviewer to the editor.

## Dependencies

- **accounts** — `CustomUser` is the student.
- **classroom** — `Subject`, `Level`, `Topic`, `School`, `Department`, `ClassRoom`, plus the subject registry.
- **quiz** — generic quiz-taking engine consumes maths Question/Answer rows.
- **progress** — read-only consumer for dashboards.

## External services

None.
