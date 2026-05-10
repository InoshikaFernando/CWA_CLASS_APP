# ai_import

AI-powered question import. Teachers upload a PDF of past papers or worksheets, the Anthropic Claude API extracts and classifies questions by subject/level/topic, the teacher reviews the proposed import on a preview page, and confirmed questions are written into the question bank.

Per-school monthly usage (pages processed, tokens consumed) is tracked against the school's plan tier so over-quota imports can be blocked or upsold.

## Key models

- **AIImportSession** — staging row for the upload → preview → confirm flow; holds the extracted question payload and embedded images as JSON until the teacher commits.
- **AIImportUsage** — per-school, per-month rollup of pages processed and tokens consumed.

## URL prefix & key routes

Mounted at `/ai-import/` (namespace `ai_import`).

- `upload/` — PDF upload entry point
- `preview/<session_id>/` — review and edit extracted questions
- `confirm/<session_id>/` — write the session into the question bank
- `plans/` — tier selection (Starter / Professional / Enterprise)

## Integration

In `settings.py`:

```python
INSTALLED_APPS = [..., 'ai_import', ...]

ANTHROPIC_API_KEY = os.environ.get('ANTHROPIC_API_KEY', '')
```

In root `urls.py` — must come **before** the catch-all classroom include because the classroom app uses the root prefix:

```python
path('ai-import/', include('ai_import.urls', namespace='ai_import')),
```

## Dependencies

- **accounts** — uploader is a `CustomUser`.
- **classroom** — usage is scoped to `School`; imports write into `classroom.Question` and related curriculum models.
- **billing** — entitlement gating uses the `ai_import_starter` / `ai_import_professional` / `ai_import_enterprise` module slugs.

## External services

- **Anthropic Claude API** (PDF analysis + question extraction). Requires `ANTHROPIC_API_KEY`.
