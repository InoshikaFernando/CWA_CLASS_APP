# coding

Coding curriculum: Python, JavaScript, HTML, CSS, and Scratch. Two activity types:

- **Exercises** — structured, topic-based tasks with starter code and an expected stdout. Used to teach a concept (variables, loops, …).
- **Problems** — algorithmic challenges scored against test cases, with optional code-quality penalties.

Code is executed in a sandbox via a self-hosted **Piston** instance. Submissions are scored on accuracy + speed, optionally multiplied by a quality factor (cyclomatic complexity, nesting depth, redundant operations).

The app also registers itself with `classroom.subject_registry` so it appears in the subjects hub and sidebars.

## Key models

- **CodingLanguage** — Python / JavaScript / HTML / CSS / Scratch.
- **CodingTopic** — concept group within a language (Variables, Loops, Functions, …).
- **CodingExercise** — exercise (starter code + expected output).
- **CodingProblem** — algorithmic challenge (test cases, scoring rubric).
- **StudentExerciseSubmission** — exercise submission (code, captured output).
- **StudentProblemSubmission** — problem submission (code, test results, score, points, quality multiplier).
- **CodingTimeLog** — aggregate time-spent tracking per student / language.

## URL prefix & key routes

Mounted at `/coding/` (namespace `coding`).

- `/coding/` — language selector
- `/coding/<lang>/` — topic list
- `/coding/<lang>/topics/<topic>/` — exercises by level/difficulty
- `/coding/<lang>/exercise/<id>/` — exercise detail
- `/coding/<lang>/problems/`, `/coding/<lang>/problems/<id>/` — problem set & detail
- `/coding/api/run/` — run code (output only)
- `/coding/api/preview-run/` — run code from a teacher-facing preview
- `/coding/api/submit/<problem_id>/` — submit & test
- `/coding/api/update-time-log/` — time tracking

## Who can reach what

Everything above is student-only: `student_required` redirects teachers, heads
and owners to `home` so elevated roles never accumulate `CodingTimeLog` or
submission rows.

`teacher_required` is its mirror, and `api/preview-run/` is the endpoint that
wears it: a teacher building a coding worksheet needs to *run* an exercise to
check it still produces its expected output, and must do so without landing in
anybody's progress data. It writes nothing — no submission, no time log, no
auto-completion — and rejects the browser-sandbox languages rather than
returning empty output for them.

The playgrounds (`/coding/playground/…`) are `login_required` only: free-form
compilers for everyone, tied to no exercise.

## The shared coding window

The editor-beside-console component every coding page renders:

| File | Role |
|------|------|
| `templates/coding/partials/_code_window.html` | markup; parameters in its header comment |
| `templates/coding/partials/_code_window_head.html` | CodeMirror (vendored), styles — include **once** per page |
| `static/js/code_window.js` | mounts and drives every window on the page |
| `coding/code_window.py` | maps a `CodingExercise` onto the partial's parameters |

It is scoped to its root element rather than to document ids, so one page can
host several windows, and it mounts itself after an htmx swap. A window swapped
into a container that is still hidden needs `CodeWindow.refreshAll()` once the
container is visible — CodeMirror measures itself on mount and otherwise draws
a zero-height box.

`_exercise_code_window.html` is the wrapper for an exercise sitting inside an
answer form: pass it the dict from `CodingPlugin.take_item_context()` and it
forwards everything. Console mode, `mark_complete` false, and a
`code_<content_id>` textarea so the code posts with the form.

Every coding page renders it, and none of them loads CodeMirror from a CDN any
more — a test fails the build if one starts again.

Two CDN dependencies remain on these pages and are NOT covered by that test:
**Blockly** (unpkg, exercise and problem pages, Scratch only) and
**highlight.js** (cdnjs, exercise descriptions). Both fail the same way the
CodeMirror one did — silently, leaving a page that looks fine and does
nothing — so they are worth vendoring next.

A page can take one half only, via `cw_panes`:

| Page | Panes | Why |
|------|-------|-----|
| compilers, homework, worksheet session, builder preview | both | editor and console together |
| exercise detail | `console` + `editor`, as two windows | the exercise text belongs beside the output, so the halves sit in different columns |
| exercise detail (Scratch) | `console` only | blocks are a Blockly workspace, but the generated Python still runs |
| problem detail | `editor` only | graded on test cases, so it reports verdicts rather than stdout |

With `cw_external_run` the window's Run and Ctrl-Enter dispatch
`code-window:run` instead of posting, and every run dispatches
`code-window:result` with the response. That is the seam the exercise page uses
for its score card and mark-complete state machine, and the problem page for
submitting against test cases — neither needs the window to know what an
exercise is. `runWith(code, extra)` runs code the page supplies, which is how
Scratch gets its generated Python (and its blocks XML) to the console.

**Reading a run's verdict.** `api_run_code` also enforces an exercise's
`required_code_patterns`, so where the response carries `exercise_score` the
window reports the server's answer, never its own comparison — otherwise it
would tell a student "matches" on a run the server is about to reject for using
the wrong approach.

**Forms.** CodeMirror writes back to its textarea only on a native submit. A
page that posts over htmx or serialises the form itself (autosave) must go
through `CodeWindow.syncAll()`; the window installs an `htmx:configRequest`
hook that also writes the fresh code into the outgoing parameters, because
htmx has already read the form by the time that event fires.

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'coding', ...]

PISTON_API_URL = os.environ.get('PISTON_API_URL', 'http://localhost:2000')
PISTON_API_TOKEN = os.environ.get('PISTON_API_TOKEN', '')
PISTON_RUN_TIMEOUT_SECONDS = int(os.environ.get('PISTON_RUN_TIMEOUT_SECONDS', '3'))
PISTON_COMPILE_TIMEOUT_SECONDS = int(os.environ.get('PISTON_COMPILE_TIMEOUT_SECONDS', '10'))

ENABLE_QUALITY_SCORING = os.environ.get('ENABLE_QUALITY_SCORING', 'true').lower() != 'false'
QUALITY_MAX_PENALTY = float(os.environ.get('QUALITY_MAX_PENALTY', '0.30'))
```

> ⚠ The Piston container enforces `PISTON_RUN_TIMEOUT` / `PISTON_COMPILE_TIMEOUT` (in **ms**) on the runner side. Keep the Django timeouts ≤ the runner's hard caps or requests will return HTTP 400.

In root `urls.py`:

```python
path('coding/', include('coding.urls', namespace='coding')),
```

`AppConfig.ready()` registers the exercise and problem plugins with the subject registry — no further wiring needed for the hub/sidebar.

## Dependencies

- **accounts** — `CustomUser` is the submitter.
- **classroom** — uses `Level`, `Topic`, and the subject registry.

## External services

- **Piston** (self-hosted Docker, see `docker-compose.piston.yml` at the repo root) — sandboxed code execution.
