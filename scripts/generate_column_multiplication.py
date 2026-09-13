"""Regenerate the column-multiplication question bank JSON.

Writes ``cwa_classroom/maths/seed_data/column_multiplication_year4_year5.json``
in the grouped schema ``manage.py import_global_questions`` consumes
(year / title / subtitle / questions), so the questions land under
Number > Multiplication at the right year level.

  Year 4 - 3-digit x 1-digit (50) and 4-digit x 1-digit (50)
  Year 5 - 3-digit x 2-digit (100), which is what draws the partial-product
           working rows in the column_operation widget.

Deterministic: the same SEED reproduces the same 200 questions byte for byte,
so re-running it is a no-op unless the rules below change.

Usage (from the repo root):
    python scripts/generate_column_multiplication.py
"""
import json
import os
import random

SEED = 20260913


def carries_single(a, b):
    """Number of carry steps when multiplying `a` by the single digit `b`."""
    n, carry = 0, 0
    for d in reversed(str(a)):
        prod = int(d) * b + carry
        carry = prod // 10
        if carry:
            n += 1
    return n


def explain_single(a, b):
    """Digit-by-digit column working for a x single-digit b."""
    steps, carry = [], 0
    digits = list(reversed(str(a)))
    for i, d in enumerate(digits):
        prod = int(d) * b
        total = prod + carry
        base = f"{d} \u00d7 {b} = {prod}"
        if carry:
            base += f", plus the {carry} carried = {total}"
        last = i == len(digits) - 1
        if total >= 10 and not last:
            base += f" - write {total % 10}, carry {total // 10}"
        steps.append(base)
        carry = total // 10
    return ". ".join(steps) + f". So {a} \u00d7 {b} = {a * b}."


def explain_double(a, b):
    """Partial-product working for a x two-digit b."""
    units, tens = b % 10, (b // 10) * 10
    parts = []
    if units:
        parts.append(f"{a} \u00d7 {units} = {a * units}")
    if tens:
        parts.append(f"{a} \u00d7 {tens} = {a * tens}")
    joined = ". Then ".join(parts)
    if len(parts) == 2:
        joined += f". Add the partial products: {a * units} + {a * tens} = {a * b}"
    return f"Split {b} into {tens} + {units}. {joined}. So {a} \u00d7 {b} = {a * b}."


def question(a, b, explanation, difficulty):
    return {
        "question_text": f"Work out {a} × {b} using column multiplication.",
        "question_type": "column_operation",
        "operands": [a, b],
        "operator": "*",
        "difficulty": difficulty,
        "points": 1,
        "explanation": explanation,
        "validation_type": "auto",
        "has_image": False,
        "answers": [],
    }


def pick(pool, n, rng):
    """Sample n pairs from pool, spread evenly across difficulty buckets."""
    buckets = {}
    for pair in pool:
        buckets.setdefault(pair[2], []).append(pair)
    keys = sorted(buckets)
    for k in keys:
        rng.shuffle(buckets[k])
    chosen, i = [], 0
    while len(chosen) < n:
        k = keys[i % len(keys)]
        if buckets[k]:
            chosen.append(buckets[k].pop())
        i += 1
        if all(not buckets[k] for k in keys):
            raise SystemExit("pool exhausted")
    return chosen


def difficulty_from_carries(c, max_c):
    """Map carry count onto the app's 1=Easy / 2=Medium / 3=Hard scale."""
    if c == 0:
        return 1
    if c >= max_c:
        return 3
    return 2


rng = random.Random(SEED)

# Multiplicands ending in "00" are excluded throughout: 300 x 19 is a
# place-value shift, not a column-algorithm exercise.

# ---- Year 4: 3-digit x 1-digit (50) and 4-digit x 1-digit (50) -------------
# Multiplier 2-9 only: x1 is a no-op and teaches nothing.
pool3 = [(a, b, difficulty_from_carries(carries_single(a, b), 3))
         for a in range(100, 1000) if a % 100
         for b in range(2, 10)]
pool4 = [(a, b, difficulty_from_carries(carries_single(a, b), 4))
         for a in range(1000, 10000) if a % 100
         for b in range(2, 10)]

y4 = []
for pool in (pool3, pool4):
    for a, b, d in sorted(pick(pool, 50, rng), key=lambda p: (p[2], p[0], p[1])):
        y4.append((a, b, explain_single(a, b), d))

# ---- Year 5: 3-digit x 2-digit (100) --------------------------------------
# Multipliers with a single significant digit (10, 20, ... 90) are skipped:
# the widget only draws the partial-product working rows when the multiplier
# has two non-zero digits, so those would render as the plain single-row
# layout instead of the long-multiplication one in the brief.
_c32 = {(a, b): carries_single(a, b % 10) + carries_single(a, b // 10)
        for a in range(100, 1000) if a % 100
        for b in range(12, 100) if b % 10 != 0}
_max_c32 = max(_c32.values())
pool32 = [(a, b, difficulty_from_carries(c, _max_c32)) for (a, b), c in _c32.items()]

y5 = [(a, b, explain_double(a, b), d)
      for a, b, d in sorted(pick(pool32, 100, rng), key=lambda p: (p[2], p[0], p[1]))]

groups = [
    {
        "year": "Year 4",
        "level_number": 4,
        "title": "Number",
        "subtitle": "Multiplication",
        "questions": [question(a, b, e, d) for (a, b, e, d) in y4],
    },
    {
        "year": "Year 5",
        "level_number": 5,
        "title": "Number",
        "subtitle": "Multiplication",
        "questions": [question(a, b, e, d) for (a, b, e, d) in y5],
    },
]

out = {
    "meta": {
        "source": "generated",
        "generated_from": "scripts/generate_column_multiplication.py",
        "description": (
            "Column (long) multiplication practice for the column_operation "
            "widget. Year 4 = 3-digit and 4-digit multiplicands by a single "
            "digit; Year 5 = 3-digit by 2-digit with partial-product rows. "
            "No multiplier is 1. Answers are computed by the app from "
            "operands/operator, so every 'answers' list is empty."
        ),
        "question_count": sum(len(g["questions"]) for g in groups),
        "group_count": len(groups),
        "schema": "import_global_questions",
    },
    "groups": groups,
}

path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cwa_classroom", "maths", "seed_data",
    "column_multiplication_year4_year5.json",
)
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("wrote", path, out["meta"]["question_count"], "questions")
