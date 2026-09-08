# Page Selection for PDF Question Extraction

## Problem

Teachers upload real papers, and real papers carry pages that hold no questions:

- a **cover or instruction sheet** as page 1 ("You have 45 minutes. Do not turn over…");
- a **formula / reference sheet** in the middle;
- a **marking scheme or worked solutions** across the last couple of pages.

The extraction pipeline sent every page to Claude. The consequences were all bad and all
paid for:

1. **Wasted quota.** A school is billed per page processed (`AIUsageLog.pages`, and in
   `ai_import` the monthly `pages_per_month` entitlement). Front and back matter burned
   pages that could never produce a question.
2. **Junk questions.** Prose from an instruction sheet, and worked answers from a marking
   scheme, come back as "questions" the teacher has to find and untick on the preview.
3. **A hard ceiling hit early.** `WORKSHEET_PAGE_CAP` (default 40) silently truncated the
   tail of a long paper, so a teacher whose questions lived on pages 45–50 of a 60-page
   scan got pages 1–40 and no explanation.

`detect_page_role` already skipped the two *machine-recognisable* cases — a bubble
multiple-choice answer sheet, and an A–D answer key — before any AI call. But an
instruction page or a worked marking scheme reads like ordinary prose to a text detector,
so no amount of detector tuning covers this. The teacher knows which pages matter; they
just had no way to say so.

## Goal

Let the teacher say which pages to extract on every PDF upload flow, through the same
three choices a print dialog offers. Default to all pages, so nothing changes for anyone
who ignores the control.

| Mode | Control | Posts |
|------|---------|-------|
| **All pages** (default) | — | `""` |
| **Range** | from / to number boxes | `5-20`, or `2-` when "to" is blank |
| **Custom** | free text list | `5, 6, 8, 9-11` |

Whichever mode is chosen the form posts ONE field, `page_selection`, holding a
print-dialog spec string, so the server contract and the parser below are the same for
all three. The full spec grammar is therefore still available to anyone who types it:

```
(blank)      every page — the default
all          every page, spelled out
2-           page 2 to the end            (skips a cover / instruction sheet)
1-8          pages 1 to 8                 (skips a marking scheme at the back)
-8           same as 1-8
2-7, 9, 11-  mix ranges and single pages freely
```

Excluded pages are **never rendered and never sent**, so they cost no memory, no
screenshot, and no tokens — and in `ai_import` they don't count against the monthly page
quota either.

## Scope

All three PDF question-extraction flows:

| Flow | Entry | Session model | Background task | Extractor |
|------|-------|---------------|-----------------|-----------|
| Worksheet upload | `worksheets.views.WorksheetUploadView` | `WorksheetUploadSession` | `worksheets.tasks.process_worksheet_pdf` | `extract_and_classify_worksheet` |
| Homework PDF upload | `homework.views.HomeworkPDFUploadView` | `HomeworkUploadSession` | `homework.tasks.process_homework_pdf` | `extract_and_classify_worksheet` |
| Questions Library (AI import) | `ai_import.views.UploadPDFView` | `AIImportSession` | `ai_import.tasks.process_pdf_import` | `ai_import.services.extract_pdf_content` |

Unlike shape-naming mode, `ai_import` **is** in scope: page selection needs nothing from
the bbox crop renderer, only the page loop, which both extractors have.

**Out of scope:** the authored JSON/ZIP upload paths on the worksheet and homework forms.
Those carry no pages — the questions are already structured — so the field doesn't apply.

## Design

### The parser — `worksheets/page_selection.py`

A new module, deliberately free of Django and PyMuPDF imports at module level so the
parser is unit-testable on its own. `fitz` is imported lazily inside the one helper that
needs it.

| Function | Purpose |
|----------|---------|
| `parse_page_selection(spec, page_count)` | The spec → sorted, de-duplicated 1-based page list. Raises `PageSelectionError` with a teacher-facing message. |
| `pdf_page_count(pdf_source)` | Page count from bytes / path / file-like, restoring the stream position so the upload can still be stored. |
| `clean_upload_selection(spec, pdf_source)` | View-side validation → `(cleaned_spec, selected_pages, page_count)`. |
| `selection_summary(spec, selected, total)` | The record stashed on `extracted_data['page_selection']`. |
| `describe_page_selection(extracted_data)` | Preview-notice context, or `None` when nothing was excluded. |
| `format_page_list(pages)` | `[1,2,3,7]` → `"1-3, 7"`, for telling the teacher what happened. |
| `excluded_pages(selected, total)` | The complement — the pages left out. |

Parsing is forgiving where forgiveness is unambiguous and strict where it isn't:

- **Accepted:** commas, semicolons or bare whitespace as separators; spaces around a dash
  (`2 - 4`); pasted en/em dashes and minus signs (`2–4`, `2—4`, `2−4`), because copying a
  range out of a Word document shouldn't be an error.
- **Rejected, with a message naming the bad part:** a page past the end (quoting the PDF's
  real length), page `0`, a backwards range (`7-3`, answered with "write it as 3-7"),
  anything unparseable, and a spec over `MAX_SPEC_LENGTH` (200) — a paste accident is
  reported, never truncated.

Two deliberate normalisations keep the stored data honest:

- A **blank or `all` spec short-circuits before the PDF is opened**. An upload that
  ignores the field costs exactly what it did before the field existed, and an empty or
  unreadable document still fails where it always failed rather than being re-diagnosed as
  a page-selection problem.
- A spec covering **every** page (`1-6` of a 6-page PDF) is stored as `""`, so "selected
  everything" is indistinguishable from "never used the field" and no false exclusion
  notice appears on the preview.

### Absolute page numbers

The single most important invariant: **selection filters which pages are read, it never
renumbers them.** A question found on page 7 is still stamped `page_num: 7`, its embedded
images are still `page7_img1.png`, and its `image_bbox` still resolves through
`doc[page_num - 1]` against the *whole* PDF.

That is what keeps everything downstream working unchanged on a partial extraction —
`render_question_images`, `crop_figure_boxes`, `_render_pdf_region`, the answer-key
matcher, and the "Adjust image" / re-crop modals, which re-open the full PDF from storage
and index it by the same absolute numbers.

Both extractors therefore iterate the selected page numbers rather than `range(len(doc))`,
and both now return three keys instead of one:

- `page_count` — pages **actually extracted**, i.e. what gets billed;
- `total_page_count` — pages in the PDF;
- `page_selection` / `selected_pages` — what was read and what was left out.

`total_page_count` is what the classification prompt quotes ("part of a 12-page paper"),
because the page labels Claude sees are absolute; quoting the selected count would
contradict them.

### Billing

`page_count` remains "pages processed", so the existing ledger call is already correct —
it now naturally charges for the selection rather than the file:

```python
record_ai_usage(school=…, pages=output['page_count'], usage=…)
```

In `ai_import` the pre-enqueue quota check uses `len(selected_pages)` instead of the whole
PDF, which is the point: a teacher with 4 pages left this month can still import the 3
question pages out of a 10-page paper.

### Data model

`page_selection = CharField(max_length=200, blank=True)` on all three session models
(`WorksheetUploadSession`, `HomeworkUploadSession`, `AIImportSession`). Three additive
migrations; blank default, no lock risk on these small staging tables.

The spec is stored **as the teacher typed it** and re-parsed by the worker, so there is one
source of truth rather than a stored page list that could drift from the spec beside it.

### The control — `templates/_partials/page_selection_field.html`

One shared partial, included by all three upload forms. An Alpine component holds the
mode and its inputs and keeps a single hidden `page_selection` input in sync; a live line
underneath states what will happen ("Every page of the PDF will be read." /
"Only page(s) 5-20 will be read.") so the teacher never has to infer it.

Two deliberate properties:

- **No-JS fallback is the old behaviour.** The hidden input starts empty, so a browser
  that never runs Alpine posts `""` — extract everything — rather than a broken form.
- **Incomplete input means all pages, not a partial selection.** Range mode with both
  boxes blank yields `""`, and switching back to *All pages* clears whatever was typed,
  so a teacher who changes their mind can't silently keep excluding pages.

### Views

Each upload view reads `request.POST.get('page_selection')` and validates it through
`clean_upload_selection` **before** creating a session or enqueuing anything. A bad range
is a form error on the upload screen, not a background job the teacher watches die minutes
later. In `ai_import` validation runs before the quota check so the selected count is what
gets compared against the remaining allowance.

### No silent failure

Two reporting paths, both required by the project's no-silent-failure rule:

- **`templates/_partials/page_selection_notice.html`** — included on all three preview
  screens, alongside the existing `skipped_pages_notice`. It states which pages were read
  *and* which were not, so a page missing from an import is a stated choice and a mistyped
  range is obvious before the questions are saved. It renders nothing when every page was
  extracted, and tolerates sessions created before the field existed.
- **`PAGE_ROLE_OVER_CAP`** — pages dropped by `WORKSHEET_PAGE_CAP` now flow into
  `skipped_pages` with the label "beyond the 40-page limit for one upload", plus a warning
  log and a progress message. Previously the cap truncated the tail in silence.

Page selection also *fixes* the cap for the common case: because selection happens first,
pages 45–50 of a 60-page scan are now the only six pages extracted, so the cap never bites.

### Diagnostics

`check_pdf_extraction` gains `--pages`, threaded through
`benchmark.measure_offline` / `measure_live`, so a selection can be checked against a real
paper for free before spending tokens on it:

```bash
python manage.py check_pdf_extraction paper.pdf --pages "2-7, 9"
```

## Permission model

Unchanged. Same role gating as the existing upload views; the field only narrows what the
teacher's own upload extracts.

## Tests

| Suite | Covers |
|-------|--------|
| `worksheets/tests/test_page_selection.py` | The parser exhaustively (every accepted form, every rejection, formatting, summaries); `pdf_page_count` restoring the stream; `clean_upload_selection` short-circuiting on a blank spec; both extractors honouring the selection; absolute page numbers surviving a partial run; the AI never seeing an excluded page; the prompt quoting the true length; over-cap pages being reported. |
| `worksheets/tests/test_page_selection_upload.py` | The worksheet view storing / normalising / rejecting a spec, the task passing it through, only selected pages hitting the usage ledger, and the preview notice. |
| `homework/test_page_selection.py` | The same for the homework flow. |
| `ai_import/tests/test_page_selection.py` | The same for AI import, plus the quota behaviour: the whole paper blocked, a selection within the remaining allowance let through, a still-too-large selection blocked. |
| `ui_tests/uploads/test_pdf_page_selection.py` | Playwright: the field present, optional and self-explaining on every PDF upload form; a typed range accepted; an out-of-range range refused on the upload screen with nothing enqueued; mobile rendering; the preview notice naming both halves. |
