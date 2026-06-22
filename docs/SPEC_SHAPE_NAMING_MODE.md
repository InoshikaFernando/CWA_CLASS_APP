# Shape-Naming Mode for Worksheet / Homework PDF Upload

## Problem

Teachers upload PDFs that display a **set, grid, or chart of shapes** (e.g. `G1.pdf`)
intending one identification question per shape ("What is the name of this shape?").
The current AI extraction pipeline assumes **one question → one `image_bbox`**, so a
page full of shapes is detected as a *single* visual and produces *one* question with
*one* crop spanning the whole cluster. It never explodes the cluster into per-shape
questions, and there is no question text / answer to attach because the source sheet
rarely prints "name this shape" beside each one.

## Goal

Add an **opt-in "name-the-shape" mode** to the worksheet-based PDF upload flows. When
enabled, the AI emits **one auto-generated question per individual shape**:

- `question_text` = `"What is the name of this shape?"`
- `has_image = true`, `image_bbox` = tight box around **that single shape only**
- `question_type = multiple_choice`, `validation_type = auto`
- `answers` = the correct shape name (`is_correct=true`) + 3 plausible distractors
- `explanation` = one sentence on the shape's defining property
- classification: subject *Mathematics*, strand *Geometry*, topic *2D Shapes* / *3D Shapes*

Claude identifies each shape visually and fills the answer itself.

## Scope

Implemented on the two flows that share the worksheet crop renderer:

| Flow | Entry | Session model | Background task |
|------|-------|---------------|-----------------|
| Homework PDF upload | `homework.views.HomeworkPDFUploadView` | `HomeworkUploadSession` | `homework.tasks.process_homework_pdf` |
| Worksheet upload | `worksheets.views.WorksheetUploadView` | `WorksheetUploadSession` | `worksheets.tasks.process_worksheet_pdf` |

**Out of scope:** the `ai_import` ("Questions Library") flow. It maps questions to *whole
embedded image refs* and has **no bbox crop renderer**, so per-shape cropping is not
possible there without porting the entire `render_question_images` pipeline. Adding the
shape prompt there would yield questions pointing at the full combined image — a broken
half-feature — so it is intentionally excluded.

## Design

No new model tree, no `maths.Question` change. Reuses the existing per-bbox renderer
(`render_question_images` → `_render_clean_diagram` → `_tight_drawings_rect` →
`_trim_whitespace`), which already tight-crops whatever bbox it is handed. The only real
change is **what Claude is instructed to emit** — a per-shape prompt variant — plus
threading a boolean.

### Service layer — `worksheets/services.py`

- New `SHAPE_NAMING_SYSTEM_PROMPT` (per-shape explosion rules).
- New `SHAPE_NAMING_DPI` (default 200) — page screenshots rendered at higher DPI in this
  mode so Claude has more pixels to localise small shapes → tighter bboxes. Bbox
  *correctness* is DPI-independent (coords convert via each page's stored dims); higher
  DPI only improves Claude's *placement precision*.
- `shape_naming: bool = False` threaded through:
  `extract_and_classify_worksheet` → `extract_worksheet_pages(screenshot_dpi=…)` and
  `classify_worksheet_questions` → `_build_system_prompt` / `_classify_page_chunk`.

### Data model

Add `shape_naming = BooleanField(default=False)` to **both** `HomeworkUploadSession` and
`WorksheetUploadSession`. Two additive migrations (nullable-equivalent boolean with
default; safe, no table-lock risk on these small staging tables).

### Views / forms / templates

- Upload views read `request.POST.get('shape_naming') == 'on'` and store it on the
  session at creation time.
- Background tasks read `session.shape_naming` and pass it to
  `extract_and_classify_worksheet`. (No task-signature change for homework — the task
  already loads the session by id.)
- A checkbox **"Name-the-shape mode — make one 'name this shape' question per shape"**
  added to `templates/homework/upload.html` and `templates/worksheets/upload.html`,
  default unchecked.

## Permission model

Unchanged — same `TEACHER_ROLES` gating as the existing upload views. The flag only
alters AI prompting, not access.

## Migration notes

- `homework/migrations/00XX_homeworkuploadsession_shape_naming.py`
- `worksheets/migrations/00XX_worksheetuploadsession_shape_naming.py`

Both add one boolean column with `default=False`. Forward-only, no data backfill.

## Test plan

- **Unit (`worksheets/tests/test_shape_naming.py`)**
  - `_build_system_prompt(shape_naming=True)` returns the shape prompt; `False` returns
    the standard prompt.
  - `extract_worksheet_pages(screenshot_dpi=…)` honours the DPI argument.
  - `extract_and_classify_worksheet(..., shape_naming=True)` threads the flag into
    `classify_worksheet_questions` (patched) and the higher DPI into extraction.
- **Unit (session models)** — default `shape_naming` is `False`; can be set `True`.
- **Unit (views)** — posting the checkbox persists `shape_naming=True` on the session;
  omitting it stores `False`.
- **UI (`ui_tests/test_shape_naming.py`)** — checkbox renders on both upload pages and
  submits (happy path + default-off).
