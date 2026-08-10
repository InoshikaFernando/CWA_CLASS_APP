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

## Second-opinion answer verification

After Claude classifies the questions, an optional **GPT verifier** independently
re-solves each *text-answerable* question (`ai_import/verification.py`). Where
GPT's answer disagrees with Claude's, the question is flagged `needs_review` (with
a `review_reason`) so the teacher checks it on the preview screen before it enters
the bank. This targets the main accuracy risk — a wrong answer slipping through —
without merging two full extractions.

It is best-effort and self-gating:

- Runs only when `OPENAI_API_KEY` is set (and `AI_IMPORT_VERIFY_ENABLED` isn't
  `0`). With no key, imports run Claude-only, exactly as before.
- Only `multiple_choice`, `true_false`, `short_answer`, and `fill_blank`
  questions are checked. Computed/structured types (`column_operation`,
  `long_division`, `plot_*`, `measure`, `number_line`, …) are graded
  deterministically, and image-dependent questions can't be fairly re-solved from
  text alone, so both are skipped.
- A verifier failure logs a warning and lets the import proceed unverified — a
  flaky second opinion never sinks a teacher's upload.
- GPT usage is reported under `extracted_data['verification']`, kept separate
  from Claude's token ledger (`usage`) because GPT is priced differently.

Tuning env vars: `AI_IMPORT_VERIFY_MODEL` (default `gpt-4o`),
`AI_IMPORT_VERIFY_CHUNK` (questions per request, default 40),
`AI_IMPORT_VERIFY_ENABLED` (`0` to force off).

## External services

- **Anthropic Claude API** (PDF analysis + question extraction). Requires `ANTHROPIC_API_KEY`.
- **OpenAI API** (optional second-opinion answer verification). Requires `OPENAI_API_KEY`.
