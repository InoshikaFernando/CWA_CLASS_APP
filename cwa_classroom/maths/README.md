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

## Sketch-a-graph questions (`sketch_graph`)

"Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex,
x-axis and y-axis intercepts and equation of the axis of symmetry" — a whole
family of Year 10–11 quadratics questions, and one the app used to hand to the
teacher as an un-gradeable drawing, because "sketch … graph" reads as a
construction (`worksheets.services._CONSTRUCTION_PATTERNS`).

It is not one. A student cannot draw a curve here, but the curve is not what
these questions are marked on — the **features the stem names** are, and those
can be typed. So the app draws the blank plane the worksheet printed, takes one
box per feature, and marks each within a tolerance.

The pieces:

| Concern | Where |
|---|---|
| The spec (plane + features + optional coefficients) | `Question.sketch_spec`, validated by `geometry_grading.validate_sketch_spec` |
| Grading, feature by feature (partial credit) | `geometry_grading.grade_sketch_parts` → `Question.grade_text_answer_parts` |
| Render data (blank plane for the student, answer figure for feedback) | `Question.sketch_data` |
| The drawn answer (curve, axis of symmetry, labelled key points) | `svg_geometry.sketch_answer_svg` |
| The widget | `templates/maths/partials/_sketch_graph_tool.html` + `static/js/sketch_graph.js` |
| Extraction from a PDF | rule 17 of `worksheets.services.WORKSHEET_SYSTEM_PROMPT` and the matching rule in `ai_import.services`; both fill `sketch_spec` |

Feature kinds are `vertex`, `x_intercept`, `y_intercept` and `axis_of_symmetry`
— a spec lists only the ones its question actually asks for. Coordinates are
**decimals, not grid indices**: the vertex of y = x² + x − 2 is (−0.5, −2.25),
and the grader reads the fraction forms a pupil writes those in (`-1/2`,
`-2 1/4`) as the same value.

The correct values live in the spec, never in `Answer` rows, so
`correct_answer_display()` and `display_text_answer()` read them from there —
without that a student who got it wrong is shown a blank where the answer
belongs.

## Dependencies

- **accounts** — `CustomUser` is the student.
- **classroom** — `Subject`, `Level`, `Topic`, `School`, `Department`, `ClassRoom`, plus the subject registry.
- **quiz** — generic quiz-taking engine consumes maths Question/Answer rows.
- **progress** — read-only consumer for dashboards.

## External services

None.
