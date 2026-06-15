# Interactive Protractor / Ruler for the `measure` Question Type

## Problem

The `measure` question type (CPP-330/332/333) renders a true-scale figure — an
auto-generated angle SVG for degree questions, or an author-supplied image for
length/scale questions — and asks the student to type the measured value. On
**paper** (the worksheet print surface) the pupil lays a real protractor or ruler
over the figure. On the **digital** surfaces (homework take, topic quiz) there is
no measuring instrument: the student can only eyeball the figure and guess. That
defeats the learning objective, which is *using the instrument*, not estimating.

## Goal

Add an on-screen, **rotatable + draggable** measuring instrument that overlays the
figure on the digital surfaces:

- `answer_unit` is degrees (`°`, `deg`, `degree(s)`) → a **protractor**.
- `answer_unit` is a length (anything else: `cm`, `mm`, …) → a **ruler**.

The instrument is a **visual aid only**. The student reads it and types the value
into the existing numeric input; the typed value is still the graded answer. The
grader (`maths.geometry_grading.grade_measure`, tolerance-based) is **unchanged**.

## Scope

| Surface | File | Change |
|---|---|---|
| Homework take (digital) | `templates/homework/partials/_maths_take_item.html` | `measure` block renders the shared tool; suppress the duplicate top image for measure |
| Topic quiz | `templates/quiz/partials/topic_question.html` | **new** `measure` render branch (figure + tool + number input) |
| Topic quiz grading | `quiz/views.py` `SubmitTopicAnswerView` | **new** `measure` grading branch → `grade_measure` |
| Shared widget | `static/js/measure_tool.js`, `templates/maths/partials/_measure_tool.html` | new reusable, dependency-free SVG instrument |

**Out of scope (intentionally):**

- **Worksheet** (`templates/worksheets/detail.html`) — a print artifact whose
  figure is true-scale for a *real physical* protractor. An on-screen tool is
  irrelevant there, so it is untouched.
- **Brain Buzz** — a separate model tree (`BrainBuzzSessionQuestion`) with its own
  4-type enum (`mcq/tf/short/fill_blank`), Alpine.js rendering and Kahoot-style
  speed scoring. A tolerance-read instrument fights the speed bonus and would need
  a new enum + Alpine rewrite. Excluded.
- **No new question type, no model change, no migration.** This is a render-layer
  enhancement to the existing `measure` type.

## Design

### Grading parity (the one server change)

Homework grades `measure` through the maths subject plugin
(`maths/plugin.py` → `grade_measure`), so it is already correct. The topic quiz
view (`SubmitTopicAnswerView`) grades inline and has **no** `measure` branch — a
measure answer falls through to the text/`Answer`-row path, finds no correct
`Answer` row (measure stores its target in `numeric_answer`), and is marked wrong
**every time**. We add a `measure` branch that calls `grade_measure(q, raw)` and
reports `numeric_answer + answer_unit` as the correct-answer text. This mirrors the
plugin, so all three auto surfaces grade identically.

### Shared widget — `static/js/measure_tool.js` + `_measure_tool.html`

One partial, one script, used by both digital surfaces (DRY — the same philosophy
as the long-division / prime-factorisation render helpers living on the model).

- The partial renders a positioned **stage**: the figure (`measure_figure_svg` for
  degrees, else `q.image`) plus a Reset button and a one-line hint. It carries
  `data-measure-tool="protractor|ruler"` chosen from the unit.
- The script builds the instrument SVG (generated in JS so the geometry is
  centralised), appends it to the stage as an absolutely-positioned overlay, and
  wires **drag** (move the instrument) and **rotate** (swing it about its
  reference point — the protractor's centre / the ruler's `0` mark) via Pointer
  Events with `setPointerCapture` (mouse + touch). `touch-action: none` stops the
  page scrolling mid-drag.
- The instrument is semi-transparent so the figure shows through, and the overlay
  is `pointer-events:none` except the instrument body + rotate handle, so taps
  elsewhere pass through to the figure/inputs.

### Initialisation across both surfaces

- Homework renders all questions server-side at once → init on `DOMContentLoaded`.
- The quiz advances by replacing `#question-container.innerHTML` (not HTMX, and
  injected `<script>` does **not** execute) → the script also runs a
  `MutationObserver` that mounts any newly-inserted, not-yet-mounted stage. Mounts
  are idempotent (a `data-measure-mounted` flag), so double-init is a no-op.

Script is loaded once per page: `base_quiz.html` (covers the topic quiz) and the
homework take page `extra_head`.

## Caveat: length/ruler on-screen scale

For **degrees**, the protractor is reliable: `angle_svg` draws the angle true to
its value and that is scale-independent, so reading the on-screen protractor gives
the right answer regardless of display size. For **length**, there is *no*
guaranteed physical scale on a screen (CSS px ≠ mm across devices/zoom). The ruler
is therefore a *technique* aid (how to lay and read a ruler), and correctness still
rests on the author-set `numeric_answer` + `answer_tolerance`. The ruler's printed
scale is cosmetic; we do not claim true-to-life millimetres on screen.

## Tests

- **pytest-django** (`quiz/tests.py`): a `measure` answer posted to
  `SubmitTopicAnswerView` is graded **correct within tolerance** and **wrong
  outside it** — covering the new server branch.
- **Playwright** (`ui_tests/`): load a degrees `measure` question in the homework
  take, assert the protractor overlay renders, type a reading, submit, assert the
  result row records the answer.
