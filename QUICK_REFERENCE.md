# Quick Reference: Coding Quiz Bank Seeding

## One-Minute Summary

A robust seeding pipeline that populates **275+ questions** for the Flipzo live-quiz feature across 4 languages and 3 difficulty levels.

### Key Files

| File | Purpose |
|------|---------|
| `scripts/seed_coding_quiz_bank.py` | Main seeding script (1,200 lines) |
| `scripts/run_all_prod_fixes.py` | Master orchestration (includes seeder) |
| `coding/tests/test_seed_coding_quiz_bank.py` | Comprehensive test suite |
| `docs/SEED_CODING_QUIZ_BANK.md` | Full documentation |

---

## Running the Seeder

### Local (Development)

```bash
cd cwa_classroom/
python ../scripts/seed_coding_quiz_bank.py
```

### Dry Run (Preview Only)

```bash
python ../scripts/seed_coding_quiz_bank.py --dry-run
```

### Staging/Production (via Master Script)

```bash
python ../scripts/run_all_prod_fixes.py
```

---

## How It Works

1. **Idempotent:** Uses MD5-hash-based slug deduplication
2. **Top-up:** Only creates missing questions to reach targets
3. **Safe:** No deletes or overwrites; production-safe
4. **Atomic:** Uses database transactions

### Coverage Targets (Per Language/Level)

- **≥ 15** Multiple-Choice (MCQ)
- **≥ 5** Short-Answer (SA)
- **≥ 5** True/False (TF)

### Total: 11 Pairs × 25 Questions = 275 Questions

| Language  | Beginner | Intermediate | Advanced |
|-----------|----------|--------------|----------|
| Python    | ✓        | ✓            | ✓        |
| JavaScript| ✓        | ✓            | ✓        |
| HTML/CSS  | ✓        | ✓            | ✓        |
| Scratch   | ✓        | ✓            | —        |

---

## Question Types

### Multiple-Choice (MCQ)
- 4 options exactly
- 1 correct answer
- 3 plausible distractors

### True/False (TF)
- 2 options: "True" and "False"
- 1 correct answer

### Short-Answer (SA)
- Canonical answer string
- No multiple-choice options

---

## Before Running (Checklist)

- [ ] Migrations applied: `python manage.py migrate coding`
- [ ] Languages exist (Python, JavaScript, HTML/CSS, Scratch)
- [ ] Topics exist ("Flipzo Quiz Bank" per language)

---

## After Running (Verification)

1. **Check admin:** `/admin/coding/codingexercise/`
   - Filter by "Flipzo Quiz Bank" topic
   - Verify questions show up
   
2. **Run tests:**
   ```bash
   python manage.py test coding.tests.test_seed_coding_quiz_bank -v 2
   ```

3. **Teacher review:**
   - Have a teacher review sample questions
   - Verify accuracy and appropriateness
   - Sign off before prod deployment

---

## Common Issues

| Issue | Fix |
|-------|-----|
| "CodingLanguage not found" | Create language rows before running |
| "0 questions created" | Check migrations applied |
| "Questions are duplicated" | Report; shouldn't happen (use slug dedup) |
| Need to add questions | Edit script, re-run (only new ones added) |
| Need to update question | Delete via admin, re-run seeder |

---

## Idempotency Guarantee

✓ **Safe to re-run multiple times**

1. **First run:** Creates all questions up to target
2. **Subsequent runs:** No-op (all targets met)
3. **After deletion:** Only top-ups the gap

No duplicates. No overwrites. Production-safe.

---

## Testing

### Full Test Suite

```bash
python manage.py test coding.tests.test_seed_coding_quiz_bank -v 2
```

### What's Tested

- ✓ Seeding logic (MCQ/TF/SA creation)
- ✓ Idempotency (no duplicates, top-up)
- ✓ Coverage targets (all pairs ≥ target counts)
- ✓ Flipzo integration (query compatibility)
- ✓ Structure validation (options, correct answers)

---

## Example: Add a Question

### 1. Edit Script

```python
# In scripts/seed_coding_quiz_bank.py, find PYTHON_ADVANCED_MCQ
PYTHON_ADVANCED_MCQ = [
    # ... existing questions ...
    {
        'title': 'python_adv_mcq_new_question',
        'question': 'What is a metaclass?',
        'correct': 'A class whose instances are classes',
        'wrong': ['A class method', 'A static method', 'A parent class'],
    },
]
```

### 2. Re-run Seeder

```bash
python ../scripts/seed_coding_quiz_bank.py
```

Only the new question is created. Existing questions unchanged.

---

## Flipzo Integration

Flipzo creates sessions by:

1. Selecting language & level (e.g., "Python — Intermediate")
2. Querying seeded questions by topic_level + type
3. Building session snapshots for playback

**Query Example:**

```python
from coding.models import CodingExercise, TopicLevel

tl = TopicLevel.objects.get(
    topic__language__slug='python',
    level_choice='beginner',
)

# Get MCQ questions
mcq_questions = CodingExercise.objects.filter(
    topic_level=tl,
    question_type='multiple_choice',
    is_active=True,
)[:10]
```

---

## Support

For issues or questions:

1. Read: `docs/SEED_CODING_QUIZ_BANK.md`
2. Check: `IMPLEMENTATION_SUMMARY.md`
3. Review: Tests in `coding/tests/test_seed_coding_quiz_bank.py`
4. File issue or contact development team

---

## Acceptance Criteria ✓

- [x] Seed script (idempotent, 275+ questions)
- [x] Master orchestration (run_all_prod_fixes.py updated)
- [x] Unit tests (seeding logic, structure validation)
- [x] Integration tests (Flipzo query compatibility)
- [x] Documentation (local, staging, prod, troubleshooting)
- [x] Coverage targets met (≥15 MCQ, ≥5 SA, ≥5 TF per pair)
- [x] Production-ready (atomic, safe, no destructive operations)

**Status: Ready for deployment** ✓
