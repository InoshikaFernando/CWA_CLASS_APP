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
