# music

Placeholder app for a future music curriculum. Currently renders a "coming soon" view and reserves the `/music/` URL prefix.

## Key models

None.

## URL prefix & key routes

Mounted at `/music/` (namespace `music`).

- `/music/` — coming-soon view

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'music', ...]
```

In root `urls.py`:

```python
path('music/', include('music.urls', namespace='music')),
```

## Future work

When the curriculum is built out, mirror the `maths` / `coding` pattern:

1. Add models for languages/topics/exercises.
2. Implement a `MusicPlugin` and register it from `AppConfig.ready()` via `classroom.subject_registry.register(...)` so it appears in the subjects hub.
3. Wire quiz/exercise routes under the existing `/music/` prefix.

## Dependencies

None today (will depend on `accounts`, `classroom`, and likely `quiz` once content is added).

## External services

None.
