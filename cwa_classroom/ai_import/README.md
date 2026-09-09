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
- `preview/<session_id>/question-preview/` — one question rendered as the student
  will meet it, and marked by the real grader (see below)
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

## Page selection

The upload form takes an optional **"Pages to extract"** spec in print-dialog syntax
(`2-7, 9`, `2-` for page 2 to the end; blank means every page), stored on
`AIImportSession.page_selection` and re-parsed by the worker. Only the selected pages are
rendered and sent, so skipping a cover sheet or a marking scheme costs no tokens — and the
pre-enqueue quota check charges the *selected* count, not the whole file. Page numbers stay
absolute, so image refs and bboxes are unaffected by a partial extraction. What was left
out is recorded on `extracted_data['page_selection']` and stated on the preview screen.

Parser and helpers: `worksheets/page_selection.py`. Full design:
[`docs/SPEC_PDF_PAGE_SELECTION.md`](../../docs/SPEC_PDF_PAGE_SELECTION.md).

## Page attribution

Pages go to the classifier in batches (`AI_IMPORT_PAGE_CHUNK`, default 20), each
labelled with its absolute page number. The model occasionally answers with a
page's *position in the batch* instead — page 27, sent seventh in the batch
21–40, comes back as `source_page: 7` — and a figure box would then be cropped
from the wrong page. Each request therefore pins `source_page` / `image_page` to
the batch's real page numbers with a schema `enum`, and
`worksheets/page_attribution.py` remaps any positional answer that still comes
back (a number that is not one of the batch's pages but is a valid position
names the page at that position; an impossible number is dropped rather than
trusted). The worksheet / homework upload does the same for its `page_num`.

## Second-opinion answer verification

After Claude classifies the questions, an optional **GPT verifier** independently
re-examines *every* question against its source-page screenshot
(`ai_import/verification.py`). For each question GPT does three things:

1. **classifies** it (its own `question_type`) — validating Claude's classification;
2. **solves** it from scratch and reports its answer — validating Claude's answer;
3. **transcription-checks** the extracted text against the page image.

A confident disagreement on any of the three — a cross-bucket type mismatch, a
different answer, or a mis-transcribed question — flags it `needs_review` (with a
`review_reason`) so the teacher checks it on the preview screen before it enters
the bank. Questions are grouped by page so each page image is sent once.

It is best-effort and self-gating:

- Runs only when `OPENAI_API_KEY` is set (and `AI_IMPORT_VERIFY_ENABLED` isn't
  `0`). With no key, imports run Claude-only, exactly as before.
- **All** question types are covered. Computed (`column_operation`,
  `long_division`, …) and image-dependent / visual (`plot_*`, `read_graph`,
  `measure`, `number_line`) questions — which a text-only pass had to skip — are
  handled by attaching the page image (GPT vision). Set `AI_IMPORT_VERIFY_VISION=0`
  to force a cheaper text-only pass (no images; the transcription check is then
  skipped). To attach the right page, the classifier stamps each question with a
  `source_page`; it falls back to `image_page` / the ref's page, then to text-only.
- Type-mismatch flagging is *coarse* (cross-bucket only) so interchangeable types
  (`short_answer` vs `calculation`) don't produce noise.
- A verifier failure logs a warning and lets the import proceed unverified — a
  flaky second opinion never sinks a teacher's upload.
- GPT usage is reported under `extracted_data['verification']` (with
  `type_flags` / `answer_flags` / `transcription_flags` counts), kept separate
  from Claude's token ledger (`usage`) because GPT is priced differently.

Tuning env vars: `AI_IMPORT_VERIFY_MODEL` (default `gpt-4o`, must support vision),
`AI_IMPORT_VERIFY_CHUNK` (questions per request, default 40),
`AI_IMPORT_VERIFY_VISION` (`0` to force text-only),
`AI_IMPORT_VERIFY_ENABLED` (`0` to force off).

## External services

- **Anthropic Claude API** (PDF analysis + question extraction). Requires `ANTHROPIC_API_KEY`.
- **OpenAI API** (optional second-opinion answer verification). Requires `OPENAI_API_KEY`.
