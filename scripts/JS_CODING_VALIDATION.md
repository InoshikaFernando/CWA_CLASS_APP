# JavaScript coding bank — validation report

Validation of the 104 ported JS exercises before seeding. The grader compares
`stdout === expected_output` after `rstrip` (`coding/scoring.py`), so every
`write_code` expected output must equal Node's `console.log` output exactly.

- **Machine proof:** `node scripts/validate_js_coding.js` — EXECUTED on Node
  v24.18.0: **94/94 executable exercises pass** (89 write_code + 5 computable
  quiz snippets), 0 fail, 0 missing. The 10 conceptual quiz items have no code
  to run and were verified by review.
- **Static review below:** every exercise reasoned through by hand.

## Result: 104/104 validated — 0 logic errors, 1 content fix applied

| Category | Count | Status |
|---|---|---|
| write_code | 89 | ✅ output matches expected |
| multiple_choice (computable) | 5 | ✅ marked answer = computed output |
| multiple_choice (conceptual) | 6 | ✅ answer correct by review |
| true_false | 2 | ✅ |
| fill_blank / short_answer | 2 | ✅ |

## Formatting-sensitive items explicitly checked (Node ≠ Python)

| Exercise | Risk | Verified output |
|---|---|---|
| Simple Math | float repr | `10/3` → `3.3333333333333335` (Node == Python) |
| Type Casting | parse + add | `parseInt("42")+parseFloat("3.14")` → `45.14` |
| Variable: A Boolean / Check Prime | bool case | `true` / `false` (lowercase) |
| Variable: Type of a Value / Type Inspector | `typeof` | `number` / `string` / `boolean` (no `<class>`; int+float both `number`) |
| Temperature Converter | decimal | `.toFixed(1)` → `77.0` |
| Filter Even / Double Each / Create Array / mutate-array | array print | `JSON.stringify` → `[2,4,6,8,10]`, `["apple",...]` (no inner spaces — avoids Node's `[ 1, 2 ]`) |
| Operator: Integer Division / Decimal→Integer | floor div | `Math.floor(17/5)`→`3`, `Math.trunc(9.8)`→`9` |

## Quiz adaptations where the JS answer differs from Python (verified)

- **Ternary syntax** — correct answer flips to `condition ? valueIfTrue : valueIfFalse` (Python's `a if c else b` is now a distractor).
- **"list comprehension"** → reframed to **`map()`** (creates a new transformed array).
- **"decorator"** → reframed to **higher-order function** (takes/returns a function).
- **`range()` questions** → rewritten as C-style / `for...of` loops; counts and outputs re-derived (e.g. `for i=0;i<5` is **not** 1–5 → False; `for...of 'cat'` blank is **`of`**).
- **`sort((a,b)=>b-a)`** on `[3,1,2]` → `[3, 2, 1]`.

## Content fix applied

- **Create and Print an Array** — the Python original (carried over) only said
  "create 5 fruits" but hard-codes the expected output to specific names. With
  an exact-match grader a different fruit list would fail. Instruction tightened
  to name the 5 items in order. (Regenerate with `build_js_coding_splits.py`.)

## Excluded (not ported) — 29 empty Python `multiple_choice` stubs

No description / starter / answers; several duplicate a real write_code of the
same title. IDs: 90,92,93,94,95,96,98,99,100,101,102,104,105,106,107,108,110,
111,112,113,114,115,116,117,118,120,121,122,123.
