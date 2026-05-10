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

## Dependencies

- **accounts** — `CustomUser` is the student.
- **classroom** — `Subject`, `Level`, `Topic`, `School`, `Department`, `ClassRoom`, plus the subject registry.
- **quiz** — generic quiz-taking engine consumes maths Question/Answer rows.
- **progress** — read-only consumer for dashboards.

## External services

None.
