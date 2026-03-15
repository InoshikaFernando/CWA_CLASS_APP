# CWA Classroom — Number Puzzles (Basic Facts)
# Specification Document

**Application:** CWA Classroom (CWA_CLASS_APP)
**Repository:** https://github.com/InoshikaFernando/CWA_CLASS_APP
**Version:** 1.0 (Draft)
**Date:** 2026-03-15

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals & Constraints](#2-goals--constraints)
3. [Feature Placement & Navigation](#3-feature-placement--navigation)
4. [Difficulty Levels](#4-difficulty-levels)
5. [Puzzle Definition & Generation](#5-puzzle-definition--generation)
6. [Answer Input & Validation](#6-answer-input--validation)
7. [Progression System](#7-progression-system)
8. [Student Experience (UI Flow)](#8-student-experience-ui-flow)
9. [Data Model (Django)](#9-data-model-django)
10. [URL Structure](#10-url-structure)
11. [Template Structure](#11-template-structure)
12. [Business Rules Summary](#12-business-rules-summary)
13. [Acceptance Criteria & Test Cases](#13-acceptance-criteria--test-cases)
14. [Future Extensibility](#14-future-extensibility)
15. [Open Items](#15-open-items)

---

## 1. Overview

### 1.1 Purpose

This specification defines **Number Puzzles**, a new activity mode within Basic Facts where students must determine missing operators and/or bracket placement in mathematical expressions. For example, given `1 _ 2 = 3`, the student types `1+2=3`.

Number Puzzles is:

- **Part of Basic Facts** — accessible from `/basic-facts/` alongside existing content
- **Difficulty-based** — 6 progressive levels, not tied to year levels or curriculum hierarchy
- **Open to all students** — any authenticated student can access it regardless of class enrollment or year level
- **Global scope** — puzzle definitions are shared across all schools; progress is tracked per student

### 1.2 Scope

- 6 difficulty levels progressing from single-operator discovery to nested bracket placement
- Pre-generated puzzle pool stored in the database
- Safe expression parsing and mathematical validation
- Student progress tracking with level unlock gating
- Integration with the existing Basic Facts navigation

### 1.3 Out of Scope

- Teacher-created custom puzzles (future)
- Leaderboards or competitive modes (future)
- Integration with ProgressCriteria from SPEC_TEACHER_CLASS_STUDENT_PROGRESS (this is self-contained progression)
- Multiplayer or timed competition modes
- Drag-and-drop or visual block-based input (v1 uses typed expressions only)

### 1.4 Terminology

| Term | Definition |
|------|-----------|
| **Puzzle** | A single mathematical expression challenge with missing operators and/or brackets |
| **Puzzle Set** | A group of 10 puzzles at a given difficulty level, presented as one session |
| **Expression** | The complete mathematical expression the student must reconstruct |
| **Target** | The result value shown to the student that the expression must equal |
| **Operand** | A number in the expression (given to the student, not hidden) |
| **Blank** | A position where the student must supply an operator (shown as `_`) |

---

## 2. Goals & Constraints

### 2.1 Goals

1. Reinforce understanding of arithmetic operators and their effects on numbers
2. Introduce operator precedence and order of operations (BEDMAS/BODMAS) through scaffolded levels
3. Develop mathematical reasoning — students think *about* operations rather than just computing
4. Provide immediate feedback on each attempt
5. Track student progress and gate advancement behind mastery thresholds
6. Generate sufficient variety so students do not encounter the same puzzle repeatedly

### 2.2 Constraints

- Must work within Django 4.2+ / Python 3.10 / MySQL 8.0
- Must integrate with existing Basic Facts navigation (`/basic-facts/`)
- Students type their answers (no drag-and-drop in v1)
- Expression evaluation must handle operator precedence correctly (standard BEDMAS)
- Puzzles must have deterministic, verifiable correct answers
- Supported operators: `+`, `-`, `x` (multiplication), `/` (division)
- **Display vs internal convention:** `x` is used for multiplication in student-facing display; `*` is used internally in `operators_allowed` and evaluation. The validation pipeline normalises `x`/`X` to `*` before evaluation.
- All puzzle results must be non-negative integers (no negatives, no fractions)

---

## 3. Feature Placement & Navigation

Number Puzzles lives within Basic Facts as a sibling activity to existing content.

### 3.1 Existing Route Context

From SPEC_PUBLIC_LANDING_AND_SUBJECT_HUB:

```
/basic-facts/           -- Basic Facts home (existing)
/times-tables/          -- Times Tables (existing)
```

### 3.2 New Routes

```
/basic-facts/number-puzzles/                    -- Level selection with progress
/basic-facts/number-puzzles/play/               -- Active puzzle session
/basic-facts/number-puzzles/check/              -- Answer validation (POST)
/basic-facts/number-puzzles/results/<session_id>/  -- Session results summary
```

### 3.3 Entry Point

The Basic Facts home page (`/basic-facts/`) gains a new card/link: **"Number Puzzles"** alongside existing content. The card shows a brief description: *"Figure out the missing pieces in maths expressions!"*

Students do NOT need class enrollment to access Number Puzzles — it is available to any authenticated user (students, individual students, and teachers for preview/testing).

---

## 4. Difficulty Levels

Six difficulty levels with increasing complexity. Each level introduces a new challenge type.

### 4.1 Level Summary

| Level | Name | Challenge | Operators | Numbers | Brackets | Student Sees | Student Types |
|-------|------|-----------|-----------|---------|----------|-------------|---------------|
| 1 | Beginner | Find 1 operator | `+`, `-` | 1–9 | None | `1 _ 2 = 3` | `1+2=3` |
| 2 | Explorer | Find 1 operator, bigger numbers | `+`, `-`, `x`, `/` | 1–99 | None | `12 _ 4 = 48` | `12x4=48` |
| 3 | Adventurer | Find 2 operators | `+`, `-`, `x`, `/` | 1–20 | None | `2 _ 3 _ 1 = 4` | `2+3-1=4` |
| 4 | Challenger | Brackets shown, find operators | `+`, `-`, `x`, `/` | 1–20 | Shown (fixed) | `(2 _ 3) _ 2 = 10` | `(2+3)x2=10` |
| 5 | Expert | Place brackets AND find operators | `+`, `-`, `x`, `/` | 1–15 | Must place | `3  3  4 = 21` | `3x(3+4)=21` |
| 6 | Master | Nested brackets + operators | `+`, `-`, `x`, `/` | 1–15 | Nested | `2  3  1  2 = 14` | `2x(3+(1+2))=14` |

### 4.2 Level-Specific Rules

**Level 1 — Beginner:**
- Two single-digit operands (1–9)
- Operators: `+` and `-` only
- Results must be non-negative integers (no negative results from subtraction)
- Maximum result: 18

**Level 2 — Explorer:**
- Two operands (1–99)
- All four operators: `+`, `-`, `x`, `/`
- Division only where result is a whole number (no remainders)
- Maximum result: 500

**Level 3 — Adventurer:**
- Three operands (1–20), two operators
- All four operators
- Expression evaluates with standard operator precedence (BEDMAS) — no brackets
- The two missing operators must yield a unique result (only one valid operator combination produces the target)
- Maximum result: 100

**Level 4 — Challenger:**
- Three operands (1–20), two operators
- Bracket positions are shown in the display (e.g., `(a _ b) _ c` or `a _ (b _ c)`)
- Student must figure out the operators and reproduce the full expression including brackets
- The bracketed expression must produce a different result than the same expression without brackets (brackets must matter)
- Maximum result: 200

**Level 5 — Expert:**
- Three operands (1–15)
- Student sees only the numbers and target: `3  3  4 = 21`
- Student must construct the full expression with operators AND brackets: `3x(3+4)=21`
- Brackets must be necessary — the expression without brackets (using the same operators) must NOT equal the target
- Multiple valid expressions may exist; any correct one is accepted
- Maximum result: 200

**Level 6 — Master:**
- Four operands (1–15)
- Student sees only the numbers and target: `2  3  1  2 = 14`
- Student must construct the full expression with operators and potentially nested brackets: `2x(3+(1+2))=14`
- Nested brackets must be necessary — a single level of brackets (or no brackets) with the same operators must NOT equal the target
- Multiple valid expressions may exist; any correct one is accepted
- Maximum result: 300

---

## 5. Puzzle Definition & Generation

### 5.1 Strategy: Pre-Generated and Stored

Puzzles are **pre-generated** by a management command and stored in the database. This approach:

- Guarantees validity (all puzzles are verified at generation time)
- Avoids runtime computational expense, especially for levels 5–6
- Enables tracking of which puzzles a student has already seen
- Allows easy seeding via fixtures or management commands

### 5.2 Generation Algorithms

**Levels 1–2 (single operator):**
```
1. Pick two operands within the level's number range
2. Pick a valid operator from the level's operator set
3. Compute the result
4. Validate constraints:
   - Result is a non-negative integer
   - For division: operand_1 % operand_2 == 0
   - Result within the level's maximum
5. Store puzzle with display template "a _ b = result"
```

**Level 3 (two operators):**
```
1. Pick three operands within range (1–20)
2. Pick two operators
3. Evaluate with standard precedence: a op1 b op2 c
4. Validate:
   - Result is a non-negative integer, result <= 100
   - Only one operator combination produces this result with these operands
5. Store puzzle with display template "a _ b _ c = result"
```

**Level 4 (brackets shown, operators hidden):**
```
1. Pick three operands within range (1–20)
2. Pick bracket placement: (a _ b) _ c  OR  a _ (b _ c)
3. Pick two operators
4. Evaluate expression with brackets
5. Validate:
   - Result is a non-negative integer, result <= 200
   - Bracketed result differs from un-bracketed result (brackets must matter)
6. Store puzzle with display template showing bracket positions
```

**Level 5 (place brackets + operators, 3 numbers):**
```
1. Pick three operands (1–15)
2. For each bracket arrangement (none, (a_b)_c, a_(b_c)):
     For each operator combination:
       Evaluate expression
       If result is a positive integer:
         Check if brackets are necessary
         (un-bracketed expression with same operators != target)
         If so: record as valid puzzle
3. Store puzzle with display showing only numbers and target
4. Store one canonical solution for display on incorrect answers
```

**Level 6 (nested brackets + operators, 4 numbers):**
```
1. Pick four operands (1–15)
2. Enumerate bracket arrangements including nested:
   - ((a_b)_c)_d, (a_(b_c))_d, (a_b_c)_d
   - a_((b_c)_d), a_(b_(c_d)), a_(b_c_d)
   - (a_b)_(c_d)
3. For each arrangement + operator combination:
     Evaluate, check for positive integer result <= 300
     Ensure nested brackets are required
4. Store puzzle with display showing only numbers and target
5. Store one canonical solution
```

### 5.3 Management Command: `generate_puzzles`

**Location:** `number_puzzles/management/commands/generate_puzzles.py`

**Usage:**

```
python manage.py generate_puzzles --level 1 --count 500
python manage.py generate_puzzles --level 2 --count 500
python manage.py generate_puzzles --all --count 500
python manage.py generate_puzzles --all --count 500 --clear
```

**Arguments:**

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `--level` | int | No* | — | Level number (1–6) to generate puzzles for |
| `--all` | flag | No* | — | Generate puzzles for all 6 levels |
| `--count` | int | No | 500 | Target number of puzzles to generate per level |
| `--clear` | flag | No | — | Delete existing puzzles for the target level(s) before generating. Only deletes puzzles not referenced by any `PuzzleAttempt` |
| `--dry-run` | flag | No | — | Show how many puzzles would be generated without writing to the database |
| `--verbosity` | int | No | 1 | 0 = silent, 1 = summary, 2 = per-puzzle output |

\* One of `--level` or `--all` is required.

**Behaviour:**

1. Validates that `NumberPuzzleLevel` fixtures are loaded (exits with error if not)
2. For each target level:
   a. Counts existing puzzles in the database for that level
   b. If existing count >= `--count` and `--clear` is not set, skips with a message
   c. If `--clear` is set, deletes puzzles not referenced by any `PuzzleAttempt` or `SessionPuzzle`
   d. Generates puzzles using the level-specific algorithm (see §5.2)
   e. Validates each puzzle against level constraints before saving
   f. Skips duplicates (matching `level` + `operands_hash` + `target`)
   g. Uses `bulk_create` with `ignore_conflicts=True` for performance
3. Prints summary: puzzles generated, duplicates skipped, total now in DB per level

**Output example (verbosity=1):**

```
Level 1 (Beginner): 500 generated, 12 duplicates skipped, 500 total in DB
Level 2 (Explorer): 500 generated, 8 duplicates skipped, 500 total in DB
Level 3 (Adventurer): 500 generated, 23 duplicates skipped, 500 total in DB
Level 4 (Challenger): 500 generated, 31 duplicates skipped, 500 total in DB
Level 5 (Expert): 347 generated, 0 duplicates skipped, 347 total in DB
Level 6 (Master): 198 generated, 0 duplicates skipped, 198 total in DB
Done. Total puzzles in database: 2845
```

**Error handling:**

| Scenario | Behaviour |
|----------|-----------|
| `NumberPuzzleLevel` fixtures not loaded | Exit with error: "No puzzle levels found. Run: python manage.py loaddata puzzle_levels" |
| Invalid `--level` value (not 1–6) | Exit with error: "Invalid level: {n}. Must be 1–6" |
| Neither `--level` nor `--all` provided | Exit with error showing usage |
| Generation cannot reach `--count` (levels 5–6) | Warn and stop: "Level {n}: only {x} valid puzzles possible, generated {x}" |
| Database error during bulk_create | Roll back, print error, continue to next level |

**Notes:**

- Levels 5–6 have stricter mathematical constraints (brackets must be necessary, nested brackets must be required), so the pool may be smaller than `--count`. The command exhaustively enumerates valid combinations and stops when all possibilities are explored.
- The command is idempotent — running it again with the same arguments will skip already-existing puzzles.
- Recommended to run once during initial deployment and periodically if the pool needs topping up.

### 5.4 Puzzle Uniqueness

Within each level, the combination of (`level`, `operands`, `target`) must be unique. Since MySQL 8.0 does not support unique constraints on JSON columns, an `operands_hash` field (MD5 of the JSON-serialised operands) is used with `unique_together = ('level', 'operands_hash', 'target')`.

---

## 6. Answer Input & Validation

### 6.1 Input Format

At all levels, the student types the complete expression. Accepted operator symbols:

| Operator | Accepted Inputs |
|----------|----------------|
| Addition | `+` |
| Subtraction | `-` |
| Multiplication | `x`, `X`, `*` |
| Division | `/` |
| Brackets | `(`, `)` |
| Equals | `=` (optional — student may include or omit the `= target` portion) |

The input field shows a placeholder guiding the student. For Level 1: *"Type your answer, e.g. 1+2=3"*

### 6.2 Validation Pipeline

```
Step 1 — Sanitise input:
  - Strip whitespace
  - Normalise operators: x/X -> *, remove spaces
  - If input contains "=", take only the left side (before "=")

Step 2 — Parse expression:
  - Tokenise into numbers, operators, brackets
  - Verify well-formed: balanced brackets, operators between operands, no consecutive operators

Step 3 — Number validation (Levels 1–4):
  - Extract numbers from the expression in order
  - Verify they match the puzzle's operands in the exact same left-to-right order

Step 4 — Number validation (Levels 5–6):
  - Extract numbers from the expression in order
  - Verify they match the puzzle's operand set in the exact same left-to-right order

Step 5 — Evaluate expression:
  - Use a safe math parser (NO eval() / exec())
  - Respect operator precedence (BEDMAS)
  - Check: result == puzzle target

Step 6 — Return result:
  - Correct: expression evaluates to target with valid numbers in correct order
  - Incorrect: expression does not evaluate to target, or invalid structure
  - Invalid: malformed expression (unbalanced brackets, non-numeric content, etc.)
```

### 6.3 Safe Expression Evaluator

The evaluator lives in `number_puzzles/expression_evaluator.py` and must use a safe tokeniser/parser — **never** Python's `eval()` or `exec()`.

Recommended approach: recursive-descent parser or Python's `ast` module with a strict whitelist.

Components:
- `tokenise(expression: str) -> list[Token]` — breaks string into number/operator/bracket tokens
- `parse(tokens: list[Token]) -> ASTNode` — builds an AST respecting BEDMAS
- `evaluate(node: ASTNode) -> Decimal` — evaluates the AST
- `validate_expression(expression: str, expected_operands: list[int], target: int) -> ValidationResult` — full pipeline

Only the following tokens are allowed: integers, `+`, `-`, `*`, `/`, `(`, `)`. Anything else (letters, function calls, variable names) is rejected.

### 6.4 Division Handling

- Integer division only for all levels — puzzles are generated to ensure clean division
- Division by zero in student input returns "Invalid expression" error, not a system error

---

## 7. Progression System

### 7.1 Unlock Thresholds

| From Level | To Level | Requirement |
|-----------|---------|-------------|
| (start) | 1 | Unlocked by default for all students |
| 1 | 2 | Complete a puzzle set with >= 8/10 correct |
| 2 | 3 | Complete a puzzle set with >= 8/10 correct |
| 3 | 4 | Complete a puzzle set with >= 8/10 correct |
| 4 | 5 | Complete a puzzle set with >= 8/10 correct |
| 5 | 6 | Complete a puzzle set with >= 8/10 correct |

- A student can replay any unlocked level at any time
- Only the best score per level is used for star rating display
- Unlocking is permanent — a later low score does not re-lock a level
- A student must complete the full puzzle set (10 questions) for the score to count

### 7.2 Puzzle Set Structure

- Each session is a set of **10 puzzles** from the student's selected level
- Puzzles are selected randomly from the pool, avoiding puzzles the student has already answered correctly in the current level (to ensure variety)
- If the student has exhausted the pool, puzzles are recycled from the full pool
- Each puzzle is presented one at a time
- Immediate feedback after each answer (correct/incorrect, with correct answer shown if wrong)
- At the end of the set: summary screen with score, time, and unlock status

### 7.3 Star Rating

Each level shows a star rating based on best performance:

| Score | Stars | Badge |
|-------|-------|-------|
| 10/10 | 3 stars (gold) | "Perfect!" |
| 8–9/10 | 2 stars (silver) | "Great work!" |
| 5–7/10 | 1 star (bronze) | "Keep practising!" |
| 0–4/10 | 0 stars | "Try again!" |

Stars are cosmetic and displayed on the level selection screen. The unlock threshold is 8/10 (2 stars minimum).

### 7.4 Speed Tracking

- Each puzzle attempt records `time_taken_seconds` (time from puzzle display to answer submission)
- Puzzle session records total `duration_seconds`
- Speed is displayed on the results screen but does NOT affect progression
- Future: speed-based challenges could use this data

---

## 8. Student Experience (UI Flow)

### 8.1 Entry Point

```
Basic Facts Home (/basic-facts/)
  |
  +-- [Number Puzzles Card]  -->  /basic-facts/number-puzzles/
```

The Basic Facts home page shows a card for Number Puzzles alongside existing content. The card shows a puzzle icon and brief description.

### 8.2 Level Selection (`/basic-facts/number-puzzles/`)

```
+---------------------------------------------------------------+
|  Number Puzzles                                                |
|                                                                |
|  Figure out the missing pieces in maths expressions!           |
|                                                                |
|  +----------+  +----------+  +----------+                     |
|  | Level 1  |  | Level 2  |  | Level 3  |                     |
|  | Beginner |  | Explorer |  |Adventurer|                     |
|  |          |  |          |  |          |                     |
|  | ***      |  | **       |  | [locked] |                     |
|  | Best:    |  | Best:    |  |          |                     |
|  | 10/10    |  | 8/10     |  | Score 8+ |                     |
|  |          |  |          |  | to unlock|                     |
|  | [Play]   |  | [Play]   |  |          |                     |
|  +----------+  +----------+  +----------+                     |
|                                                                |
|  +----------+  +----------+  +----------+                     |
|  | Level 4  |  | Level 5  |  | Level 6  |                     |
|  |Challenger|  | Expert   |  | Master   |                     |
|  | [locked] |  | [locked] |  | [locked] |                     |
|  +----------+  +----------+  +----------+                     |
|                                                                |
+---------------------------------------------------------------+
```

- **Unlocked levels:** Show star rating, best score, and a "Play" button
- **Locked levels:** Greyed out, show "Score 8+ to unlock" text, no "Play" button
- Level card style follows the existing CWA_CLASS_APP card design

### 8.3 Active Puzzle (`/basic-facts/number-puzzles/play/?level=1`)

**Levels 1–4 (blanks shown):**

```
+---------------------------------------------------------------+
|  Level 1 - Beginner                     Question 3 of 10      |
|                                                                |
|                                                                |
|                     5 _ 3 = 8                                  |
|                                                                |
|                                                                |
|  Your answer:                                                  |
|  +---------------------------------------+                     |
|  | 5+3=8                                 |                     |
|  +---------------------------------------+                     |
|                                                                |
|  [Check Answer]                                                |
|                                                                |
+---------------------------------------------------------------+
```

**Levels 5–6 (numbers and target only):**

```
+---------------------------------------------------------------+
|  Level 5 - Expert                       Question 7 of 10      |
|                                                                |
|                                                                |
|                   3   3   4  =  21                             |
|                                                                |
|  Build an expression using these numbers to make 21            |
|                                                                |
|  Your answer:                                                  |
|  +---------------------------------------+                     |
|  | 3x(3+4)                               |                     |
|  +---------------------------------------+                     |
|                                                                |
|  [Check Answer]                                                |
|                                                                |
+---------------------------------------------------------------+
```

- Large, clear display of the puzzle expression
- Text input field for the student's answer
- "Check Answer" button (primary style)
- Progress indicator: "Question X of 10"

### 8.4 Feedback (Inline)

**Correct:**
```
+---------------------------------------------------------------+
|  Level 1 - Beginner                     Question 3 of 10      |
|                                                                |
|                     5 _ 3 = 8                                  |
|                                                                |
|  +----------------------------------------------------+       |
|  |  Correct!   5 + 3 = 8                              |       |
|  +----------------------------------------------------+       |
|                                                                |
|  [Next Question -->]                                           |
|                                                                |
+---------------------------------------------------------------+
```

**Incorrect:**
```
+---------------------------------------------------------------+
|  Level 1 - Beginner                     Question 3 of 10      |
|                                                                |
|                     5 _ 3 = 8                                  |
|                                                                |
|  +----------------------------------------------------+       |
|  |  Not quite. The answer is:  5 + 3 = 8              |       |
|  +----------------------------------------------------+       |
|                                                                |
|  [Next Question -->]                                           |
|                                                                |
+---------------------------------------------------------------+
```

- Feedback is immediate after submission (no page reload — use HTMX or standard form POST with redirect)
- Correct answer is always shown on incorrect attempts
- "Next Question" advances to the next puzzle; on the last question, reads "See Results"

### 8.5 Results Screen (`/basic-facts/number-puzzles/results/<session_id>/`)

```
+---------------------------------------------------------------+
|  Puzzle Set Complete!                                          |
|                                                                |
|  Level 1 - Beginner                                           |
|                                                                |
|  Score: 9 / 10                                                 |
|  Time:  2m 34s                                                 |
|  Stars: ** (silver)                                            |
|                                                                |
|  +----------------------------------------------------+       |
|  |  Level 2 Unlocked!                                  |       |
|  +----------------------------------------------------+       |
|                                                                |
|  [Play Again]    [Try Level 2]    [Back to Levels]             |
|                                                                |
+---------------------------------------------------------------+
```

- Shows score, time taken, star rating
- If threshold met and next level was not yet unlocked: shows unlock notification
- Navigation: replay same level, try newly unlocked level, or return to level selection

---

## 9. Data Model (Django)

### 9.1 App Structure

All Number Puzzles models live in a **new Django app: `number_puzzles`**. This follows the principle of feature isolation — Number Puzzles has its own models, views, templates, and management commands, and does not share models with the core domain.

App location: `number_puzzles/` (top-level Django app)

### 9.2 NumberPuzzleLevel (Global, Seeded)

Defines the 6 difficulty levels. Seeded via fixture — not user-editable.

```python
class NumberPuzzleLevel(models.Model):
    """A difficulty level for number puzzles. Seeded data, not user-editable."""

    number = models.PositiveIntegerField(unique=True)
    # 1-6, the level number
    name = models.CharField(max_length=50)
    # "Beginner", "Explorer", "Adventurer", "Challenger", "Expert", "Master"
    slug = models.SlugField(max_length=50, unique=True)
    description = models.TextField(blank=True)
    operators_allowed = models.CharField(max_length=20)
    # Comma-separated: "+,-" or "+,-,*,/"
    min_operand = models.PositiveIntegerField(default=1)
    max_operand = models.PositiveIntegerField(default=9)
    num_operands = models.PositiveIntegerField(default=2)
    # 2 for levels 1-2, 3 for levels 3-5, 4 for level 6
    brackets_shown = models.BooleanField(default=False)
    # True only for level 4
    brackets_required = models.BooleanField(default=False)
    # True for levels 5-6
    nested_brackets = models.BooleanField(default=False)
    # True only for level 6
    puzzles_per_set = models.PositiveIntegerField(default=10)
    unlock_threshold = models.PositiveIntegerField(default=8)
    # Score needed to unlock the next level
    max_result = models.PositiveIntegerField(default=100)
    # Maximum allowed result for puzzles at this level (used by generation command)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['number']

    def __str__(self):
        return f"Level {self.number}: {self.name}"
```

### 9.3 NumberPuzzle (Global, Pre-Generated)

Pre-generated puzzle definitions. Global scope — shared across all schools and students.

```python
class NumberPuzzle(models.Model):
    """A pre-generated number puzzle. Global scope."""

    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='puzzles'
    )
    operands = models.JSONField()
    # List of integers, e.g. [5, 3] or [2, 3, 1, 2]
    operands_hash = models.CharField(max_length=32, editable=False)
    # MD5 hash of JSON-serialised operands, set in save()
    target = models.IntegerField()
    # The result the expression must equal
    display_template = models.CharField(max_length=200)
    # What the student sees, e.g. "5 _ 3 = 8" or "3  3  4 = 21"
    solution = models.CharField(max_length=200)
    # One canonical correct expression, e.g. "5+3" or "3*(3+4)"
    # Used for display on incorrect answers
    has_multiple_solutions = models.BooleanField(default=False)
    # True for levels 5-6 where multiple bracket/operator combinations may work
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('level', 'operands_hash', 'target')
        ordering = ['level', 'id']

    def __str__(self):
        return f"L{self.level.number}: {self.display_template}"

    def save(self, *args, **kwargs):
        import hashlib
        import json
        self.operands_hash = hashlib.md5(
            json.dumps(self.operands, sort_keys=False).encode()
        ).hexdigest()
        super().save(*args, **kwargs)
```

### 9.4 PuzzleSession (Per-Student)

Tracks a student's attempt at a puzzle set (10 puzzles).

```python
import uuid


class PuzzleSession(models.Model):
    """A student's attempt at a set of puzzles at a given level."""

    STATUS_CHOICES = [
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('abandoned', 'Abandoned'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    student = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='puzzle_sessions'
    )
    # No limit_choices_to — teachers can also play for preview/testing (NP-21)
    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='sessions'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='in_progress')
    score = models.PositiveIntegerField(default=0)
    # Count of correct answers
    total_questions = models.PositiveIntegerField(default=10)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    # Total time from first puzzle displayed to last answer submitted
    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.student} - Level {self.level.number} ({self.score}/{self.total_questions})"
```

### 9.5 PuzzleAttempt (Per-Student, Per-Puzzle)

Records each individual puzzle attempt within a session.

```python
class PuzzleAttempt(models.Model):
    """A student's answer to a single puzzle within a session."""

    session = models.ForeignKey(
        PuzzleSession,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    puzzle = models.ForeignKey(
        NumberPuzzle,
        on_delete=models.CASCADE,
        related_name='attempts'
    )
    question_number = models.PositiveIntegerField()
    # 1-10, the order in which this puzzle was presented
    student_answer = models.CharField(max_length=200, blank=True)
    # The raw expression typed by the student
    is_correct = models.BooleanField(default=False)
    time_taken_seconds = models.PositiveIntegerField(null=True, blank=True)
    # Time from puzzle display to answer submission
    answered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('session', 'question_number')
        ordering = ['question_number']

    def __str__(self):
        return f"Q{self.question_number}: {'correct' if self.is_correct else 'incorrect'}"
```

### 9.6 SessionPuzzle (Per-Session)

Stores the pre-selected set of puzzles for a session. Created when the session starts, ensuring the same puzzles are shown even if the student resumes later.

```python
class SessionPuzzle(models.Model):
    """A puzzle assigned to a session. Created at session start."""

    session = models.ForeignKey(
        PuzzleSession,
        on_delete=models.CASCADE,
        related_name='session_puzzles'
    )
    puzzle = models.ForeignKey(
        NumberPuzzle,
        on_delete=models.CASCADE,
        related_name='session_assignments'
    )
    question_number = models.PositiveIntegerField()
    # 1-10, the order in which this puzzle will be presented

    class Meta:
        unique_together = ('session', 'question_number')
        ordering = ['question_number']

    def __str__(self):
        return f"Session {self.session_id} Q{self.question_number}"
```

### 9.7 StudentPuzzleProgress (Per-Student)

Aggregated progress tracking per student per level. Updated after each completed session.

```python
class StudentPuzzleProgress(models.Model):
    """Tracks a student's overall progress for each puzzle level."""

    student = models.ForeignKey(
        'accounts.CustomUser',
        on_delete=models.CASCADE,
        related_name='puzzle_progress'
    )
    level = models.ForeignKey(
        NumberPuzzleLevel,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_unlocked = models.BooleanField(default=False)
    best_score = models.PositiveIntegerField(default=0)
    # Best score out of total_questions across all completed sessions
    best_time_seconds = models.PositiveIntegerField(null=True, blank=True)
    # Fastest completion time for a full set
    total_sessions = models.PositiveIntegerField(default=0)
    total_puzzles_attempted = models.PositiveIntegerField(default=0)
    total_puzzles_correct = models.PositiveIntegerField(default=0)
    last_played_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('student', 'level')
        ordering = ['level__number']

    def __str__(self):
        return f"{self.student} - Level {self.level.number}: {self.best_score}"

    @property
    def stars(self):
        """Calculate star rating from best score (assuming 10-question sets)."""
        if self.best_score >= 10:
            return 3
        elif self.best_score >= 8:
            return 2
        elif self.best_score >= 5:
            return 1
        return 0

    @property
    def accuracy(self):
        """Overall accuracy percentage."""
        if self.total_puzzles_attempted == 0:
            return 0
        return round((self.total_puzzles_correct / self.total_puzzles_attempted) * 100)
```

### 9.8 Unlock Workflow

When a student completes a puzzle session:

1. Mark the `PuzzleSession` as `completed`, set `completed_at` and `duration_seconds`
2. Get or create `StudentPuzzleProgress` for this student + level
3. Update progress: increment `total_sessions`, `total_puzzles_attempted`, `total_puzzles_correct`
4. If `session.score > progress.best_score`: update `best_score` and `best_time_seconds`
5. **Check unlock:** If `session.score >= level.unlock_threshold` AND a next level exists:
   - Get or create `StudentPuzzleProgress` for this student + next level
   - Set `is_unlocked = True` on the next level's progress record

Level 1's `StudentPuzzleProgress` is created with `is_unlocked = True` on first access (lazily when the level list view renders).

### 9.9 Initial Data Fixture

`number_puzzles/fixtures/puzzle_levels.json` — seeds the 6 difficulty levels:

| number | name | slug | operators_allowed | num_operands | min_operand | max_operand | max_result | brackets_shown | brackets_required | nested_brackets | unlock_threshold |
|--------|------|------|-------------------|-------------|-------------|-------------|------------|----------------|-------------------|-----------------|-----------------|
| 1 | Beginner | beginner | +,- | 2 | 1 | 9 | 18 | False | False | False | 8 |
| 2 | Explorer | explorer | +,-,*,/ | 2 | 1 | 99 | 500 | False | False | False | 8 |
| 3 | Adventurer | adventurer | +,-,*,/ | 3 | 1 | 20 | 100 | False | False | False | 8 |
| 4 | Challenger | challenger | +,-,*,/ | 3 | 1 | 20 | 200 | True | False | False | 8 |
| 5 | Expert | expert | +,-,*,/ | 3 | 1 | 15 | 200 | False | True | False | 8 |
| 6 | Master | master | +,-,*,/ | 4 | 1 | 15 | 300 | False | True | True | 8 |

### 9.10 ER Diagram

```
NumberPuzzleLevel (global, seeded)
  |
  +-- 1:many --> NumberPuzzle (global, pre-generated)
  |                  |
  |                  +-- 1:many --> SessionPuzzle (per-session, puzzle queue)
  |                  |                  |
  |                  +-- 1:many --> PuzzleAttempt (per-student, answers)
  |                                    |
  +-- 1:many --> PuzzleSession ---------+   (per-student)
  |                  |
  |                  +-- FK --> accounts.CustomUser
  |
  +-- 1:many --> StudentPuzzleProgress (per-student)
                     |
                     +-- FK --> accounts.CustomUser
```

---

## 10. URL Structure

### 10.1 URL Configuration

```python
# number_puzzles/urls.py
from django.urls import path
from . import views

app_name = 'number_puzzles'

urlpatterns = [
    path('', views.PuzzleLevelListView.as_view(), name='level_list'),
    path('play/', views.PuzzlePlayView.as_view(), name='play'),
    path('check/', views.PuzzleCheckAnswerView.as_view(), name='check_answer'),
    path('results/<uuid:session_id>/', views.PuzzleResultsView.as_view(), name='results'),
]
```

```python
# cwa_classroom/urls.py (addition to existing)
urlpatterns = [
    # ... existing routes ...
    path('basic-facts/number-puzzles/', include('number_puzzles.urls')),
]
```

### 10.2 Route Summary

| URL | View | Method | Auth | Purpose |
|-----|------|--------|------|---------|
| `/basic-facts/number-puzzles/` | `PuzzleLevelListView` | GET | `@login_required` | Level selection with progress |
| `/basic-facts/number-puzzles/play/` | `PuzzlePlayView` | GET | `@login_required` | Start/continue a puzzle session |
| `/basic-facts/number-puzzles/check/` | `PuzzleCheckAnswerView` | POST | `@login_required` | Submit and validate an answer |
| `/basic-facts/number-puzzles/results/<session_id>/` | `PuzzleResultsView` | GET | `@login_required` | Session results summary |

### 10.3 Query Parameters

| View | Parameter | Type | Required | Purpose |
|------|----------|------|----------|---------|
| `PuzzlePlayView` | `level` | int | Yes | Which difficulty level to play |
| `PuzzlePlayView` | `session` | UUID | No | Resume an in-progress session |

---

## 11. Template Structure

```
templates/
  number_puzzles/
    level_list.html             -- Level selection grid with progress
    play.html                   -- Active puzzle display and answer input
    results.html                -- Session results summary
    partials/
      level_card.html           -- Reusable level card (unlocked/locked states)
      puzzle_display.html       -- Puzzle expression renderer
      feedback.html             -- Inline feedback (correct/incorrect)
      star_rating.html          -- Star display partial (0-3 stars)
```

All templates extend `base.html` (the existing authenticated app layout with sidebar + topbar).

---

## 12. Business Rules Summary

### 12.1 Puzzle Rules (Global)

| # | Rule |
|---|------|
| NP-1 | Puzzle definitions are global — shared across all schools and students |
| NP-2 | Puzzles are pre-generated and stored in the database (not computed at runtime) |
| NP-3 | Each puzzle has exactly one display template and at least one valid solution |
| NP-4 | For levels 1–4, there is exactly one correct operator combination |
| NP-5 | For levels 5–6, multiple valid expressions may exist; any that equals the target using the given numbers in order is accepted |
| NP-6 | All puzzle results must be non-negative integers |
| NP-7 | Division puzzles must have exact (no remainder) solutions |
| NP-8 | Numbers in the student's answer must appear in the same left-to-right order as the puzzle's operands |

### 12.2 Progression Rules

| # | Rule |
|---|------|
| NP-9 | Level 1 is unlocked by default for all students |
| NP-10 | Levels 2–6 require a score of >= 8/10 on the previous level to unlock |
| NP-11 | A student can replay any unlocked level at any time |
| NP-12 | Only the best score per level counts toward star rating display |
| NP-13 | Unlocking is permanent — a later low score does not re-lock a level |
| NP-14 | A student must complete the full puzzle set (10 questions) for the score to count |
| NP-15 | Abandoned sessions (browser close, navigation away) do not count toward best score |

### 12.3 Session Rules

| # | Rule |
|---|------|
| NP-16 | Each puzzle set contains exactly 10 puzzles (configurable per level via `puzzles_per_set`) |
| NP-17 | Puzzles within a set are randomly selected from the level's pool, avoiding recently seen puzzles where possible |
| NP-18 | A student can have at most one `in_progress` session at a time per level |
| NP-19 | Starting a new session while one is `in_progress` marks the old session as `abandoned` |
| NP-20 | Feedback is immediate after each answer submission |

### 12.4 Access Rules

| # | Rule |
|---|------|
| NP-21 | Any authenticated user with role `student`, `individual_student`, or any teacher role can access Number Puzzles |
| NP-22 | Number Puzzles does not require class enrollment — it is open to all authenticated users |
| NP-23 | Number Puzzles does not check package limits — it is free content |
| NP-24 | Progress is tracked per user account, not per school or per class |

### 12.5 Validation Rules

| # | Rule |
|---|------|
| NP-25 | Student expressions are validated using a safe parser (no `eval()`) |
| NP-26 | Accepted operators: `+`, `-`, `*`/`x`/`X`, `/` |
| NP-27 | Operator symbols are normalised before evaluation (`x` and `X` become `*`) |
| NP-28 | Brackets must be balanced in student input |
| NP-29 | Student input containing anything other than digits, operators, brackets, spaces, and `=` is rejected as invalid |
| NP-30 | Division by zero in student input returns "Invalid expression", not a system error |

---

## 13. Acceptance Criteria & Test Cases

### 13.1 Level Selection

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-1 | Student visits `/basic-facts/number-puzzles/` | Level selection page renders with 6 level cards |
| AC-2 | Level 1 is unlocked for a new student | Level 1 card shows "Play" button, no lock icon |
| AC-3 | Levels 2–6 are locked for a new student | Levels 2–6 show lock icon, greyed out, "Score 8+ to unlock" |
| AC-4 | Student with best score 9/10 on Level 1 | Level 1 shows 2 silver stars; Level 2 is unlocked |
| AC-5 | Student with best score 10/10 on Level 1 | Level 1 shows 3 gold stars; Level 2 is unlocked |
| AC-6 | Student with best score 6/10 on Level 1 | Level 1 shows 1 bronze star; Level 2 remains locked |

### 13.2 Playing Puzzles

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-7 | Student clicks "Play" on Level 1 | New puzzle session created, first puzzle displayed |
| AC-8 | Puzzle displays `5 _ 3 = 8`, student types `5+3=8` | Answer marked correct, correct feedback shown |
| AC-9 | Puzzle displays `5 _ 3 = 8`, student types `5-3=8` | Answer marked incorrect, correct answer `5+3=8` shown |
| AC-10 | Student types `5+3` (without `=8`) | Answer accepted and evaluated (equals portion is optional) |
| AC-11 | Student types `5 + 3 = 8` (with spaces) | Spaces stripped, answer accepted and evaluated |
| AC-12 | Student types `5x3=8` (valid expression, wrong answer) | Answer marked incorrect (15 != 8) |
| AC-13 | Student types `abc` (invalid input) | Error message: "Please enter a valid expression" |
| AC-14 | Level 4: `(2 _ 3) _ 2 = 10`, student types `(2+3)*2=10` | Correct (`*` accepted as multiplication) |
| AC-15 | Level 5: `3  3  4 = 21`, student types `3*(3+4)=21` | Correct |
| AC-16 | Level 5: student types `(3*3)+4=13` (valid but wrong target) | Incorrect (13 != 21) |
| AC-17 | Level 5: student types `3*(3+4)` (no `=21`) | Correct (equals portion optional, evaluates to 21) |
| AC-18 | Level 1: puzzle `7 _ 3 = 4`, student types `3-7=4` (wrong operand order) | Incorrect: numbers must appear in same left-to-right order as the puzzle |

### 13.3 Session Completion

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-19 | Student completes all 10 puzzles | Session status = `completed`, results page shown |
| AC-20 | Student scores 8/10 on Level 1 (first time) | Level 2 unlocked, unlock notification on results page |
| AC-21 | Student scores 7/10 on Level 1 | Level 2 remains locked, encouragement message shown |
| AC-22 | Results page displays score, time, stars | All three metrics displayed correctly |
| AC-23 | Student navigates away during session | Session remains `in_progress`; starting new session marks old as `abandoned` |
| AC-24 | Student has `in_progress` session, starts a new session at same level | Old session marked `abandoned`, new session created |
| AC-25 | Abandoned session with score 9/10 | Best score NOT updated (only completed sessions count) |

### 13.4 Progress Persistence

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-26 | Student logs out and back in | Progress preserved — unlocked levels still unlocked, stars unchanged |
| AC-27 | Student replays Level 1 with lower score (5/10) after previous 9/10 | Best score remains 9/10, stars unchanged |
| AC-28 | Student replays Level 1 with higher score (10/10) after previous 9/10 | Best score updated to 10/10, stars updated to 3 gold |
| AC-29 | Student completes Level 1 with 8/10, then Level 2 with 8/10 | Both levels show 2 stars, Level 3 unlocked |

### 13.5 Expression Validation

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-30 | Input `5+3` | Valid, evaluates to 8 |
| AC-31 | Input `(2+3)*2` | Valid, evaluates to 10 |
| AC-32 | Input `2+3)*2` | Invalid: unbalanced brackets |
| AC-33 | Input `10/0` | Invalid: division by zero, friendly error message |
| AC-34 | Input `5++3` | Invalid: consecutive operators |
| AC-35 | Input `import os` | Invalid: rejected by parser (non-numeric, non-operator content) |
| AC-36 | Input `3x4` | Valid: `x` normalised to `*`, evaluates to 12 |
| AC-37 | Input `3X4` | Valid: `X` normalised to `*`, evaluates to 12 |
| AC-38 | Input `3*4` | Valid, evaluates to 12 |
| AC-39 | Input `7/2` (non-integer result) | Evaluates to 3.5 — marked incorrect if target is integer (puzzle generation ensures clean division, but student may attempt it) |

### 13.6 Data Model

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-40 | `NumberPuzzleLevel` fixture loads successfully | All 6 levels present in database with correct `max_result` values |
| AC-41 | Duplicate puzzle (same level, operands, target) | Rejected by unique constraint |
| AC-42 | `PuzzleSession` uses UUID primary key | Session accessible by UUID in URL |
| AC-43 | `StudentPuzzleProgress.stars` with best_score=10 | Returns 3 |
| AC-44 | `StudentPuzzleProgress.stars` with best_score=8 | Returns 2 |
| AC-45 | `StudentPuzzleProgress.stars` with best_score=4 | Returns 0 |
| AC-46 | `NumberPuzzle.save()` auto-sets `operands_hash` | Hash computed from operands JSON |
| AC-47 | `SessionPuzzle` records created at session start | 10 `SessionPuzzle` records created when session begins |
| AC-48 | Resuming an in-progress session | Same puzzles shown (from `SessionPuzzle` records), not re-randomised |

### 13.7 Access Control

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-49 | Unauthenticated user visits `/basic-facts/number-puzzles/` | Redirected to login |
| AC-50 | Student without class enrollment accesses Number Puzzles | Access granted (NP-22) |
| AC-51 | Student on Basic package (1 class limit) accesses Number Puzzles | Access granted — package limits not enforced (NP-23) |
| AC-52 | Teacher accesses Number Puzzles | Access granted (can preview/test) |
| AC-53 | Student tries to play a locked level | Redirected to level selection with error message |

### 13.8 Puzzle Generation

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-54 | Generated Level 1 puzzle has result <= 18 | All Level 1 puzzles have non-negative integer results <= `max_result` |
| AC-55 | Generated Level 2 division puzzle | Operand divides evenly (no remainder) |
| AC-56 | Generated Level 4 puzzle — brackets must matter | Expression evaluated with brackets differs from expression without brackets |
| AC-57 | Generated Level 5 puzzle — brackets necessary | No flat (un-bracketed) expression with same operators produces the target |
| AC-58 | Puzzle variety: student plays 3 sessions at Level 1 | Majority of puzzles differ across sessions (avoids recently seen) |

### 13.9 Management Command (`generate_puzzles`)

| # | Criteria | Expected Result |
|---|---------|----------------|
| AC-59 | Run `generate_puzzles --level 1 --count 500` | 500 valid Level 1 puzzles created in DB; summary printed |
| AC-60 | Run `generate_puzzles --all --count 500` | Puzzles generated for all 6 levels; per-level summary printed |
| AC-61 | Run command twice with same arguments (idempotency) | Second run skips existing puzzles; no duplicates created; DB count unchanged |
| AC-62 | Run `generate_puzzles` without `--level` or `--all` | Command exits with usage error |
| AC-63 | Run `generate_puzzles --level 7` | Command exits with error: "Invalid level: 7. Must be 1–6" |
| AC-64 | Run command when `NumberPuzzleLevel` fixtures not loaded | Command exits with error prompting to load fixtures first |
| AC-65 | Run `generate_puzzles --level 5 --count 1000` (exceeds possible) | Command generates all valid puzzles, warns that only N were possible, exits cleanly |
| AC-66 | Run `generate_puzzles --level 1 --count 50 --clear` | Existing unreferenced Level 1 puzzles deleted; 50 new puzzles generated |
| AC-67 | Run `--clear` when puzzles are referenced by `PuzzleAttempt` | Referenced puzzles preserved; only unreferenced puzzles deleted |
| AC-68 | Run `generate_puzzles --all --dry-run` | No DB writes; prints expected generation counts per level |

---

## 14. Future Extensibility

### 14.1 Additional Puzzle Types

Future versions may support:
- **Fill-in-the-number** — operator given, number missing: `_ + 3 = 8`
- **Multi-step chains** — `2 + 3 = _ , _ x 2 = ?`
- **Decimal/fraction puzzles** — for advanced levels

### 14.2 Teacher Dashboard Integration

- Teachers could view class-level statistics: how many students have reached each level
- Integration with `ProgressCriteria` from SPEC_TEACHER_CLASS_STUDENT_PROGRESS: a criterion like "Can solve Level 4 Number Puzzles" could be auto-marked based on puzzle progress

### 14.3 Leaderboards

- Per-school or per-class leaderboards showing fastest completion times
- Weekly/monthly puzzle challenges with time-limited puzzle sets

### 14.4 Dynamic Puzzle Generation

- For levels 1–3, puzzles could be generated at runtime as an alternative to pre-seeding
- This would provide unlimited variety without database storage concerns
- The pre-seeded approach in v1 provides a solid baseline

### 14.5 Mobile-Optimised Input

- Custom on-screen keyboard with number and operator buttons
- Visual bracket placement for levels 5–6

---

## 15. Open Items

These items require further definition in future spec iterations:

| # | Item | Notes |
|---|------|-------|
| OI-1 | **Puzzle pool size** | How many puzzles per level should be pre-generated? Proposed: 500. Levels 5–6 may have fewer valid puzzles due to constraints. |
| OI-2 | **Timer visibility** | Should a running timer be visible during the puzzle set, or only shown on results? Visible timers could cause anxiety for younger students. |
| OI-3 | **Hint system** | Should students get hints after N incorrect attempts? E.g., "Try using + or -" for Level 1. |
| OI-4 | **Sound effects** | Correct/incorrect audio feedback. Needs design decision on sound in educational app context. |
| OI-5 | **Retry on incorrect** | Should students be able to retry a puzzle within the same session, or does one attempt count? Current spec: one attempt per puzzle, immediate feedback, move on. |
| OI-6 | **Level 5–6 number ordering** | For expressions with commutativity (e.g., `3+4` vs `4+3`), the constraint is that numbers appear in the given order. Confirm this is desired. |
| OI-7 | **Analytics/reporting** | What aggregate statistics should be available to admins? Per-level completion rates, average scores, common errors? |

---

*End of specification.*
