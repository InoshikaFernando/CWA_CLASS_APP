# progress

Cross-subject progress reporting and dashboards. Aggregates data from the subject apps (`maths`, `coding`, …) into per-student and per-class views. Owns the JSON API used by client-side charts on the dashboards.

This is a **utility / view-only** app — it defines no models. All progress data lives in the subject apps; `progress` reads from them.

## Key models

None. Reads from:
- `maths.BasicFactsResult`, `maths.StudentAnswer`, `maths.TimeLog`, `maths.TopicLevelStatistics`
- `coding.StudentProblemSubmission`, `coding.CodingTimeLog`

## URL prefix & key routes

Mounted at the project root.

- `/student-dashboard/` — student's overall progress home
- `/student/<id>/progress/` — teacher view of a student's progress

## API

JSON endpoints for charts. Mounted at both `/api/` (legacy) and `/api/v1/` (canonical):

```python
path('api/v1/', include('progress.api_urls')),
path('api/',    include('progress.api_urls')),  # legacy, kept for compatibility
```

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'progress', ...]
```

In root `urls.py`:

```python
path('', include('progress.urls')),
path('api/v1/', include('progress.api_urls')),
path('api/',    include('progress.api_urls')),  # legacy
```

## Dependencies

- **maths** — primary data source (quiz attempts, time logs, topic stats).
- **coding** — problem submissions and time logs.
- **classroom** — `Subject`, `Level`, `Topic`, `ClassRoom` for grouping and labels.
- **accounts** — `CustomUser` for student/teacher identity.

## External services

None.
