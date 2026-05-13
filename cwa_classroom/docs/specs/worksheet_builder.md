# Worksheet Builder — Select Questions from Global Bank

## Overview

Teachers currently create worksheets only by uploading PDFs (which are AI-extracted into questions). This feature adds a second creation path: **browse the global question bank**, filter by subject/topic/level, pick questions in order, name the worksheet, and save it. The resulting worksheet is identical to a PDF-extracted one — it can be assigned to any class, reused, and taken by students. The student-facing session page is also upgraded to render the correct answer format per question type (coding panel, MCQ radios, long-division grid, prime-factorisation ladder, etc.) instead of the current MCQ-or-text-input binary.

## Prerequisite — Fix worksheet question-type rendering (BUG)

**The homework module already handles all question types correctly** via the plugin system (`_maths_take_item.html` dispatches per `question_type`, coding gets its own template via `_coding_take_item.html`). **The worksheet module does not** — it has a hardcoded binary that shows radio buttons for MCQ/true-false and a plain text input for everything else.

### Current broken behaviour in `worksheets/session.html` (lines 42–57)

| Question type | What student sees (WRONG) | What they SHOULD see |
|---------------|---------------------------|----------------------|
| `long_division` | Plain text input | Step grid: quotient row + subtract/bring-down rows + remainder (as in `_maths_take_item.html` lines 26–99) |
| `prime_factorization` | Plain text input | Factor ladder with prime inputs and number cells (as in `_maths_take_item.html` lines 101–150) |
| `extended_answer` | Single-line text input | Multi-line textarea; AI-graded or teacher-graded |
| `calculation` | Works (text input is correct) | ✓ No change needed |
| `short_answer` | Single-line text input | Multi-line textarea |
| `fill_blank` | Works (single-line text input is correct) | ✓ No change needed |
| Coding (`CodingExercise`) | Not supported at all — worksheets can only hold `maths.Question` | CodeMirror editor + Piston Run button (as in `_coding_take_item.html`) |

### Current broken behaviour in `WorksheetAnswerView` (views.py lines 560–607)

The grading logic also only handles two paths:
1. MCQ/true_false → checks `selected_answer.is_correct`
2. Everything else → exact text match against `answer_text`

This means:
- **Long division** answers (quotient + remainder) would need to be typed exactly like "123 r 4" — which students wouldn't know, and the grid data isn't submitted.
- **Prime factorization** answers (factor chain) aren't collected from the ladder grid.
- **Extended answers** can't be AI-graded (no call to `grading_service`).
- **Coding answers** can't be evaluated at all.

### Fix approach

Refactor the worksheet session to use the **same plugin-based rendering** that homework uses:

1. **`session.html`**: Replace the inline MCQ/text block with `{% include %}` dispatch to type-specific partials (shared with or copied from the homework partials).
2. **`WorksheetAnswerView`**: Add grading paths for each question type:
   - `long_division` → parse the step grid hidden input ("quotient r remainder") and compare against expected.
   - `prime_factorization` → parse the factor chain hidden input ("2x2x3") and compare against expected.
   - `extended_answer` → call `grading_service.grade_answer()` (same as homework).
   - `coding` → run via Piston, compare stdout against expected output (same as homework).
3. **`WorksheetQuestion` model**: Add `subject_slug` + `content_id` fields (see Data Model section) so worksheets can hold coding exercises alongside maths questions.

This fix is **Sprint 1** of the implementation plan below.

## User stories

| # | Role | Story |
|---|------|-------|
| 1 | **Teacher** | As a teacher, I want to browse the global question bank filtered by subject, topic, and level so I can find relevant questions quickly. |
| 2 | **Teacher** | As a teacher, I want to select questions in a specific order and save them as a named worksheet so I can reuse it across classes. |
| 3 | **Teacher** | As a teacher, I want to assign a worksheet (new or existing) to one or more of my classes so students receive the work. |
| 4 | **Teacher** | As a teacher, I want to re-assign an already-created worksheet to another class (or the same class again) without recreating it. |
| 5 | **HoI** | As a Head of Institute, I want to see all worksheets created within my school so I can monitor content quality. |
| 6 | **HoD** | As a Head of Department, I want to see worksheets created by teachers in my department. |
| 7 | **Student** | As a student, I want the worksheet session to show the correct input format for each question type (MCQ radios, code editor, text box, long-division grid, factor ladder) so I can answer naturally. |
| 8 | **Student** | As a student taking a coding question in a worksheet, I want a code editor with a Run button (Piston) so I can test my code before submitting. |
| 9 | **Parent** | As a parent, I want to see my child's worksheet assignments and scores on my dashboard. |

**Intentionally excluded:** Parents and Students cannot create or assign worksheets.

## Data model

### No new models required

The existing schema already supports everything:

- **`Worksheet`** — `name`, `school`, `level`, `created_by`, `question_count`, `pdf_file` (nullable)
- **`WorksheetQuestion`** — join table with `worksheet`, `question` (FK → `maths.Question`), `order`
- **`WorksheetAssignment`** — links worksheet to a classroom/session
- **`WorksheetSubmission`** / **`WorksheetStudentAnswer`** — student progress and answers

The only change is that a `Worksheet` created via the builder will have `pdf_file = NULL` and `original_filename = ''`. The existing model already allows this (both fields are `blank=True`).

### Schema changes

#### `WorksheetQuestion` — add support for coding exercises

```python
# worksheets/models.py — WorksheetQuestion

subject_slug = models.CharField(
    max_length=50, default='mathematics', db_index=True,
    help_text='Plugin slug: mathematics, coding, etc.',
)
content_id = models.PositiveIntegerField(
    default=0,
    help_text='pk of the content row (maths.Question.id, coding.CodingExercise.id, etc.).',
)
```

This mirrors the pattern already established in `HomeworkQuestion`. The legacy `question` FK stays for backward compatibility with existing PDF-extracted worksheets.

**Unique constraint change:** `unique_together = ('worksheet', 'order')` → add `unique_together = ('worksheet', 'subject_slug', 'content_id')` as a second constraint (keep the order constraint too).

#### `WorksheetStudentAnswer` — add coding answer support

```python
# worksheets/models.py — WorksheetStudentAnswer

answer_data = models.JSONField(
    default=dict, blank=True,
    help_text='Plugin-specific answer payload — e.g. {"code": "...", "output": "...", "language": "python"}',
)
```

This mirrors `HomeworkStudentAnswer.answer_data`.

**Migration risk:** Low — adding nullable/defaulted columns. No data migration needed.

## Resolution / inheritance rules

### Question visibility (which questions can a teacher see?)

1. **Global questions** — `school__isnull=True` — visible to all teachers (these are the platform-curated bank).
2. **School-scoped questions** — `school=teacher.school` — visible to teachers in that school only.
3. **Department-scoped questions** — `department__in=teacher.departments` — visible to teachers in those departments.
4. **Class-scoped questions** — `classroom__in=teacher.classrooms` — visible only to the owning teacher.

Teachers see the union of all four tiers. Questions are never cross-tenant.

### Worksheet ownership

- A worksheet belongs to a `school`. Any teacher in that school can view it.
- Only the `created_by` teacher (or HoI/HoD) can edit or delete it.
- Assigning a worksheet to a class requires the teacher to be a `ClassTeacher` for that class.

## Views, URLs, templates

### New views

| View | URL | Method | Template | Notes |
|------|-----|--------|----------|-------|
| `WorksheetBuilderView` | `worksheets/builder/` | GET | `worksheets/builder.html` | Full-page: subject/topic/level filters, question list, selected-question sidebar |
| `WorksheetBuilderQuestionsAPI` | `worksheets/builder/questions/` | GET (HTMX) | `worksheets/partials/_builder_question_list.html` | HTMX partial — returns filtered questions. Query params: `subject`, `topic`, `level`, `q` (search text), `page` |
| `WorksheetBuilderSaveView` | `worksheets/builder/save/` | POST | redirect → `worksheets:detail` | Receives JSON: `{name, level_id, question_ids: [{subject_slug, content_id}, ...]}`. Creates `Worksheet` + `WorksheetQuestion` rows. |
| `WorksheetBuilderPreviewAPI` | `worksheets/builder/preview/<int:question_id>/` | GET (HTMX) | `worksheets/partials/_builder_question_preview.html` | HTMX partial — shows full question content in a modal/sidebar when teacher clicks a question |

### Modified views

| View | Change |
|------|--------|
| `WorksheetListView` | Add "Create from Question Bank" button alongside existing "Upload PDF" button |
| `WorksheetSessionView` | Render question-type-specific answer templates instead of MCQ-or-text binary |
| `WorksheetAnswerView` | Handle coding answer submissions (run via Piston, store in `answer_data`) |
| `WorksheetAssignView` | Allow re-assignment of existing worksheet to another class (already partially works — just needs UI clarity) |

### New templates

```
templates/worksheets/
├── builder.html                          # Full page: filter panel + question list + selection sidebar
├── partials/
│   ├── _builder_question_list.html       # HTMX: paginated question cards with "Add" buttons
│   ├── _builder_question_preview.html    # HTMX: question detail modal
│   ├── _answer_mcq.html                  # MCQ / True-False radio buttons
│   ├── _answer_text.html                 # Short answer / fill-blank / calculation text input
│   ├── _answer_extended.html             # Extended answer textarea
│   ├── _answer_long_division.html        # Long division step grid
│   ├── _answer_prime_factorization.html  # Factor ladder input grid
│   └── _answer_coding.html              # CodeMirror editor + Run button (reuses homework pattern)
```

### Modified templates

| Template | Change |
|----------|--------|
| `worksheets/list.html` | Add "Create from Question Bank" CTA button |
| `worksheets/session.html` | Replace inline MCQ/text block with `{% include %}` dispatch based on `question.question_type` |
| `worksheets/detail.html` | Show creation method badge ("PDF Upload" vs "Question Bank") |

### URL patterns (added to `worksheets/urls.py`)

```python
path('builder/', views.WorksheetBuilderView.as_view(), name='builder'),
path('builder/questions/', views.WorksheetBuilderQuestionsAPI.as_view(), name='builder_questions'),
path('builder/save/', views.WorksheetBuilderSaveView.as_view(), name='builder_save'),
path('builder/preview/<int:question_id>/', views.WorksheetBuilderPreviewAPI.as_view(), name='builder_preview'),
```

## Permissions

| View | Student | Parent | Teacher | HoD | HoI |
|------|---------|--------|---------|-----|-----|
| `WorksheetBuilderView` | ✗ | ✗ | ✓ (own school) | ✓ (own school) | ✓ (own school) |
| `WorksheetBuilderQuestionsAPI` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `WorksheetBuilderSaveView` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `WorksheetBuilderPreviewAPI` | ✗ | ✗ | ✓ | ✓ | ✓ |
| `WorksheetAssignView` | ✗ | ✗ | ✓ (own classes) | ✓ (dept classes) | ✓ (all classes) |
| `WorksheetSessionView` (coding) | ✓ (assigned) | ✗ | ✗ | ✗ | ✗ |

All views enforce `school` tenant scoping. Teachers can only assign to classes where they are a `ClassTeacher`.

## UI / UX — Builder page

### Layout (3-column on desktop, stacked on mobile)

```
┌─────────────────────────────────────────────────────────────┐
│  Worksheet Builder                                          │
├──────────┬────────────────────────┬─────────────────────────┤
│ FILTERS  │  QUESTION RESULTS      │  SELECTED QUESTIONS     │
│          │                        │                         │
│ Subject  │  Q1: What is 5+3?  [+] │  1. What is 5+3?   [×] │
│ [Maths▾] │  Q2: Solve x=2... [+] │  2. Solve x=2...   [×] │
│          │  Q3: Write a for  [+] │  3. Write a for... [×] │
│ Topic    │      loop...          │                         │
│ [Algebra▾│  Q4: ...          [+] │  ────────────────────── │
│          │                        │  Worksheet name:        │
│ Level    │  ◀ 1 2 3 ▶             │  [________________]     │
│ [Year 5▾]│                        │  Level: [Year 5 ▾]      │
│          │                        │                         │
│ Search   │                        │  [Save Worksheet]       │
│ [______] │                        │                         │
└──────────┴────────────────────────┴─────────────────────────┘
```

- **Filters panel**: Subject dropdown (Maths, Coding, etc.), Topic dropdown (cascading — filtered by selected subject), Level dropdown, free-text search. Changing any filter triggers HTMX GET to `builder/questions/`.
- **Question results**: Paginated list of matching questions. Each card shows question text (truncated), type badge, difficulty badge, topic, level. Click [+] to add to selection. Click the question text to open a preview modal (HTMX).
- **Selected questions sidebar**: Ordered list. Drag-to-reorder (SortableJS). Click [×] to remove. Worksheet name input, level dropdown, and Save button at the bottom.
- Questions already in the selection are greyed out in the results list.
- Coding exercises appear alongside maths questions when `subject=Coding` is selected (queries `CodingExercise` model via the subject plugin system).

## Question-type rendering in student session

The `session.html` template dispatches to a partial based on `question.question_type`:

| `question_type` | Partial | Rendering |
|-----------------|---------|-----------|
| `multiple_choice` | `_answer_mcq.html` | Radio buttons with answer text. Image answers if `answer_image` present. |
| `true_false` | `_answer_mcq.html` | Same as MCQ (True / False as radio options). |
| `short_answer` | `_answer_text.html` | Multi-line textarea. Auto-graded via exact match. |
| `fill_blank` | `_answer_text.html` | Single-line text input with placeholder "Fill in the blank". |
| `calculation` | `_answer_text.html` | Single text input. Numeric comparison (strip whitespace, parse float). |
| `extended_answer` | `_answer_extended.html` | Multi-line textarea. AI-graded or teacher-graded. |
| `long_division` | `_answer_long_division.html` | Step-by-step grid: quotient, remainder, bring-down fields per step. Uses `question.dividend`, `question.divisor`, `question.long_division_step_count`. |
| `prime_factorization` | `_answer_prime_factorization.html` | Factor ladder/tree. Uses `question.target_number`, `question.prime_factorization_rows`. |
| coding (`subject_slug='coding'`) | `_answer_coding.html` | CodeMirror editor + Run button (Piston execution). Reuses pattern from `homework/partials/_coding_take_item.html`. |

### Coding question flow in worksheets

1. `WorksheetSessionView` detects `worksheet_question.subject_slug == 'coding'` and loads the `CodingExercise` instead of `maths.Question`.
2. Template renders `_answer_coding.html` with CodeMirror editor, starter code, expected output, Run button.
3. Run button POSTs to existing `/coding/api/run/` endpoint (Piston).
4. Submit button POSTs to `WorksheetAnswerView` with `answer_data = {"code": "...", "output": "...", "language": "python"}`.
5. `WorksheetAnswerView` evaluates correctness by comparing stdout against `exercise.expected_output` (same logic as homework coding grading).

## Edge cases

| Case | Handling |
|------|----------|
| **Tenant isolation** | Question queryset always scoped: `Q(school__isnull=True) | Q(school=request.user.school)`. Builder views enforce `LoginRequiredMixin` + school check. |
| **Soft-deleted questions** | Questions don't use `removed_at` (they use `is_active` convention via queryset filtering in views). Builder filters to active questions only. If a question is deactivated after being added to a worksheet, it still appears in existing worksheets (data integrity) but shows a "retired" badge. |
| **Empty question bank** | Builder shows a friendly empty-state message with a link to upload questions. |
| **Duplicate selection** | Cannot add the same `(subject_slug, content_id)` pair twice — enforced by unique constraint and client-side disable. |
| **Mixed subjects in one worksheet** | Allowed. A worksheet can contain both maths and coding questions. The `subject_slug` field on `WorksheetQuestion` identifies the source. |
| **Worksheet with zero questions** | Save button is disabled until ≥1 question is selected. Server-side validation rejects empty lists. |
| **Re-assignment to same class** | Allowed — creates a new `WorksheetAssignment` row. Students get a fresh `WorksheetSubmission`. Teacher sees separate assignment entries. |
| **Large question bank (performance)** | Builder questions endpoint is paginated (25 per page). Subject + topic + level filters use indexed FKs. Text search uses `question_text__icontains` (sufficient at current scale; can add full-text index later). |
| **Coding questions without Piston** | If `PISTON_API_URL` is unreachable, the Run button shows an error toast. Student can still submit code (graded later by teacher or when Piston comes back). |
| **Multi-child parents** | Parent dashboard already scopes by child — worksheet scores appear per-child, no change needed. |
| **Long division / prime factorisation answer grading** | These structured answer types store the full step data in `answer_data` JSONField. Grading compares each step against expected values from the question model. |

## Migration & rollout

### Database migrations

1. **Add `subject_slug` and `content_id` to `WorksheetQuestion`** — `CharField` with default `'mathematics'` and `PositiveIntegerField` with default `0`. Non-destructive, backward-compatible.
2. **Add `answer_data` JSONField to `WorksheetStudentAnswer`** — default `dict`. Non-destructive.
3. **Data migration**: Backfill existing `WorksheetQuestion` rows: set `content_id = question_id` for all rows where `question_id IS NOT NULL`.
4. **Add second unique constraint** on `WorksheetQuestion`: `('worksheet', 'subject_slug', 'content_id')`.

### Rollout plan

- No feature flag needed — the builder is a new URL that doesn't affect existing PDF upload flow.
- Existing worksheets continue to work unchanged.
- Student session template changes are backward-compatible (the `{% include %}` dispatch handles all existing question types that were previously hard-coded as MCQ-or-text).
- Deploy order: migrations → code deploy. No rollback risk.

## Out of scope

- **Question creation/editing in the builder** — teacher selects from existing questions only. Creating new questions stays in the existing admin/upload flows.
- **AI-generated worksheets** — "Generate a worksheet for Year 5 Algebra" via Claude. Future feature.
- **Worksheet sharing across schools** — worksheets are school-scoped. Cross-school sharing is a separate feature.
- **Worksheet templates / favourites** — saving a worksheet as a "template" for quick re-creation.
- **Bulk import of questions** — CSV/Excel import of questions into the bank.
- **Worksheet analytics** — per-question difficulty stats, common wrong answers. Future enhancement.
- **Print-friendly PDF export** — generating a printable PDF from a builder-created worksheet.
- **Drag-to-reorder question types** — ordering/matching question types that require drag-and-drop.

## Sprint breakdown

### Sprint 1 — Fix Worksheet Question-Type Rendering (BUG FIX) (6 stories)

This sprint fixes the existing worksheet session so it renders all question types correctly — matching what homework already does. **Must ship before the builder**, because any worksheet (including PDF-uploaded ones) can contain long division, prime factorisation, or extended answer questions that currently render as a broken text input.

| # | Story | Points |
|---|-------|--------|
| CPP-XXX | Add `subject_slug`, `content_id` to `WorksheetQuestion` + `answer_data` to `WorksheetStudentAnswer` + migration + backfill | 3 |
| CPP-XXX | Extract worksheet answer rendering into type-specific partials: `_answer_mcq.html` (MCQ + T/F radios), `_answer_short.html` (short answer textarea), `_answer_text.html` (fill-blank / calculation single-line input), `_answer_extended.html` (extended answer textarea) | 3 |
| CPP-XXX | Port long-division step grid from `_maths_take_item.html` into `_answer_long_division.html` for worksheets — quotient row, subtract/bring-down rows, remainder input, hidden field sync JS | 5 |
| CPP-XXX | Port prime-factorisation factor ladder from `_maths_take_item.html` into `_answer_prime_factorization.html` — prime input cells, number cells, preview, hidden field sync JS | 3 |
| CPP-XXX | Update `WorksheetSessionView` to dispatch to correct partial via `{% include %}` based on `question.question_type` (replace inline MCQ/text binary in `session.html`) | 3 |
| CPP-XXX | Update `WorksheetAnswerView` to grade long-division (parse "quotient r remainder"), prime-factorisation (parse "2x3x5"), and extended-answer (call `grading_service.grade_answer()`) correctly | 5 |

### Sprint 2 — Worksheet Builder Core (5 stories)

| # | Story | Points |
|---|-------|--------|
| CPP-XXX | Build `WorksheetBuilderView` — filter panel (subject/topic/level/search) + paginated question list via HTMX | 5 |
| CPP-XXX | Build question selection sidebar with drag-to-reorder (SortableJS) + worksheet name/level inputs | 5 |
| CPP-XXX | Build `WorksheetBuilderSaveView` — validate + create `Worksheet` + `WorksheetQuestion` rows from selection | 3 |
| CPP-XXX | Build `WorksheetBuilderPreviewAPI` — HTMX modal showing full question detail when teacher clicks a question in the results list | 2 |
| CPP-XXX | Add "Create from Question Bank" button to worksheet list page alongside existing "Upload PDF" | 1 |

### Sprint 3 — Coding Support + Assignment (6 stories)

| # | Story | Points |
|---|-------|--------|
| CPP-XXX | Build `_answer_coding.html` — CodeMirror editor + Piston Run button for worksheet session (port from `_coding_take_item.html`) | 5 |
| CPP-XXX | Update `WorksheetSessionView` to load `CodingExercise` when `subject_slug='coding'` and render the coding partial | 3 |
| CPP-XXX | Update `WorksheetAnswerView` to grade coding answers — run via Piston, compare stdout, store in `answer_data` | 3 |
| CPP-XXX | Include coding exercises in builder question list when subject filter = Coding (query `CodingExercise` via plugin) | 3 |
| CPP-XXX | Allow re-assignment of existing worksheets to another class from detail page | 2 |
| CPP-XXX | Show creation method badge on worksheet list/detail ("PDF Upload" / "Question Bank") | 1 |

### Sprint 4 — Polish & Testing (5 stories)

| # | Story | Points |
|---|-------|--------|
| CPP-XXX | Mobile-responsive builder layout (stacked columns, bottom sheet for selection) | 3 |
| CPP-XXX | Add worksheet scores to parent dashboard (reuse existing homework dashboard pattern) | 3 |
| CPP-XXX | Unit tests — builder views, save logic, question filtering, tenant isolation, grading per question type | 5 |
| CPP-XXX | UI tests — full builder flow, question selection, assignment, student session for each question type | 5 |
| CPP-XXX | Empty states, loading skeletons, error handling for Piston timeout | 2 |
