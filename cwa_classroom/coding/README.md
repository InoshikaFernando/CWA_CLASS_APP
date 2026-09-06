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

Rendered by the standalone compilers and by the worksheet builder's exercise
preview. `templates/coding/exercise_detail.html`, `problem_detail.html`, the
homework take page and the worksheet session still carry their own copies —
migrating them onto this partial is the remaining work, and would also get them
off the CodeMirror CDN.

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
