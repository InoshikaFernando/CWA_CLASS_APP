# CPP-302: Display Required Code Patterns per Exercise on Upload Results

## Problem

PR #276 added the aggregate "With Patterns" count and documented the
`required_code_patterns` field, but the upload results page still does not show
**which** exercises received **which** patterns. Acceptance criterion #1 of
CPP-302 — "the upload preview should display `required_code_patterns` for each
exercise" — was therefore left unmet.

## Solution

1. **Parser** (`classroom/upload_services.py` — `CodingExerciseParser.process`):
   Return a per-exercise detail list in `result.detail['exercises']`.
   Each entry: `{title, status, patterns}` where `status` is
   `new` / `updated` / `failed` and `patterns` is the list of required
   code patterns for that exercise (empty list if none).

2. **Template** (`templates/teacher/upload_questions.html`):
   Add a collapsible exercise detail table below the stats row for coding
   uploads. Each row shows the exercise title, a status badge, and the
   patterns rendered as inline chips. Collapsed by default so large uploads
   don't overwhelm the page.

## Data flow

```
JSON upload
  -> CodingExerciseParser.process()
     -> saves to CodingExercise model (unchanged)
     -> builds result.detail['exercises'] list  (NEW)
  -> UploadQuestionsView renders template
     -> template iterates exercises list         (NEW)
```

## No migration required

The `CodingExercise.required_code_patterns` TextField already exists and is
populated correctly by the parser.

## Tests

- `coding/tests/test_upload.py`
  - Parser: returns exercise detail list, status new/updated, order preserved,
    empty patterns → empty list.
  - View: renders detail table for coding uploads, status badges present,
    maths uploads have no exercise-detail section.
