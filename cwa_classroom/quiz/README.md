# quiz

Generic quiz engine. Owns the quiz-taking flow (question presentation, answer submission, validation, scoring, result reporting) and the JSON API used by both maths and coding quiz UIs. Question/answer **data** lives in the subject apps (today: `maths.Question`, `maths.Answer`, …); `quiz` is the runtime, not the content store.

Three quiz "shapes" are supported:
- **Topic quizzes** — questions filtered to a single topic
- **Mixed quizzes** — questions sampled across topics in a level
- **Basic facts drills** — high-volume timed drills (multiplication, division, times tables)

## Key models

None — engine only. State for a quiz attempt is stored on `maths.StudentAnswer` / `maths.StudentFinalAnswer`; basic-facts results land on `maths.BasicFactsResult`.

## URL prefix & key routes

Three URL modules, included from the root urlconf at three different mount points:

| Module | Mounted at | Purpose |
|---|---|---|
| `quiz.urls` | `/maths/` | basic-facts, times-tables (maths-specific) |
| `quiz.level_urls` | `/maths/` | level/<n>/... routes under maths |
| `quiz.subject_urls` | `/` | `/<subject>/level/<n>/topic/<id>/quiz/` and similar |
| `quiz.api_urls` | `/api/v1/` and `/api/` | JSON quiz API (legacy alias kept) |

## Grading typed answers

Multiple-choice questions post an `Answer` id; everything typed is graded by
`_grade_short_answer` (`quiz/views.py`), which mirrors
`maths.Question.grade_text_answer`:

- **Every** ticked answer row is an accepted alternative — not just the first.
- Matching is case-, space-, exponent- and inequality-insensitive, so the maths
  keypad buttons work wherever a student types.
- There is no multi-select question type: a "which of these are correct?"
  question is authored as a typed answer listing the option labels (`"D and E"`),
  so those are compared as a **set** — `"E,D"` and `"E D"` are the same answer.
  The set rule is bounded to lists of single letters, so an ordered answer
  ("write these in order: 3, 5, 7") stays order-sensitive.
- A numeric answer also grades within `ANSWER_NUMERIC_TOLERANCE`.
- A question the student **invents the answer to** — "Create your own
  subtraction number pattern of six numbers" — is tagged
  `answer_format='pattern'` and graded by `maths.pattern_grading` against what
  the question asked for (same step each time, right operation, right count),
  because there is no answer to store and match. Such a question has no
  correct `Answer` row at all, and an untagged one scores **every** student
  zero — so a typed question that reaches the grader with nothing to match
  against is logged as a content defect rather than failing quietly.
  `manage.py set_pattern_answer_format` finds and tags them;
  `manage.py verify_quiz_grading` checks them by submitting a model pattern
  built from the question's own wording.

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'quiz', ...]

# Engine knobs
ANSWER_NUMERIC_TOLERANCE = 0.05         # ± tolerance for numeric answers
QUIZ_DEDUP_WINDOW_SECONDS = 5           # ignore duplicate submissions within N s
QUIZ_RECENT_RESULT_WINDOW_SECONDS = 30  # show last result if page is refreshed
```

In root `urls.py`:

```python
path('',         include('quiz.subject_urls')),  # /<subject>/level/<n>/topic/<id>/quiz/
path('maths/',   include('quiz.urls')),          # basic-facts, times-tables
path('maths/',   include('quiz.level_urls')),    # level/<n>/...
path('api/v1/',  include('quiz.api_urls')),
path('api/',     include('quiz.api_urls')),      # legacy
```

## Dependencies

- **accounts** — `CustomUser` is the quiz taker.
- **maths** — Question/Answer data and per-attempt rows live here.
- **classroom** — `Subject`, `Level`, `Topic` provide the curriculum scope.

## External services

None.
