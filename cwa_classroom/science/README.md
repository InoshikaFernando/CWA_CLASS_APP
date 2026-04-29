# science

Placeholder app for a future science curriculum. Currently renders a "coming soon" view and reserves the `/science/` URL prefix.

## Key models

None.

## URL prefix & key routes

Mounted at `/science/` (namespace `science`).

- `/science/` — coming-soon view

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'science', ...]
```

In root `urls.py`:

```python
path('science/', include('science.urls', namespace='science')),
```

## Future work

When the curriculum is built out, mirror the `maths` / `coding` pattern:

1. Add models for topics / experiments / questions.
2. Implement a `SciencePlugin` and register it from `AppConfig.ready()` via `classroom.subject_registry.register(...)` so it appears in the subjects hub.
3. Wire quiz routes under the existing `/science/` prefix.

## Dependencies

None today (will depend on `accounts`, `classroom`, and likely `quiz` once content is added).

## External services

None.
