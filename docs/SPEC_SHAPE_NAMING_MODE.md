# Name-the-Shape Items in the Worksheet / Homework PDF Upload

> **Superseded design note.** This document originally specified an opt-in
> *"Name-the-shape mode"* checkbox on the upload form. That mode is gone. What
> replaced it, and why, is below; the original design is kept at the end for
> the record.

## Problem

Teachers upload PDFs that display a **set, grid, or chart of shapes** intending one
identification question per shape ("What is the name of this shape?"). The source sheet
rarely prints a question beside each shape, so the ordinary one-question-one-bbox
extraction turned a page of shapes into a single question with one crop of the whole
cluster.

The first fix was a **whole-upload mode switch**. It only worked when the entire PDF was
a shapes sheet: the switch swapped the system prompt for one that emitted *only* shape
questions and skipped everything else. Real sheets are mixed — a row of shapes to name
above six ordinary questions — and for those a teacher had to choose which half of the
page to lose.

## Design (current)

There is no mode. The classifier decides **per item**.

### An extractor-only question type: `name_the_shape`

`worksheets/services.py` adds `name_the_shape` to the classification tool's
`question_type` enum (`NAME_THE_SHAPE_TYPE`). Rule 19 of `WORKSHEET_SYSTEM_PROMPT`
tells the model when to use it: a sheet, section, chart, grid or row that *displays*
shapes for the student to identify — with no question text of their own, or under
"name each shape" — is **one question per individual shape**, emitted alongside whatever
ordinary questions the same page carries. Each such question has:

- `question_type = "name_the_shape"`
- `question_text = "What is the name of this shape?"`
- `has_image = true`, `image_bbox` = a tight box around **that single shape only**
- `answers` = the correct shape name + 3 plausible distractors
- `validation_type = "auto"`, one-sentence explanation, Mathematics / Geometry / 2D Shapes

A shape that is merely the figure of an ordinary question ("find the area of this
rectangle") keeps its own type — rule 19 says so explicitly.

### Normalised before the preview

`_normalise_name_the_shape` runs on every chunk result. Each `name_the_shape` item
becomes a `multiple_choice` question carrying a `shape_naming: true` marker — exactly
what the old mode produced, now item by item. The marker shows as a **🔷 Name the shape**
badge on the homework and worksheet previews; the question bank stores plain multiple
choice, so `maths.Question`, the take page and grading are untouched. An item that would
be unanswerable — no figure box to crop the shape from, or not exactly one correct
option — is routed to ⚠ Review with the reason rather than saved looking complete.

### What was removed

- The `shape_naming` checkbox on `templates/homework/upload.html` and
  `templates/worksheets/upload.html` (replaced by a line saying shapes are detected
  automatically).
- `HomeworkUploadSession.shape_naming` and `WorksheetUploadSession.shape_naming`
  (`homework/0030`, `worksheets/0010` drop the columns; reversible).
- The `shape_naming` parameter threaded through `extract_and_classify_worksheet`,
  `classify_worksheet_questions`, `_classify_chunk_adaptive`, `_classify_page_chunk` and
  `_build_system_prompt`; `SHAPE_NAMING_SYSTEM_PROMPT`; `SHAPE_NAMING_DPI` (the higher
  screenshot DPI bought nothing — the vision API downsizes an A4 page below 150-DPI
  size anyway, and bbox correctness never depended on it).

### Out of scope

The `ai_import` flow keeps its own prompt; adding rule 19 there is a follow-up.

## Tests

- `worksheets/tests/test_name_the_shape.py` — the enum carries the type but the review
  dropdown does not; the prompt carries rule 19; a mixed chunk result (ordinary question
  + shape items) is normalised item by item; items missing a box or a single correct
  option are flagged; the upload page no longer renders the checkbox and a posted
  `shape_naming=on` is ignored.
- `homework/test_shape_naming.py` — the homework upload page has no checkbox; the task
  no longer forwards a mode flag.

---

## Original design (2026-06, superseded)

Opt-in "name-the-shape mode": a checkbox on both upload forms stored on the session
(`shape_naming` boolean), threaded to `extract_and_classify_worksheet`, which rendered
pages at `SHAPE_NAMING_DPI` (200) and swapped `WORKSHEET_SYSTEM_PROMPT` for
`SHAPE_NAMING_SYSTEM_PROMPT` — a prompt that emitted only shape questions and skipped all
other text on the sheet.
