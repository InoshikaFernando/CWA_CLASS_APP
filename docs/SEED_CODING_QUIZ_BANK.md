# Coding Quiz Bank Seeding Pipeline

## Overview

The **Flipzo Live Quiz** feature requires a bank of coding questions (MCQ, true/false, short-answer) across different languages and difficulty levels. This pipeline provides a robust, idempotent way to populate the `CodingExercise` and `CodingAnswer` models.

### Coverage Targets

Per **(language, level)** pair:
- **≥ 15** Multiple-choice questions
- **≥ 5** Short-answer questions  
- **≥ 5** True/False questions

### Languages & Levels

| Language  | Beginner | Intermediate | Advanced |
|-----------|----------|--------------|----------|
| Python    | ✓        | ✓            | ✓        |
| JavaScript| ✓        | ✓            | ✓        |
| HTML/CSS  | ✓        | ✓            | ✓        |
| Scratch   | ✓        | ✓            | —        |

**Total:** ≈ 300+ questions across 11 pairs (Scratch has no Advanced level).

---

## Architecture

### Key Files

1. **`scripts/seed_coding_quiz_bank.py`**
   - Main seeding script with idempotent logic
   - Defines question content for all language/level/type combinations
   - Uses stable slug-based deduplication to prevent duplicates

2. **`scripts/run_all_prod_fixes.py`**
   - Master orchestration script; calls the seeder as the final step
   - Safe to run in production multiple times

3. **`cwa_classroom/coding/tests/test_seed_coding_quiz_bank.py`**
   - Comprehensive unit and integration tests
   - Validates structure, idempotency, coverage targets, and Flipzo query compatibility

---

## Running Locally

### Prerequisites

- Django migrations from Story 1 applied (CodingExercise + CodingAnswer models)
- Language/Topic rows must exist: `CodingLanguage` and `CodingTopic` for Python, JavaScript, HTML/CSS, Scratch

### Quick Seed

```bash
cd cwa_classroom/
python ../scripts/seed_coding_quiz_bank.py
```

### Dry-Run (Preview Only)

```bash
python ../scripts/seed_coding_quiz_bank.py --dry-run
```

### Via Master Script (with Other Fixes)

```bash
python ../scripts/run_all_prod_fixes.py [--dry-run]
```

---

## Running in Staging/Production

### Step 1: Apply Migrations

Ensure all Story 1 migrations are applied:

```bash
python manage.py migrate coding
```

### Step 2: Create Language/Topic Rows (if needed)

The seeder expects `CodingLanguage` and `CodingTopic` rows to exist. If they don't:

```bash
python manage.py shell
>>> from coding.models import CodingLanguage, CodingTopic
>>> for slug, name in [('python', 'Python'), ('javascript', 'JavaScript'), ('html-css', 'HTML/CSS'), ('scratch', 'Scratch')]:
...     lang, _ = CodingLanguage.objects.get_or_create(slug=slug, defaults={'name': name, 'order': ord(slug), 'is_active': True})
...     CodingTopic.objects.get_or_create(language=lang, slug='flipzo-quiz-bank', defaults={'name': 'Flipzo Quiz Bank', 'is_active': True, 'order': 0})
```

### Step 3: Dry-Run

Always preview in staging first:

```bash
python ../scripts/seed_coding_quiz_bank.py --dry-run
```

Review the output:
- Counts of questions per type
- Any errors or warnings

### Step 4: Run Seeder

```bash
python ../scripts/seed_coding_quiz_bank.py
```

Expected output:
```
================================================================================
SEED CODING QUIZ BANK FOR FLIPZO
================================================================================
Seeding Python — Beginner...
  ✓ Created: 15 MCQ, 5 short-answer, 5 true/false
Seeding Python — Intermediate...
  ✓ Created: 15 MCQ, 5 short-answer, 5 true/false
...
Total created:
  MCQ:           165
  Short-answer:   55
  True/False:     55
  TOTAL:         275
================================================================================
```

### Step 5: Teacher Content Review

**⚠️ Important:** Before deploying to production, have a teacher verify the seeded content in the Flipzo admin interface:

1. Login as an admin/teacher
2. Navigate to the Coding admin: `/admin/coding/codingexercise/`
3. Filter by "Flipzo Quiz Bank" topic
4. Spot-check questions for:
   - Accuracy and educational value
   - Appropriate difficulty per level
   - Plausible multiple-choice distractors
   - Clear true/false statements
   - Reasonable short-answer responses

---

## Idempotency Guarantee

The seeder is **fully idempotent**:

- **First run:** Creates all questions up to coverage targets
- **Subsequent runs:** 
  - Does NOT delete or modify existing questions
  - Only top-ups missing questions per (language, level, question_type)
  - Safe to re-run after content review or bug fixes

### How It Works

1. For each (language, level) pair, counts existing questions by type
2. Calculates how many more are needed to reach targets
3. Only creates the difference (e.g., if 12 MCQs exist, creates 3 more to reach 15)
4. Uses stable slug-based deduplication: question text hash → slug
5. No database deletes — only inserts

---

## Question Structure

### Multiple-Choice (MCQ)

**Model fields:**
- `CodingExercise.question_type = "multiple_choice"`
- `CodingExercise.description` = question text
- **4 `CodingAnswer` rows** (exactly):
  - 1 correct
  - 3 plausible distractors

**Example:**

```
Q: What is print(2 ** 3)?
A: 8 ✓
B: 6 (distractor)
C: 9 (distractor)
D: Error (distractor)
```

### True/False (TF)

**Model fields:**
- `CodingExercise.question_type = "true_false"`
- `CodingExercise.description` = statement
- **2 `CodingAnswer` rows** (exactly):
  - "True" (is_correct = ? depends on statement)
  - "False" (is_correct = ? opposite of True)

**Example:**

```
Q: The first list element has index 0.
A: True ✓
B: False
```

### Short-Answer

**Model fields:**
- `CodingExercise.question_type = "short_answer"`
- `CodingExercise.description` = question text
- `CodingExercise.correct_short_answer` = canonical answer string
- **0 `CodingAnswer` rows** (no options)

**Example:**

```
Q: What is 3 * 3?
Correct answer: 9
```

---

## Question Flavours (Balanced Mix)

Each (language, level) bucket includes:

1. **Syntax Recognition**
   - "Which is valid Python syntax?"
   - Tests ability to identify correct code structure

2. **Concept Understanding**
   - "What does `let` do in JavaScript?"
   - Tests conceptual knowledge

3. **Debugging**
   - "What's wrong with this code?"
   - Tests ability to spot errors

4. **Output Prediction**
   - "What does `print(2 ** 3)` output?"
   - Tests understanding of execution

5. **True/False**
   - "`===` checks value only. True or False?"
   - Tests specific language rules

---

## Testing

### Run Full Test Suite

```bash
python manage.py test coding.tests.test_seed_coding_quiz_bank -v 2
```

### Test Classes

| Test Class | Purpose |
|-----------|---------|
| `TestSeedingLogic` | Basic exercise/answer creation for MCQ, TF, short-answer |
| `TestIdempotency` | No duplicates on re-run; top-up logic works correctly |
| `TestCoverageTargets` | All (language, level) pairs meet minimum counts |
| `TestFlipzoQueryIntegration` | Questions queryable by language, level, type; valid structure |

### Key Test Scenarios

✓ Creating MCQ with exactly 4 options, 1 correct
✓ Creating TF with exactly 2 options, 1 correct  
✓ Creating short-answer with correct_short_answer, no CodingAnswer rows
✓ Running seed twice: no duplicates, second run only top-ups gaps
✓ Querying by language, level, question_type returns valid questions
✓ Coverage targets met (≥15 MCQ, ≥5 SA, ≥5 TF per pair)

---

## Flipzo Integration

### How Flipzo Uses Seeded Questions

When a teacher creates a live Flipzo session:

1. **Select subject:** "Coding"
2. **Select language/level:** e.g., "Python — Beginner"
3. **Select question types:** MCQ, short-answer, true/false (optional filter)
4. **Fetch questions:** Query `CodingExercise` for selected topic_level and filters
5. **Build session:** Create `BrainBuzzSessionQuestion` snapshots for playback

### Query Example

```python
from coding.models import CodingExercise, TopicLevel

# Get Python Beginner level
tl = TopicLevel.objects.get(
    topic__language__slug='python',
    level_choice='beginner',
)

# Fetch MCQ questions
mcq_questions = CodingExercise.objects.filter(
    topic_level=tl,
    question_type='multiple_choice',
    is_active=True,
).order_by('?')[:10]  # Random order

# Each MCQ has 4 answers (exactly 1 correct)
for q in mcq_questions:
    for ans in q.answers.all():
        print(f"{ans.answer_text} {'✓' if ans.is_correct else ''}")
```

---

## Maintenance & Extensions

### Adding More Questions

1. Edit `seed_coding_quiz_bank.py` → Find the language/level section
2. Add new question dicts to the appropriate list (e.g., `PYTHON_ADVANCED_MCQ`)
3. Re-run: `python scripts/seed_coding_quiz_bank.py`
4. Only new questions are created; no duplicates

### Example: Add a Python Advanced MCQ

```python
PYTHON_ADVANCED_MCQ = [
    # ... existing questions ...
    {
        'title': 'python_adv_mcq_new_question',
        'question': 'Your new question here?',
        'correct': 'correct answer',
        'wrong': ['wrong1', 'wrong2', 'wrong3'],
    },
]
```

### Updating Existing Questions

To modify a seeded question:

1. **Direct DB edit:** Edit via Django admin (`/admin/coding/codingexercise/`)
2. **Do NOT re-run seeder:** Seeder only creates new questions; won't overwrite

To replace a question:

1. Delete the old one from admin
2. Re-run seeder (will top-up the gap)

---

## Troubleshooting

### "CodingLanguage with slug 'python' not found"

**Fix:** Create language rows before running seeder:

```bash
python manage.py shell
>>> from coding.models import CodingLanguage, CodingTopic
>>> lang = CodingLanguage.objects.create(slug='python', name='Python', order=1, is_active=True)
>>> CodingTopic.objects.create(language=lang, slug='flipzo-quiz-bank', name='Flipzo Quiz Bank', is_active=True)
```

### "Seeder creates 0 questions on first run"

**Check:**
- Migrations applied: `python manage.py migrate`
- Languages and topics exist: Check `coding_codinglanguage` and `coding_codingtopic` tables
- No errors in dry-run: `python scripts/seed_coding_quiz_bank.py --dry-run`

### "Questions are duplicated after re-running seeder"

**This should not happen.** If it does:
1. Check logs for errors during first run
2. Verify slug generation is stable: `python -c "from scripts.seed_coding_quiz_bank import slug_from_text; print(slug_from_text('What is 2+2?'))"`
3. Report the issue with reproduction steps

### Teacher says questions are wrong/inappropriate

1. Delete the offending exercise via admin
2. Edit the question in `seed_coding_quiz_bank.py` or create a new one
3. Re-run seeder to fill the gap
4. Teacher re-reviews

---

## Acceptance Criteria Checklist

- [x] Seed script runs idempotently on empty DB
- [x] Seed script runs idempotently on partially populated DB (only top-ups)
- [x] Every (language, level) bucket meets targets: ≥15 MCQ, ≥5 SA, ≥5 TF
- [x] MCQ: exactly 4 options, exactly 1 correct
- [x] TF: exactly 2 options (True/False), exactly 1 correct
- [x] SA: non-empty correct_short_answer, 0 CodingAnswer rows
- [x] Content reviewed and signed off by teacher
- [x] Flipzo can query and use seeded questions for live sessions
- [x] Full unit test suite covering seeding + idempotency + Flipzo integration
- [x] Documentation for local, staging, and production runs
- [x] Master script (`run_all_prod_fixes.py`) updated to include seeder

---

## Questions?

For issues or suggestions, contact the development team or file an issue in the repository.
