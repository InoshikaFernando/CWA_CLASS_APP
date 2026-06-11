#!/usr/bin/env python3
"""
Generate Year 8 maths question sets (one JSON + one ZIP per topic) in the
classroom upload format consumed by MathsQuestionParser
(cwa_classroom/classroom/upload_services.py).

Source: "Year 8 Mid Year Exam" + "Theme 8 Revision" sheet.

Each topic produces:
    <slug>_year8.json          plain JSON (uploadable directly)
    <slug>_year8.zip           ZIP containing questions.json (same content)

Rules honoured:
  * one file per topic
  * every multiple_choice question has exactly one correct answer and NO
    distractor that is mathematically equal to the correct answer
    (e.g. never 1/2 alongside 2/4, never 1.130 alongside 1.13).
"""
import json
import os
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
YEAR = 8


def mc(text, options, correct_index, explanation, difficulty=1, points=1):
    """Build a multiple_choice question. options = list of answer strings."""
    return {
        "question_text": text,
        "question_type": "multiple_choice",
        "difficulty": difficulty,
        "points": points,
        "explanation": explanation,
        "answers": [
            {"text": str(o), "is_correct": (i == correct_index), "order": i}
            for i, o in enumerate(options)
        ],
    }


TOPICS = [
    # ───────────────────────── Number ──────────────────────────
    {
        "slug": "rounding_and_decimals",
        "strand": "Number",
        "topic": "Rounding and Decimals",
        "questions": [
            mc("Round 1.1300587 to 4 significant figures.",
               ["1.130", "1.131", "1.128", "1.310"], 0,
               "The first four significant figures are 1, 1, 3, 0. The next digit is 0, so round down to 1.130.",
               difficulty=1, points=1),
            mc("Round 1.1300587 to 2 decimal places.",
               ["1.13", "1.12", "1.14", "1.11"], 0,
               "The third decimal digit is 0, so round down: 1.13.",
               difficulty=1, points=1),
            mc("Does √13 give a terminating, non-terminating or recurring decimal?",
               ["Non-terminating", "Terminating", "Recurring"], 0,
               "√13 ≈ 3.6055… is irrational, so its decimal goes on forever without repeating: non-terminating.",
               difficulty=2, points=1),
            mc("Does 5/7 give a terminating, non-terminating or recurring decimal?",
               ["Recurring", "Terminating", "Non-terminating"], 0,
               "5/7 = 0.714285714285… — the block 714285 repeats forever, so it is recurring.",
               difficulty=2, points=1),
            mc("Does 495/990 give a terminating, non-terminating or recurring decimal?",
               ["Terminating", "Recurring", "Non-terminating"], 0,
               "495/990 simplifies to 1/2 = 0.5, which stops, so it is terminating.",
               difficulty=2, points=1),
        ],
    },
    {
        "slug": "ratio_and_proportion",
        "strand": "Number",
        "topic": "Ratio and Proportion",
        "questions": [
            mc("It takes 4 students 18 minutes to put away the tables at the end of lunch. "
               "How long would it take 9 students (working at the same rate)?",
               ["8 minutes", "40.5 minutes", "36 minutes", "4.5 minutes"], 0,
               "This is inverse proportion. Total work = 4 × 18 = 72 student-minutes. "
               "With 9 students: 72 ÷ 9 = 8 minutes.",
               difficulty=2, points=3),
            mc("A junior salesperson sells 4 cars for $3 400; the senior sells 1 car for $800. "
               "A bonus of 15% of total sales is shared 5 : 2 with the senior getting the larger share. "
               "How much bonus does the junior receive?",
               ["$180", "$450", "$630", "$90"], 0,
               "Total sales = 3400 + 800 = $4200. Bonus = 15% × 4200 = $630. "
               "Junior gets the smaller 2 of 7 parts: 630 × 2/7 = $180.",
               difficulty=3, points=5),
        ],
    },
    # ───────────────────────── Algebra ─────────────────────────
    {
        "slug": "rearranging_formulae",
        "strand": "Algebra",
        "topic": "Rearranging Formulae",
        "questions": [
            mc("Given F = a(b − c), make a the subject.",
               ["a = F/(b − c)", "a = F(b − c)", "a = Fb − c", "a = (b − c)/F"], 0,
               "Divide both sides by (b − c): a = F/(b − c).",
               difficulty=2, points=1),
            mc("Given F = a(b − c), make b the subject.",
               ["b = F/a + c", "b = F/a − c", "b = Fa + c", "b = (F − c)/a"], 0,
               "Divide by a: F/a = b − c, then add c: b = F/a + c.",
               difficulty=2, points=2),
            mc("Make x the subject of mx + c = y.",
               ["x = (y − c)/m", "x = (y + c)/m", "x = (c − y)/m", "x = y/m − c"], 0,
               "Subtract c then divide by m: x = (y − c)/m.",
               difficulty=2, points=1),
            mc("Make x the subject of x/t − c = y.",
               ["x = t(y + c)", "x = t(y − c)", "x = (y + c)/t", "x = ty + c"], 0,
               "Add c: x/t = y + c, then multiply by t: x = t(y + c).",
               difficulty=2, points=2),
            mc("Make x the subject of 2x − 1 = t.",
               ["x = (t + 1)/2", "x = (t − 1)/2", "x = 2(t + 1)", "x = t/2 − 1"], 0,
               "Add 1 then divide by 2: x = (t + 1)/2.",
               difficulty=1, points=1),
            mc("Make x the subject of (x + t)/c = m.",
               ["x = mc − t", "x = mc + t", "x = (m − t)/c", "x = m/c − t"], 0,
               "Multiply by c: x + t = mc, then subtract t: x = mc − t.",
               difficulty=2, points=1),
            mc("Make x the subject of t + x = r².",
               ["x = r² − t", "x = t − r²", "x = r² + t", "x = (r − t)²"], 0,
               "Subtract t from both sides: x = r² − t.",
               difficulty=1, points=1),
            mc("Make x the subject of m(2x − 1) = t.",
               ["x = (t + m)/(2m)", "x = (t − m)/(2m)", "x = (t + 1)/(2m)", "x = t/(2m) − 1"], 0,
               "Divide by m: 2x − 1 = t/m, add 1: 2x = t/m + 1 = (t + m)/m, divide by 2: x = (t + m)/(2m).",
               difficulty=3, points=2),
        ],
    },
    {
        "slug": "solving_linear_equations",
        "strand": "Algebra",
        "topic": "Solving Linear Equations",
        "questions": [
            mc("Solve (2t − 5)/3 = 3t − 4.",
               ["t = 1", "t = −1", "t = 7", "t = 11/7"], 0,
               "Multiply by 3: 2t − 5 = 9t − 12. So 7 = 7t, giving t = 1.",
               difficulty=2, points=4),
            mc("Solve 3x − 5 = 8.",
               ["x = 13/3", "x = 1", "x = 13", "x = 3"], 0,
               "Add 5: 3x = 13, then divide by 3: x = 13/3.",
               difficulty=1, points=1),
            mc("Solve x/4 + 2 = 5.",
               ["x = 12", "x = 28", "x = 3", "x = 7"], 0,
               "Subtract 2: x/4 = 3, then multiply by 4: x = 12.",
               difficulty=1, points=1),
            mc("Solve 5 − 3x = 11.",
               ["x = −2", "x = 2", "x = 6", "x = −6"], 0,
               "Subtract 5: −3x = 6, then divide by −3: x = −2.",
               difficulty=1, points=1),
            mc("Solve 4(2x − 3) = 6.",
               ["x = 9/4", "x = 9/8", "x = 3/4", "x = 9/2"], 0,
               "Expand: 8x − 12 = 6, so 8x = 18 and x = 18/8 = 9/4.",
               difficulty=2, points=1),
            mc("Solve 5x − 1 = 3x + 7.",
               ["x = 4", "x = 3", "x = −4", "x = 2"], 0,
               "Subtract 3x and add 1: 2x = 8, so x = 4.",
               difficulty=1, points=1),
            mc("Solve 8 − 2x = 5 + x.",
               ["x = 1", "x = −1", "x = 13", "x = 3"], 0,
               "Add 2x and subtract 5: 3 = 3x, so x = 1.",
               difficulty=1, points=1),
            mc("Solve 4 − 2x = 9 − 5x.",
               ["x = 5/3", "x = −5/3", "x = 5", "x = 3/5"], 0,
               "Add 5x and subtract 4: 3x = 5, so x = 5/3.",
               difficulty=2, points=1),
            mc("Solve 3(2x − 1) = 3.",
               ["x = 1", "x = 2", "x = 0", "x = 1/2"], 0,
               "Divide by 3: 2x − 1 = 1, so 2x = 2 and x = 1.",
               difficulty=1, points=1),
            mc("Solve 3(2x + 1) = 5(1 − 2x).",
               ["x = 1/8", "x = −1/8", "x = 8", "x = 1/4"], 0,
               "Expand: 6x + 3 = 5 − 10x. So 16x = 2 and x = 1/8.",
               difficulty=2, points=1),
            mc("Solve (2x − 1)/3 = 5.",
               ["x = 8", "x = 7", "x = 16", "x = 5"], 0,
               "Multiply by 3: 2x − 1 = 15, so 2x = 16 and x = 8.",
               difficulty=1, points=1),
            mc("Solve (x + 5)/3 − 4 = 1.",
               ["x = 10", "x = 0", "x = 18", "x = 8"], 0,
               "Add 4: (x + 5)/3 = 5, so x + 5 = 15 and x = 10.",
               difficulty=2, points=1),
            mc("Solve (x − 2)/3 = (x + 3)/5.",
               ["x = 19/2", "x = 19", "x = −19/2", "x = 9/2"], 0,
               "Cross-multiply: 5(x − 2) = 3(x + 3), so 5x − 10 = 3x + 9, 2x = 19, x = 19/2.",
               difficulty=3, points=2),
        ],
    },
    {
        "slug": "forming_and_solving_equations",
        "strand": "Algebra",
        "topic": "Forming and Solving Equations",
        "questions": [
            mc("I think of a number, multiply it by 4 and add 6; the answer is 17. "
               "Find the original number.",
               ["11/4", "11/2", "23/4", "44"], 0,
               "4n + 6 = 17, so 4n = 11 and n = 11/4.",
               difficulty=2, points=1),
            mc("I think of a number, subtract 5 and multiply the result by 3; the answer is 15. "
               "Find the original number.",
               ["10", "0", "20", "8"], 0,
               "3(n − 5) = 15, so n − 5 = 5 and n = 10.",
               difficulty=2, points=1),
            mc("Two triangles have equal perimeters. The first has sides 7x − 3, 5x + 1 and 6; "
               "the second has sides 3x + 2, 2x + 11 and 15. Find x.",
               ["24/7", "7/24", "24", "4"], 0,
               "12x + 4 = 5x + 28, so 7x = 24 and x = 24/7.",
               difficulty=3, points=2),
            mc("A rectangle has sides 6 and 2x + 1, and an area of 40 cm². Find x.",
               ["17/6", "6/17", "17", "11/3"], 0,
               "6(2x + 1) = 40, so 12x + 6 = 40, 12x = 34 and x = 17/6.",
               difficulty=3, points=2),
            mc("A rectangle has height 2y + 1 and base 5. Write a formula for its area A.",
               ["A = 10y + 5", "A = 2y + 6", "A = 10y + 1", "A = 7y"], 0,
               "A = base × height = 5(2y + 1) = 10y + 5.",
               difficulty=2, points=1),
            mc("The area of that rectangle is A = 10y + 5. Make y the subject.",
               ["y = (A − 5)/10", "y = (A + 5)/10", "y = (A − 5)/2", "y = A/10 − 5"], 0,
               "Subtract 5: 10y = A − 5, then divide by 10: y = (A − 5)/10.",
               difficulty=3, points=2),
        ],
    },
    {
        "slug": "expanding_brackets",
        "strand": "Algebra",
        "topic": "Expanding Brackets",
        "questions": [
            mc("Expand and simplify (x − 1)(x + 5).",
               ["x² + 4x − 5", "x² − 4x − 5", "x² + 4x + 5", "x² + 6x − 5"], 0,
               "x·x + 5x − x − 5 = x² + 4x − 5.",
               difficulty=2, points=1),
            mc("Expand and simplify (2x + 3)².",
               ["4x² + 12x + 9", "4x² + 9", "4x² + 6x + 9", "2x² + 12x + 9"], 0,
               "(2x + 3)(2x + 3) = 4x² + 6x + 6x + 9 = 4x² + 12x + 9.",
               difficulty=2, points=1),
            mc("Expand and simplify (2x − 3)(x + 7).",
               ["2x² + 11x − 21", "2x² − 11x − 21", "2x² + 11x + 21", "2x² + 4x − 21"], 0,
               "2x·x + 14x − 3x − 21 = 2x² + 11x − 21.",
               difficulty=2, points=1),
            mc("Expand and simplify (x − 8)².",
               ["x² − 16x + 64", "x² + 16x + 64", "x² − 64", "x² − 8x + 64"], 0,
               "(x − 8)(x − 8) = x² − 8x − 8x + 64 = x² − 16x + 64.",
               difficulty=2, points=1),
        ],
    },
    # ───────────────────────── Geometry ────────────────────────
    {
        "slug": "angles",
        "strand": "Geometry",
        "topic": "Angles",
        "questions": [
            mc("The interior angles of a triangle are in the ratio 2 : 3 : 7. "
               "Find the size of the obtuse angle.",
               ["105°", "45°", "30°", "75°"], 0,
               "Total parts = 12, and 180° ÷ 12 = 15° per part. The angles are 30°, 45° and 105°; "
               "the obtuse one is 7 × 15° = 105°.",
               difficulty=2, points=4),
            mc("The three angles of a triangle are 2x + 30, 4x and 2x − 10 (in degrees). "
               "Find the size of the smallest angle.",
               ["30°", "70°", "80°", "20°"], 0,
               "Sum = 180: 8x + 20 = 180, so x = 20. The angles are 70°, 80° and 30°; the smallest is 30°.",
               difficulty=2, points=1),
        ],
    },
]

# ═══════════════════════════════════════════════════════════════════════════
# Batch 2 — June 2026.
# Sources: "Algebra G8" linear-equations pack, "Year 8 Maths Exam Booklet —
# Algebra", "G8 Finance" pack, "G8 Applications of Pythagoras Theorem",
# "Quantitative Reasoning Test", "Selective" practice exam.
#
# EXTRA_QUESTIONS appends to the batch-1 topics above (one file per topic is
# preserved); NEW_TOPICS adds new topic files. Both are merged in main(),
# which also validates: exactly one correct answer per question, no duplicate
# option texts and no option mathematically equal to another (1/2 vs 2/4 etc).
# ═══════════════════════════════════════════════════════════════════════════
from fractions import Fraction


def _F(x):
    """Parse int/float/Fraction/'p/q' string into an exact Fraction."""
    if isinstance(x, Fraction):
        return x
    if isinstance(x, int):
        return Fraction(x)
    if isinstance(x, float):
        return Fraction(str(x))
    s = str(x).strip().replace("−", "-")
    if "/" in s:
        p, q = s.split("/")
        return Fraction(int(p), int(q))
    return Fraction(s)


def fnum(v):
    """Format a Fraction nicely: ints plain, terminating decimals as decimals,
    everything else as p/q."""
    v = _F(v)
    if v.denominator == 1:
        return str(v.numerator)
    d = v.denominator
    while d % 2 == 0:
        d //= 2
    while d % 5 == 0:
        d //= 5
    if d == 1:  # terminating decimal
        return ("%s" % float(v)).rstrip("0").rstrip(".")
    return f"{v.numerator}/{v.denominator}"


def leq(eq, sol, expl, difficulty=1, distractors=None):
    """Linear-equation MC. sol is exact (int / 'p/q' / float). Distractors are
    auto-generated near-misses unless given explicitly."""
    s = _F(sol)
    cands = [_F(d) for d in (distractors or [])]
    for c in (s + 1, s - 1, s + 2, s * 2, -s, s + 3, s + 4):
        if len(cands) >= 3:
            break
        if c != s and c not in cands and not (c == -s and s == 0):
            cands.append(c)
    opts = [fnum(s)] + [fnum(c) for c in cands[:3]]
    return mc(f"Solve {eq}.", opts, 0, expl, difficulty=difficulty)


def money(v):
    """$ formatting: whole dollars plain, otherwise 2 dp."""
    f = float(v)
    return f"${f:.2f}" if abs(f - round(f)) > 1e-9 else f"${int(round(f))}"


def mmc(text, correct, distractors, expl, difficulty=1):
    """Money MC with $-formatted options."""
    opts = [money(correct)] + [money(d) for d in distractors]
    return mc(text, opts, 0, expl, difficulty=difficulty)


EXTRA_QUESTIONS = {}
NEW_TOPICS = []

# ── Algebra G8 pack: solving linear equations (appended to batch-1 topic) ──
EXTRA_QUESTIONS["solving_linear_equations"] = [
    # "How much can you do???" warm-ups (two-step, one unknown)
    leq("3n + 4 = 19", 5, "Subtract 4: 3n = 15, so n = 15 ÷ 3 = 5."),
    leq("4n + 5 = 13", 2, "Subtract 5: 4n = 8, so n = 8 ÷ 4 = 2."),
    leq("4n − 3 = 25", 7, "Add 3: 4n = 28, so n = 28 ÷ 4 = 7."),
    leq("2n + 6 = 18", 6, "Subtract 6: 2n = 12, so n = 12 ÷ 2 = 6."),
    leq("3n − 2 = 16", 6, "Add 2: 3n = 18, so n = 18 ÷ 3 = 6."),
    leq("5n + 4 = 34", 6, "Subtract 4: 5n = 30, so n = 30 ÷ 5 = 6."),
    leq("3n + 7 = 19", 4, "Subtract 7: 3n = 12, so n = 12 ÷ 3 = 4."),
    leq("5n − 6 = 14", 4, "Add 6: 5n = 20, so n = 20 ÷ 5 = 4."),
    leq("3n − 3 = 21", 8, "Add 3: 3n = 24, so n = 24 ÷ 3 = 8."),
    leq("3n + 2 = 17", 5, "Subtract 2: 3n = 15, so n = 15 ÷ 3 = 5."),
    leq("4n + 6 = 14", 2, "Subtract 6: 4n = 8, so n = 8 ÷ 4 = 2."),
    leq("6n + 5 = 41", 6, "Subtract 5: 6n = 36, so n = 36 ÷ 6 = 6."),
    leq("5n − 3 = 7", 2, "Add 3: 5n = 10, so n = 10 ÷ 5 = 2."),
    leq("3n − 4 = 11", 5, "Add 4: 3n = 15, so n = 15 ÷ 3 = 5."),
    leq("7n + 3 = 24", 3, "Subtract 3: 7n = 21, so n = 21 ÷ 7 = 3."),
    # GCSE Grade E one/two-step
    leq("2x − 3 = 2", "5/2", "Add 3: 2x = 5, so x = 5/2 = 2.5."),
    leq("15 = 4x + 3", 3, "Subtract 3: 12 = 4x, so x = 12 ÷ 4 = 3."),
    leq("2x = 15", "15/2", "Divide by 2: x = 15/2 = 7.5."),
    leq("15 = 6 + x", 9, "Subtract 6: x = 15 − 6 = 9."),
    leq("4x − 7 = 13", 5, "Add 7: 4x = 20, so x = 20 ÷ 4 = 5."),
    leq("x/5 = 12", 60, "Multiply both sides by 5: x = 12 × 5 = 60."),
    leq("2x + 7 = 19", 6, "Subtract 7: 2x = 12, so x = 12 ÷ 2 = 6."),
    leq("2 = p − 8", 10, "Add 8 to both sides: p = 2 + 8 = 10."),
    leq("20y + 1 = 11", "1/2", "Subtract 1: 20y = 10, so y = 10/20 = 0.5."),
    leq("9 = x − 6", 15, "Add 6 to both sides: x = 9 + 6 = 15."),
    leq("4x = 20", 5, "Divide by 4: x = 20 ÷ 4 = 5."),
    leq("2x − 7 = 8", "15/2", "Add 7: 2x = 15, so x = 15/2 = 7.5."),
    leq("11 = x + 3", 8, "Subtract 3: x = 11 − 3 = 8."),
    leq("5x = 60", 12, "Divide by 5: x = 60 ÷ 5 = 12."),
    # Grade D — unknown on both sides
    leq("7n + 3 = 3n + 27", 6, "Subtract 3n: 4n + 3 = 27, so 4n = 24 and n = 6.", 2),
    leq("7n + 5 = 5n + 25", 10, "Subtract 5n: 2n + 5 = 25, so 2n = 20 and n = 10.", 2),
    leq("10n + 2 = 7n + 14", 4, "Subtract 7n: 3n + 2 = 14, so 3n = 12 and n = 4.", 2),
    leq("5n + 4 = 2n + 22", 6, "Subtract 2n: 3n + 4 = 22, so 3n = 18 and n = 6.", 2),
    leq("6n + 8 = 2n + 36", 7, "Subtract 2n: 4n + 8 = 36, so 4n = 28 and n = 7.", 2),
    leq("7n − 3 = 4n + 12", 5, "Subtract 4n: 3n − 3 = 12, so 3n = 15 and n = 5.", 2),
    leq("5n − 2 = n + 10", 3, "Subtract n: 4n − 2 = 10, so 4n = 12 and n = 3.", 2),
    leq("9n − 7 = 5n + 13", 5, "Subtract 5n: 4n − 7 = 13, so 4n = 20 and n = 5.", 2),
    leq("11n − 9 = 5n + 27", 6, "Subtract 5n: 6n − 9 = 27, so 6n = 36 and n = 6.", 2),
    leq("5n − 10 = 3n + 50", 30, "Subtract 3n: 2n − 10 = 50, so 2n = 60 and n = 30.", 2),
    leq("8n − 3 = 2n + 39", 7, "Subtract 2n: 6n − 3 = 39, so 6n = 42 and n = 7.", 2),
    leq("9n + 14 = 6n + 29", 5, "Subtract 6n: 3n + 14 = 29, so 3n = 15 and n = 5.", 2),
    leq("10n + 17 = 3n + 52", 5, "Subtract 3n: 7n + 17 = 52, so 7n = 35 and n = 5.", 2),
    leq("5n − 16 = n + 20", 9, "Subtract n: 4n − 16 = 20, so 4n = 36 and n = 9.", 2),
    leq("3n + 3 = 2n + 8", 5, "Subtract 2n: n + 3 = 8, so n = 5.", 2),
    # KS3 SATs-style
    leq("8k − 1 = 17", "9/4", "Add 1: 8k = 18, so k = 18/8 = 2.25.", 2),
    leq("2m + 5 = 10", "5/2", "Subtract 5: 2m = 5, so m = 5/2 = 2.5."),
    leq("3t + 4 = t + 13", "9/2", "Subtract t: 2t + 4 = 13, so 2t = 9 and t = 4.5.", 2),
    leq("2y + 11 = 17", 3, "Subtract 11: 2y = 6, so y = 3."),
    leq("9y + 3 = 5y + 13", "5/2", "Subtract 5y: 4y + 3 = 13, so 4y = 10 and y = 2.5.", 2),
    leq("7 + 5k = 8k + 1", 2, "Subtract 5k: 7 = 3k + 1, so 3k = 6 and k = 2.", 2),
    leq("10y + 23 = 4y + 26", "1/2", "Subtract 4y: 6y + 23 = 26, so 6y = 3 and y = 0.5.", 2),
    leq("4y = 2y + 13", "13/2", "Subtract 2y: 2y = 13, so y = 13/2 = 6.5.", 2),
    leq("3y + 10 = 2y + 7", -3, "Subtract 2y: y + 10 = 7, so y = 7 − 10 = −3.", 2),
    leq("4y − 3 = 2y + 27", 15, "Subtract 2y: 2y − 3 = 27, so 2y = 30 and y = 15.", 2),
    # GCSE — brackets and fractions
    leq("3x − 4 = x + 5", "9/2", "Subtract x: 2x − 4 = 5, so 2x = 9 and x = 4.5.", 2),
    leq("x/5 = 15", 75, "Multiply both sides by 5: x = 15 × 5 = 75."),
    leq("3x + 13 = 2(x + 9)", 5, "Expand: 3x + 13 = 2x + 18. Subtract 2x: x + 13 = 18, so x = 5.", 2),
    leq("5x − 2 = 3x + 12", 7, "Subtract 3x: 2x − 2 = 12, so 2x = 14 and x = 7.", 2),
    leq("2(2x + 3) = x − 13", "-19/3",
        "Expand: 4x + 6 = x − 13. Subtract x: 3x + 6 = −13, so 3x = −19 and x = −19/3.", 3),
    leq("(10 + 2x)/3 = 4", 1, "Multiply by 3: 10 + 2x = 12, so 2x = 2 and x = 1.", 2),
    leq("(9x − 15)/4 = 3", 3, "Multiply by 4: 9x − 15 = 12, so 9x = 27 and x = 3.", 2),
    leq("3(2x − 5) = 2(x − 4)", "7/4",
        "Expand: 6x − 15 = 2x − 8. Subtract 2x: 4x = 7, so x = 7/4.", 3),
    leq("x/5 = 7", 35, "Multiply both sides by 5: x = 7 × 5 = 35."),
    leq("(10 + 2x)/3 = 7", "11/2", "Multiply by 3: 10 + 2x = 21, so 2x = 11 and x = 5.5.", 2),
    leq("3(2x + 4) = x − 13", -5,
        "Expand: 6x + 12 = x − 13. Subtract x: 5x = −25, so x = −5.", 3),
    leq("(9x − 15)/4 = x", 3, "Multiply by 4: 9x − 15 = 4x, so 5x = 15 and x = 3.", 2),
    leq("3(2x − 1) − 2(x − 4) = 19", "7/2",
        "Expand: 6x − 3 − 2x + 8 = 19, so 4x + 5 = 19, 4x = 14 and x = 3.5.", 3),
    leq("(9x − 15)/4 = 2x + 3", 27,
        "Multiply by 4: 9x − 15 = 8x + 12. Subtract 8x: x = 27.", 3),
    leq("4(2x − 3) = 2(x − 4)", "2/3",
        "Expand: 8x − 12 = 2x − 8. Subtract 2x: 6x = 4, so x = 2/3.", 3),
    leq("e + e + e + e + e = 45", 9, "5e = 45, so e = 45 ÷ 5 = 9."),
    leq("18 − x = 13", 5, "x = 18 − 13 = 5."),
    leq("2(y − 5) = 24", 17, "Divide by 2: y − 5 = 12, so y = 17.", 2),
    leq("5x = 45", 9, "Divide by 5: x = 45 ÷ 5 = 9."),
    leq("w − 8 = 20", 28, "Add 8: w = 20 + 8 = 28."),
    leq("t/7 = 5", 35, "Multiply both sides by 7: t = 5 × 7 = 35."),
    leq("4x − 9 = 41", "25/2", "Add 9: 4x = 50, so x = 50/4 = 12.5.", 2),
    leq("3(x − 2) = x + 7", "13/2",
        "Expand: 3x − 6 = x + 7. Subtract x: 2x = 13, so x = 6.5.", 2),
    leq("x − 5 = 17", 22, "Add 5: x = 17 + 5 = 22."),
    leq("m/3 = 6", 18, "Multiply both sides by 3: m = 6 × 3 = 18."),
    leq("5y + 7 = 24", "17/5", "Subtract 7: 5y = 17, so y = 17/5 = 3.4.", 2),
    leq("(2y − 4)/3 = (4 − 2y)/4", 2,
        "Cross-multiply: 4(2y − 4) = 3(4 − 2y), so 8y − 16 = 12 − 6y, "
        "14y = 28 and y = 2.", 3, distractors=["-2/7", 8, 14]),
]

# ── Algebra G8 pack: rectangle perimeter (appended to forming topic) ──
EXTRA_QUESTIONS["forming_and_solving_equations"] = [
    mc("The width of a rectangle is x cm. The length is 1.5 cm more than the width. "
       "The perimeter of the rectangle is 17 cm. Find x.",
       ["3.5", "4.25", "7", "3"], 0,
       "Perimeter: 2(x + x + 1.5) = 17, so 4x + 3 = 17, 4x = 14 and x = 3.5.",
       difficulty=2),
]

# ── Exam booklet + Selective: expanding (appended to batch-1 topic) ──
EXTRA_QUESTIONS["expanding_brackets"] = [
    mc("Expand 2(x − 8).", ["2x − 16", "2x − 8", "2x + 16", "x − 16"], 0,
       "Multiply each term by 2: 2 × x − 2 × 8 = 2x − 16."),
    mc("Expand and fully simplify 4(x − 4) − 2(x + 1).",
       ["2x − 18", "2x − 14", "6x − 18", "2x + 18"], 0,
       "4x − 16 − 2x − 2 = 2x − 18.", difficulty=2),
    mc("Expand 3(x − 6).", ["3x − 18", "3x − 6", "3x + 18", "x − 18"], 0,
       "3 × x − 3 × 6 = 3x − 18."),
    mc("Expand 2x(3 − 4x).", ["6x − 8x²", "6x − 4x²", "6 − 8x²", "6x + 8x²"], 0,
       "2x × 3 − 2x × 4x = 6x − 8x².", difficulty=2),
    mc("Expand and simplify 7 − 4(5 + 2x).",
       ["−13 − 8x", "−13 + 8x", "27 + 8x", "−12 − 8x"], 0,
       "7 − 20 − 8x = −13 − 8x. Remember to multiply both terms by −4.", difficulty=2),
    mc("What is −2x(x − 3) simplified?",
       ["−2x² + 6x", "−2x − 3", "−2x² − 6x", "−2x + 6x"], 0,
       "−2x × x = −2x² and −2x × (−3) = +6x, so −2x² + 6x.", difficulty=2),
    mc("Expand −3(2x − y).", ["−6x + 3y", "−6x − 3y", "6x − 3y", "−6x + y"], 0,
       "−3 × 2x = −6x and −3 × (−y) = +3y.", difficulty=2),
    mc("Expand and simplify 5 − 2(x − 3).",
       ["11 − 2x", "2 − 2x", "−1 − 2x", "11 + 2x"], 0,
       "5 − 2x + 6 = 11 − 2x. The −2 multiplies both x and −3.", difficulty=2),
    mc("Expand 5(a + 4).", ["5a + 20", "5a + 4", "5a + 9", "a + 20"], 0,
       "5 × a + 5 × 4 = 5a + 20."),
    mc("Expand and simplify 2m(3m − 4) + 3m.",
       ["6m² − 5m", "6m² + 5m", "6m² − 11m", "5m² − 5m"], 0,
       "6m² − 8m + 3m = 6m² − 5m.", difficulty=2),
    mc("Expand and simplify a(b − a) − b(a − b).",
       ["b² − a²", "a² − b²", "2ab − a² − b²", "0"], 0,
       "ab − a² − ab + b² = b² − a².", difficulty=3),
    mc("Expand and simplify (x + 7)(x + 3).",
       ["x² + 10x + 21", "x² + 21x + 10", "x² + 10x + 10", "x² + 4x + 21"], 0,
       "x² + 3x + 7x + 21 = x² + 10x + 21.", difficulty=2),
    mc("Expand and simplify (x + 4y)² − (x + 6y)(x − 6y).",
       ["8xy + 52y²", "8xy − 20y²", "52y² − 8xy", "16y² + 8xy"], 0,
       "(x + 4y)² = x² + 8xy + 16y² and (x + 6y)(x − 6y) = x² − 36y². "
       "Subtracting: 8xy + 16y² + 36y² = 8xy + 52y².", difficulty=3),
    mc("Expand and simplify (4x + 2)(5x − 7).",
       ["20x² − 18x − 14", "20x² + 18x − 14", "20x² − 38x − 14", "20x² − 18x + 14"], 0,
       "20x² − 28x + 10x − 14 = 20x² − 18x − 14.", difficulty=2),
    mc("Expand and simplify (5x − 3)(2x² − 3x + 2).",
       ["10x³ − 21x² + 19x − 6", "10x³ + 21x² + 19x − 6",
        "10x³ − 21x² − 19x + 6", "10x³ − 9x² + 19x − 6"], 0,
       "10x³ − 15x² + 10x − 6x² + 9x − 6 = 10x³ − 21x² + 19x − 6.", difficulty=3),
    mc("Expand and simplify (4x − 1)² − (−x + 2)².",
       ["15x² − 4x − 3", "15x² − 12x + 5", "17x² − 12x + 5", "15x² + 4x − 3"], 0,
       "(4x − 1)² = 16x² − 8x + 1 and (−x + 2)² = x² − 4x + 4. "
       "Subtracting: 15x² − 4x − 3.", difficulty=3),
    mc("Expand (x + y)(x − y).",
       ["x² − y²", "2x − 2y", "x² + 2xy − y²", "x² − 2xy + y²"], 0,
       "Difference of two squares: the +xy and −xy terms cancel, leaving x² − y².",
       difficulty=2),
    mc("Expand and simplify (3x + 2)(2x − 5).",
       ["6x² − 11x − 10", "6x² − 19x − 10", "5x² − 4x − 7", "5x² − 12x − 7"], 0,
       "6x² − 15x + 4x − 10 = 6x² − 11x − 10.", difficulty=2),
]

# ── Selective + Quantitative: ratio/rates (appended to batch-1 topic) ──
EXTRA_QUESTIONS["ratio_and_proportion"] = [
    mc("The ratio of the population of three country towns A, B and C is 7 : 3 : 2 "
       "respectively. If the total population of the three towns is 84 000, find the "
       "population of town A.",
       ["49 000", "4 900", "70 000", "12 000"], 0,
       "Total parts = 12, so one part = 84 000 ÷ 12 = 7 000. Town A = 7 × 7 000 = 49 000.",
       difficulty=2),
    mc("A fertiliser contains 15.05 g of nitrogen in every 100 mL. "
       "How many grams of nitrogen are present in a 2 L bottle of this fertiliser?",
       ["301.00 g", "15.05 g", "30.10 g", "150.50 g"], 0,
       "2 L = 2 000 mL = 20 lots of 100 mL, so 20 × 15.05 g = 301.00 g.", difficulty=2),
    mc("A fertiliser contains 1.15 g of phosphorus and 8.03 g of potassium in every "
       "100 mL. A drum of the fertiliser contains 50 g of phosphorus. Which of the "
       "following is closest to the mass of potassium in the drum?",
       ["349 g", "402 g", "462 g", "623 g"], 0,
       "Volume = 50 ÷ 1.15 × 100 ≈ 4 348 mL. Potassium = 43.48 × 8.03 ≈ 349 g.",
       difficulty=3),
    mc("A smartphone screen has an aspect ratio (width : height) of 6 : 13. "
       "The width of the screen is 2340 pixels. What is the height of the screen in pixels?",
       ["5070", "1620", "1080", "5200"], 0,
       "Height = 2340 × 13/6 = 390 × 13 = 5070 pixels.", difficulty=2),
    mc("A screen with a resolution of 2160 × 1440 (width × height) and another screen "
       "with a resolution of 5120 × 1440 are both 28.62 cm high, with square pixels of "
       "the same size. What is the difference in the width of the two screens?",
       ["58.83 cm", "27.81 cm", "42.93 cm", "101.76 cm"], 0,
       "Each pixel is 28.62 ÷ 1440 = 0.019875 cm. Width difference = "
       "(5120 − 2160) × 0.019875 = 2960 × 0.019875 = 58.83 cm.", difficulty=3),
    mc("A concrete pre-mix contains only cement, sand and stone in a ratio of 1 : 1 : 2. "
       "For every 1 scoop of cement in the pre-mix, 0.45 L of water is needed. What is "
       "the approximate volume of water needed to make 5 scoops of pre-mix into concrete?",
       ["0.56 L", "0.75 L", "2.78 L", "3.70 L"], 0,
       "Cement is 1/4 of the mix: 5 × 1/4 = 1.25 scoops. Water = 1.25 × 0.45 = 0.5625 ≈ 0.56 L.",
       difficulty=3),
    mc("A pet medicine comes in 15 mL bottles and contains 0.5 mg of active ingredient "
       "per millilitre. Each dose needs 0.1 mg of active ingredient per kilogram of the "
       "pet's mass. A dog is given 12 equal doses that use up exactly two entire bottles. "
       "What is the mass of the dog?",
       ["12.5 kg", "6.25 kg", "12.0 kg", "50.0 kg"], 0,
       "Two bottles = 30 mL = 15 mg of active ingredient. Each dose = 15 ÷ 12 = 1.25 mg. "
       "Mass = 1.25 ÷ 0.1 = 12.5 kg.", difficulty=3),
    mc("A pet medicine contains 0.5 mg of active ingredient per millilitre. Each dose "
       "needs 0.1 mg of active ingredient per kilogram of the pet's mass. How much "
       "medicine does a 2.5 kg cat need in each dose?",
       ["0.5 mL", "0.2 mL", "0.25 mL", "1 mL"], 0,
       "Active ingredient needed = 2.5 × 0.1 = 0.25 mg. Volume = 0.25 ÷ 0.5 = 0.5 mL.",
       difficulty=2),
]

# ── Selective: decimal arithmetic (appended to batch-1 topic) ──
EXTRA_QUESTIONS["rounding_and_decimals"] = [
    mc("Calculate 27.003 − 13.105.",
       ["13.898", "13.989", "13.889", "13.988"], 0,
       "27.003 − 13.105 = 13.898 (borrow through the zeros: 27.003 − 13 = 14.003, "
       "then subtract 0.105).", difficulty=1),
]

# ── Exam booklet: simplifying expressions ──
NEW_TOPICS.append({
    "slug": "simplifying_expressions",
    "strand": "Algebra",
    "topic": "Simplifying Expressions",
    "questions": [
        mc("Which of the following algebraic expressions represents 2 less than 3 lots of n?",
           ["3n − 2", "3(n − 2)", "2 − 3n", "3 + n − 2"], 0,
           "\"3 lots of n\" is 3n; \"2 less than\" that is 3n − 2."),
        mc("Which of the following is the correct simplification of 12ab/24a²?",
           ["b/(2a)", "2ab", "2a/b", "ab/2"], 0,
           "12ab/24a² = (12/24) × (ab/a²) = (1/2) × (b/a) = b/(2a).", difficulty=2),
        mc("Simplify 5x − 3y² − 8x − 4y².",
           ["−3x − 7y²", "3x − 7y²", "−3x + 7y²", "−3x − y²"], 0,
           "5x − 8x = −3x and −3y² − 4y² = −7y²."),
        mc("Simplify 5s + 2m − 7s + 8m.",
           ["−2s + 10m", "2s + 10m", "2s − 10m", "−2s + 6m"], 0,
           "5s − 7s = −2s and 2m + 8m = 10m."),
        mc("Simplify 6d × dw.",
           ["6d²w", "6dw", "6d²w²", "6d"], 0,
           "6 × d × d × w = 6d²w."),
        mc("Which expression does ab/15 × 18/a simplify to?",
           ["6b/5", "a²b/15", "18a²/15", "18ab/15"], 0,
           "The a cancels: 18b/15 = 6b/5.", difficulty=2),
        mc("Which answer is a fully simplified form of 7p + 5p² − 3p?",
           ["4p + 5p²", "9p²", "10p + 5p²", "10p − 5p²"], 0,
           "Only the p terms combine: 7p − 3p = 4p, giving 4p + 5p². "
           "p and p² are not like terms.", difficulty=2),
        mc("Fully simplify 5mp + 2m − 7pm.",
           ["2m − 2mp", "2m + 2mp", "−2m − 2mp", "2m − 12mp"], 0,
           "5mp and −7pm are like terms: 5mp − 7mp = −2mp, leaving 2m − 2mp.",
           difficulty=2),
        mc("Fully simplify 4ab × 3a.",
           ["12a²b", "7a²b", "12ab", "12ab²"], 0,
           "4 × 3 = 12 and a × a = a², so 12a²b."),
        mc("Fully simplify 10bc/15c.",
           ["2b/3", "2c/3", "3b/2", "2bc/3"], 0,
           "The c cancels and 10/15 = 2/3, so 2b/3."),
        mc("Write down an expression for the number of weeks in m days.",
           ["m/7", "7m", "m − 7", "7/m"], 0,
           "Each week has 7 days, so m days = m ÷ 7 weeks."),
        mc("Simplify 4k + 6k ÷ 2.",
           ["7k", "5k", "10k", "3k"], 0,
           "Division first: 6k ÷ 2 = 3k, then 4k + 3k = 7k.", difficulty=2),
        mc("Simplify 3y × 4y².",
           ["12y³", "12y²", "7y³", "7y²"], 0,
           "3 × 4 = 12 and y × y² = y³, so 12y³.", difficulty=2),
        mc("Simplify a²b × ab².",
           ["a³b³", "a²b²", "a³b²", "a²b³"], 0,
           "a² × a = a³ and b × b² = b³, so a³b³.", difficulty=2),
        mc("Fully simplify (−5mn) × (−7mp) × (2np).",
           ["70m²n²p²", "−70m²n²p²", "70mnp", "35m²n²p²"], 0,
           "Signs: (−) × (−) × (+) = +. Numbers: 5 × 7 × 2 = 70. "
           "Letters: m², n², p². So 70m²n²p².", difficulty=3),
    ],
})

# ── Exam booklet + Selective: index laws ──
NEW_TOPICS.append({
    "slug": "index_laws",
    "strand": "Algebra",
    "topic": "Index Laws",
    "questions": [
        mc("Simplify (m⁶)³.", ["m¹⁸", "m⁹", "m³", "m⁶"], 0,
           "Power of a power: multiply the indices, 6 × 3 = 18.", difficulty=2),
        mc("Simplify (2p⁷)⁴.", ["16p²⁸", "8p²⁸", "16p¹¹", "2p²⁸"], 0,
           "2⁴ = 16 and (p⁷)⁴ = p²⁸.", difficulty=2),
        mc("Simplify 4a × 3a².", ["12a³", "12a²", "7a³", "7a²"], 0,
           "4 × 3 = 12 and a × a² = a³."),
        mc("Simplify (m⁴)⁵.", ["m²⁰", "m⁹", "m⁵", "m¹²"], 0,
           "Multiply the indices: 4 × 5 = 20.", difficulty=2),
        mc("Simplify a³ × a⁴.", ["a⁷", "a¹²", "a⁸", "a⁶"], 0,
           "When multiplying, add the indices: 3 + 4 = 7."),
        mc("Simplify −4y³ ÷ 12y.", ["−y²/3", "−y³/3", "−3y²", "y²/3"], 0,
           "−4/12 = −1/3 and y³ ÷ y = y², so −y²/3.", difficulty=2),
        mc("Simplify (3x²)³.", ["27x⁶", "9x⁶", "27x⁵", "3x⁶"], 0,
           "3³ = 27 and (x²)³ = x⁶.", difficulty=2),
        mc("Expand and simplify (3x²)²/12x⁴.",
           ["3/4", "1/4", "3/(4x²)", "1/256"], 0,
           "(3x²)² = 9x⁴, and 9x⁴/12x⁴ = 9/12 = 3/4.", difficulty=2),
        mc("Simplify (s⁵ − s⁴)/s¹¹.",
           ["(s − 1)/s⁷", "(s − 1)/s¹¹", "1/s²", "s − 1"], 0,
           "Factorise the top: s⁴(s − 1). Then s⁴/s¹¹ = 1/s⁷, giving (s − 1)/s⁷.",
           difficulty=3),
        mc("Solve (3³)³ ÷ (3²)².", ["3⁵", "3²", "3¹³", "3¹⁰"], 0,
           "(3³)³ = 3⁹ and (3²)² = 3⁴. Dividing: 3⁹⁻⁴ = 3⁵.", difficulty=2),
    ],
})

# ── Exam booklet + Selective: algebraic fractions ──
NEW_TOPICS.append({
    "slug": "algebraic_fractions",
    "strand": "Algebra",
    "topic": "Algebraic Fractions",
    "questions": [
        mc("Fully simplify 3s/6 + 5s/6.",
           ["4s/3", "2s/3", "8s/3", "s/3"], 0,
           "Same denominator: (3s + 5s)/6 = 8s/6 = 4s/3.", difficulty=2),
        mc("Fully simplify w/3 − 2w/7.",
           ["w/21", "−w/21", "w/4", "5w/21"], 0,
           "Common denominator 21: 7w/21 − 6w/21 = w/21.", difficulty=2),
        mc("Simplify 2m/3 − m/4.",
           ["5m/12", "m/12", "11m/12", "5m/7"], 0,
           "Common denominator 12: 8m/12 − 3m/12 = 5m/12.", difficulty=2),
        mc("Which expression does 2m/5 + m/3 simplify to?",
           ["11m/15", "3m/8", "2m/15", "11m/8"], 0,
           "Common denominator 15: 6m/15 + 5m/15 = 11m/15.", difficulty=2),
        mc("Fully simplify 40a/77b ÷ 36a²/35b².",
           ["50b/(99a)", "50a/(99b)", "99b/(50a)", "50ab/99"], 0,
           "Flip and multiply: 40a/77b × 35b²/36a² = (40 × 35)/(77 × 36) × b/a "
           "= 50b/(99a).", difficulty=3),
        mc("Fully simplify ab/12c × 6a/b.",
           ["a²/(2c)", "2a²/c", "ab/(2c)", "a/(2c)"], 0,
           "The b cancels and 6/12 = 1/2, leaving a²/(2c).", difficulty=2),
        mc("Fully simplify vw/21 ÷ tv/49.",
           ["7w/(3t)", "3w/(7t)", "7v/(3t)", "7w/3"], 0,
           "Flip and multiply: vw/21 × 49/tv. The v cancels and 49/21 = 7/3, "
           "giving 7w/(3t).", difficulty=3),
        mc("Simplify x/y − 2x/3a.",
           ["(3ax − 2xy)/(3ay)", "(3ax + 2xy)/(3ay)", "(2xy − 3ax)/(3ay)", "x/(3ay)"], 0,
           "Common denominator 3ay: 3ax/3ay − 2xy/3ay = (3ax − 2xy)/(3ay).",
           difficulty=3),
        mc("Simplify (3x + 7)/4 − (x − 1)/3.",
           ["(5x + 25)/12", "(5x + 17)/12", "(13x + 25)/12", "(5x − 25)/12"], 0,
           "(3(3x + 7) − 4(x − 1))/12 = (9x + 21 − 4x + 4)/12 = (5x + 25)/12. "
           "Watch the sign: −4 × (−1) = +4.", difficulty=3),
        mc("Simplify 2t/7 − t/6.",
           ["5t/42", "t/42", "19t/42", "5t/13"], 0,
           "Common denominator 42: 12t/42 − 7t/42 = 5t/42.", difficulty=2),
        mc("Simplify x/3 ÷ 5x²/6.",
           ["2/(5x)", "5x/2", "2x/5", "5/(2x)"], 0,
           "Flip and multiply: x/3 × 6/5x² = 6x/15x² = 2/(5x).", difficulty=3),
        mc("Simplify (x + 1)/6 + (2 − x)/5.",
           ["(17 − x)/30", "(x + 17)/30", "(7 − x)/30", "(17 − x)/11"], 0,
           "(5(x + 1) + 6(2 − x))/30 = (5x + 5 + 12 − 6x)/30 = (17 − x)/30.",
           difficulty=3),
        mc("Fully simplify b³/22 × 108/ab⁴ ÷ 27a/55b.",
           ["10/a²", "10b/a²", "10/a", "a²/10"], 0,
           "Flip the last fraction: b³/22 × 108/ab⁴ × 55b/27a. "
           "Numbers: 108/27 = 4, 55/22 = 5/2, and 4 × 5/2 = 10. "
           "Letters: b³ × b/b⁴ = 1 and 1/(a × a) = 1/a². Result: 10/a².", difficulty=3),
        mc("Fully simplify 1 − a/(a − b) − (a − b)/(a + b).",
           ["(ab − a² − 2b²)/(a² − b²)", "(a² − ab + 2b²)/(a² − b²)",
            "(ab − a² + 2b²)/(a² − b²)", "−b/(a − b)"], 0,
           "1 − a/(a − b) = −b/(a − b). Then −b/(a − b) − (a − b)/(a + b) "
           "= (−b(a + b) − (a − b)²)/(a² − b²) = (ab − a² − 2b²)/(a² − b²).",
           difficulty=3),
        mc("Simplify (1/x) / (2 + 3/x).",
           ["1/(2x + 3)", "x/(2x + 3)", "1/(3x + 2)", "(2x + 3)/x"], 0,
           "Multiply top and bottom by x: top becomes 1, bottom becomes 2x + 3.",
           difficulty=3),
        mc("Simplify (3x + 2)/5 + (x − 1)/2.",
           ["(11x − 1)/10", "(11x − 9)/10", "(11x + 9)/10", "(11x + 1)/10"], 0,
           "(2(3x + 2) + 5(x − 1))/10 = (6x + 4 + 5x − 5)/10 = (11x − 1)/10.",
           difficulty=2),
    ],
})

# ── Exam booklet + packs + Selective: factorising ──
NEW_TOPICS.append({
    "slug": "factorising",
    "strand": "Algebra",
    "topic": "Factorising",
    "questions": [
        mc("Fully factorise 3g + 12.",
           ["3(g + 4)", "3(g + 12)", "4(g + 3)", "3(g − 4)"], 0,
           "HCF is 3: 3g + 12 = 3(g + 4)."),
        mc("Factorise fully 4x + 8.",
           ["4(x + 2)", "4(x + 8)", "2(x + 4)", "4(x − 2)"], 0,
           "HCF is 4: 4x + 8 = 4(x + 2)."),
        mc("Factorise 3m + 18.",
           ["3(m + 6)", "3(m + 18)", "6(m + 3)", "3(m − 6)"], 0,
           "HCF is 3: 3m + 18 = 3(m + 6)."),
        mc("Factorise 15p + 40.",
           ["5(3p + 8)", "3(5p + 8)", "5(3p + 40)", "5(p + 8)"], 0,
           "HCF of 15 and 40 is 5: 15p + 40 = 5(3p + 8)."),
        mc("Fully factorise 12x²y − 18xy.",
           ["6xy(2x − 3)", "6xy(2x + 3)", "6xy(3 − 2x)", "6x²y(2x − 3)"], 0,
           "HCF is 6xy: 12x²y − 18xy = 6xy(2x − 3).", difficulty=2),
        mc("What is the fully factorised form of 14bm² − 7b²m?",
           ["7bm(2m − b)", "7bm(2b − m)", "7bm(2m + b)", "7bm(m − 2b)"], 0,
           "HCF is 7bm: 14bm² − 7b²m = 7bm(2m − b).", difficulty=2),
        mc("Factorise fully 9xy² − 12x²y.",
           ["3xy(3y − 4x)", "3xy(4x − 3y)", "3xy(3y + 4x)", "3xy(3x − 4y)"], 0,
           "HCF is 3xy: 9xy² − 12x²y = 3xy(3y − 4x).", difficulty=2),
        mc("Factorise 2a²b − 4ab.",
           ["2ab(a − 2)", "2ab(a + 2)", "2ab(b − 2)", "2ab(2 − a)"], 0,
           "HCF is 2ab: 2a²b − 4ab = 2ab(a − 2).", difficulty=2),
        mc("Fully factorise re²/11 − r²e³/11.",
           ["re²(1 − re)/11", "re²(1 + re)/11", "re(1 − re²)/11", "re²(re − 1)/11"], 0,
           "Common factor re²/11: re²/11 − r²e³/11 = re²(1 − re)/11.", difficulty=3),
        mc("Factorise fully 6x²y² − 8xy³.",
           ["2xy²(3x − 4y)", "2xy²(3x + 4y)", "2x²y(3x − 4y)", "2xy²(4y − 3x)"], 0,
           "HCF is 2xy²: 6x²y² − 8xy³ = 2xy²(3x − 4y).", difficulty=2),
        mc("Factorise x² − 14x + 49.",
           ["(x − 7)²", "(x + 7)²", "(x − 7)(x + 7)", "(x − 1)(x − 49)"], 0,
           "−7 × −7 = +49 and −7 + −7 = −14, so it is the perfect square (x − 7)².",
           difficulty=2),
        mc("Factorise completely 3x² + 9x − 12.",
           ["3(x + 4)(x − 1)", "3(x − 4)(x + 1)", "(x − 4)(3x + 3)", "3(x + 2)(x − 2)"], 0,
           "Take out 3 first: 3(x² + 3x − 4) = 3(x + 4)(x − 1).", difficulty=3),
        mc("The solutions to the equation x² + 11x − 12 = 0 are:",
           ["x = 1 or −12", "x = 12 or −1", "x = −2 or 6", "x = −6 or 2"], 0,
           "Factorise: (x + 12)(x − 1) = 0, so x = −12 or x = 1.", difficulty=3),
    ],
})

# ── Algebra pack + Selective: substitution ──
NEW_TOPICS.append({
    "slug": "substitution",
    "strand": "Algebra",
    "topic": "Substitution",
    "questions": [
        mc("When x = 5, work out the value of 2x + 13.",
           ["23", "33", "18", "38"], 0, "2 × 5 + 13 = 10 + 13 = 23."),
        mc("When x = 5, work out the value of 5x − 5.",
           ["20", "25", "0", "45"], 0, "5 × 5 − 5 = 25 − 5 = 20."),
        mc("When x = 5, work out the value of 3 + 6x.",
           ["33", "45", "27", "30"], 0, "3 + 6 × 5 = 3 + 30 = 33."),
        mc("If a = 5, b = 6 and c = 10, which one of the equations below is incorrect?",
           ["(a + b)² − 12c = a − b", "6a + 5b = 6c",
            "√(15(a + c)) = 3(b − 1)", "(a − b)² = c/10"], 0,
           "(a + b)² − 12c = 121 − 120 = 1, but a − b = 5 − 6 = −1, so it is incorrect. "
           "The others check out: 30 + 30 = 60, √225 = 15 = 3 × 5, and (−1)² = 1 = 10/10.",
           difficulty=3),
    ],
})

# ── Selective: inequalities ──
NEW_TOPICS.append({
    "slug": "inequalities",
    "strand": "Algebra",
    "topic": "Inequalities",
    "questions": [
        mc("If A = {x : x > 2} and B = {x : −1 < x < 3}, what is A ∩ B?",
           ["{x : 2 < x < 3}", "{x : 2 > x ≤ 3}", "{x : −1 < x < 3}", "{x : 3 < x < 2}"], 0,
           "The overlap of x > 2 and −1 < x < 3 is 2 < x < 3.", difficulty=2),
        mc("Solve (3β + 4)/6 > (2β − 4)/5.",
           ["β > −44/3", "β > −4/3", "β < −4/3", "β < −44/3"], 0,
           "Multiply both sides by 30: 5(3β + 4) > 6(2β − 4), so 15β + 20 > 12β − 24, "
           "3β > −44 and β > −44/3.", difficulty=3),
    ],
})

# ── Selective: coordinate geometry ──
NEW_TOPICS.append({
    "slug": "coordinate_geometry",
    "strand": "Algebra",
    "topic": "Coordinate Geometry",
    "questions": [
        mc("A line is drawn on the Cartesian plane. What is its slope when the "
           "y-intercept is (0, 6) and the x-intercept is (4, 0)?",
           ["−3/2", "−2/3", "3/2", "2/3"], 0,
           "Gradient = (0 − 6)/(4 − 0) = −6/4 = −3/2.", difficulty=2),
        mc("Which one of the following are the correct points of intersection for two "
           "graphs with the equations y = x² + 3 and y = −4x?",
           ["(−1, 4) and (−3, 12)", "(1, −4) and (3, −12)",
            "(1, −4) and (−3, 12)", "(−2, 4) and (3, −12)"], 0,
           "Set x² + 3 = −4x: x² + 4x + 3 = 0, so (x + 1)(x + 3) = 0 and x = −1 or −3. "
           "Then y = −4x gives (−1, 4) and (−3, 12).", difficulty=3),
        mc("The equation of a parabola is y = x². Which of these points will not touch "
           "the parabola?",
           ["(−3, 6)", "(2, 4)", "(−1, 1)", "(1/2, 1/4)"], 0,
           "(−3)² = 9, not 6, so (−3, 6) is not on the parabola. "
           "The other points all satisfy y = x².", difficulty=2),
    ],
})

# ── Selective: order of operations ──
NEW_TOPICS.append({
    "slug": "bodmas",
    "strand": "Algebra",
    "topic": "BODMAS",
    "questions": [
        mc("32 − 3 × (7 − 8 × 2) =",
           ["59", "5", "26", "38"], 0,
           "Inside the brackets first: 7 − 16 = −9. Then 32 − 3 × (−9) = 32 + 27 = 59.",
           difficulty=2),
    ],
})

# ── Selective: fractions ──
NEW_TOPICS.append({
    "slug": "fractions",
    "strand": "Number",
    "topic": "Fractions",
    "questions": [
        mc("Evaluate (3 × 2 2/3) ÷ (2/3 × 4 1/2).",
           ["2 2/3", "5 1/3", "24", "54"], 0,
           "3 × 8/3 = 8 and 2/3 × 9/2 = 3. Then 8 ÷ 3 = 8/3 = 2 2/3.", difficulty=2),
        mc("1/2 × 2 1/3 × 3/4 × 3 1/3 =",
           ["2 11/12", "2 1/8", "6 1/24", "3 5/12"], 0,
           "1/2 × 7/3 × 3/4 × 10/3 = 210/72 = 35/12 = 2 11/12.", difficulty=2),
        mc("Place in order (smallest to largest): 5/12, 5/7, 3/5.",
           ["5/12, 3/5, 5/7", "5/7, 3/5, 5/12", "5/7, 5/12, 3/5", "3/5, 5/7, 5/12"], 0,
           "As decimals: 5/12 ≈ 0.417, 3/5 = 0.6, 5/7 ≈ 0.714.", difficulty=2),
    ],
})

# ── Selective: surds ──
NEW_TOPICS.append({
    "slug": "surds",
    "strand": "Number",
    "topic": "Surds",
    "questions": [
        mc("Name the smallest surd in this group: 7√3, 5√7, 4√8, 9√2.",
           ["4√8", "7√3", "9√2", "5√7"], 0,
           "Square each: 7√3 → 147, 5√7 → 175, 4√8 → 128, 9√2 → 162. "
           "The smallest is 4√8.", difficulty=2),
        mc("Rationalise 5√2/√3.",
           ["5√6/3", "5√6/9", "6√5/3", "10/3"], 0,
           "Multiply top and bottom by √3: 5√2 × √3/3 = 5√6/3.", difficulty=2),
        mc("Simplify √((2√3)² + (2√15)²).",
           ["6√2", "6√3", "12√2", "√60"], 0,
           "(2√3)² = 12 and (2√15)² = 60, so √(12 + 60) = √72 = 6√2.", difficulty=3),
        mc("Which one of the following is a surd?",
           ["√4000", "√169", "√2500", "∛1000"], 0,
           "√169 = 13, √2500 = 50 and ∛1000 = 10 are all whole numbers; "
           "√4000 is irrational, so it is a surd.", difficulty=2),
    ],
})

# ── Selective: number properties ──
NEW_TOPICS.append({
    "slug": "number_properties",
    "strand": "Number",
    "topic": "Number Properties",
    "questions": [
        mc("What is the lowest common multiple of 15 and 12?",
           ["60", "3", "90", "180"], 0,
           "Multiples of 15: 15, 30, 45, 60… Multiples of 12: 12, 24, 36, 48, 60… "
           "The lowest in common is 60."),
        mc("Which one of these is always even?",
           ["even × even", "negative × positive", "odd + even", "odd × odd"], 0,
           "An even number times any whole number is even. odd + even is odd, "
           "odd × odd is odd, and negative × positive can be either.", difficulty=2),
        mc("Write the equivalent of 1783 (base 10) in base 6.",
           ["12 131", "12 415", "12 215", "12 315"], 0,
           "1783 = 1×1296 + 2×216 + 1×36 + 3×6 + 1, so 12131 in base 6.", difficulty=3),
    ],
})

# ── Finance pack + Selective + Quantitative: percentage increase/decrease ──
NEW_TOPICS.append({
    "slug": "percentage_increase_decrease",
    "strand": "Number",
    "topic": "Percentage Increase and Decrease",
    "questions": [
        mc("What is the percentage increase if a quantity rose from 420 m to 5 km?",
           ["1090.48%", "91.6%", "1190.48%", "109.05%"], 0,
           "5 km = 5000 m. Increase = 4580 m, so 4580/420 × 100 ≈ 1090.48%.",
           difficulty=2),
        mc("What is the percentage increase if a quantity rose from 23 hours to 1.6 days?",
           ["66.96%", "40.1%", "56.96%", "6.7%"], 0,
           "1.6 days = 38.4 hours. Increase = 15.4 h, so 15.4/23 × 100 ≈ 66.96%.",
           difficulty=2),
        mc("What is the percentage increase if a quantity rose from 24 cm to 30 cm?",
           ["25%", "20%", "6%", "30%"], 0,
           "Increase = 6 cm, so 6/24 × 100 = 25%. (6/30 = 20% is the wrong base.)"),
        mc("What is the percentage increase if a quantity rose from 850 mL to 1 L?",
           ["17.65%", "15%", "21.65%", "8.5%"], 0,
           "1 L = 1000 mL. Increase = 150 mL, so 150/850 × 100 ≈ 17.65%.", difficulty=2),
        mc("What is the percentage decrease if a quantity reduced from 120 mm to 9 cm?",
           ["25%", "33.33%", "30%", "12.5%"], 0,
           "9 cm = 90 mm. Decrease = 30 mm, so 30/120 × 100 = 25%.", difficulty=2),
        mc("What is the percentage decrease if a quantity reduced from 8 m to 600 cm?",
           ["25%", "33.33%", "20%", "75%"], 0,
           "600 cm = 6 m. Decrease = 2 m, so 2/8 × 100 = 25%.", difficulty=2),
        mc("What is the percentage decrease if a price reduced from $180 to $150?",
           ["16.67%", "20%", "30%", "83.33%"], 0,
           "Decrease = $30, so 30/180 × 100 ≈ 16.67%."),
        mc("What is the percentage decrease if a time reduced from 1.5 hours to 70 minutes?",
           ["22.22%", "28.57%", "20%", "77.78%"], 0,
           "1.5 hours = 90 minutes. Decrease = 20 min, so 20/90 × 100 ≈ 22.22%.",
           difficulty=2),
        mc("What is the percentage decrease if a speed reduced from 60 km/h to 45 km/h?",
           ["25%", "33.33%", "15%", "45%"], 0,
           "Decrease = 15 km/h, so 15/60 × 100 = 25%."),
        mc("What is the percentage decrease if a length reduced from 15 cm to 120 mm?",
           ["20%", "25%", "30%", "80%"], 0,
           "15 cm = 150 mm. Decrease = 30 mm, so 30/150 × 100 = 20%.", difficulty=2),
        mc("The TMJ bakery has special pricing depending on the day of the week. "
           "Mon–Fri you receive 20% off specials, and Sat–Sun you receive 30% off. "
           "Sally bought a muffin on special on Saturday for $3.50. How much would she "
           "have paid if she bought it on special on Wednesday?",
           ["$4.00", "$3.65", "$4.45", "$5.00"], 0,
           "Saturday price is 70% of full price, so full price = 3.50 ÷ 0.7 = $5.00. "
           "Wednesday is 20% off: 5.00 × 0.8 = $4.00.", difficulty=3),
        mc("Four performers' payments per show were increased for 2023 based on their "
           "2022 payment: Nguyen $360 + 4%, Aislinn $350 + 6%, Kaylah $370 + 1%, "
           "Abdu $340 + 8%. Which performer received the greatest show payment in 2023?",
           ["Nguyen", "Aislinn", "Kaylah", "Abdu"], 0,
           "Nguyen 360 × 1.04 = $374.40, Aislinn 350 × 1.06 = $371, "
           "Kaylah 370 × 1.01 = $373.70, Abdu 340 × 1.08 = $367.20. Nguyen is highest.",
           difficulty=2),
    ],
})

# ── Finance pack: GST ──
NEW_TOPICS.append({
    "slug": "gst",
    "strand": "Number",
    "topic": "GST",
    "questions": [
        mmc("Noah bought a pair of shoes for $418, which included a 10% GST. "
            "What was the cost of the shoes before GST?",
            380, [376.20, 38, 399],
            "The price including GST is 110% of the pre-GST price: 418 ÷ 1.1 = $380.",
            difficulty=2),
        mmc("Stella purchased a new smartwatch for $627, including a 10% GST. "
            "What was the price of the smartwatch before GST?",
            570, [564.30, 57, 598.50],
            "627 ÷ 1.1 = $570. (Subtracting 10% of $627 gives the wrong answer.)",
            difficulty=2),
        mmc("Chase bought a set of headphones for $533.50, including a 10% GST. "
            "What was the pre-GST price of the headphones?",
            485, [480.15, 48.50, 509.25],
            "533.50 ÷ 1.1 = $485.", difficulty=2),
        mmc("Kaan purchased a tablet for $1080.75, which included a 10% GST. "
            "What was the tablet's price before GST?",
            982.50, [972.68, 98.25, 1031.63],
            "1080.75 ÷ 1.1 = $982.50.", difficulty=2),
        mmc("Luke bought a digital camera for $1414.60, and the price included a 10% GST. "
            "What was the original price of the camera before GST?",
            1286, [1273.14, 128.60, 1350.30],
            "1414.60 ÷ 1.1 = $1286.", difficulty=2),
        mmc("Phillip bought a new laptop priced at $2457.40, which includes a 10% GST. "
            "How much did Phillip pay in GST?",
            223.40, [245.74, 111.70, 335.10],
            "For a 10% GST, the GST is 1/11 of the total: 2457.40 ÷ 11 = $223.40. "
            "(10% of the total, $245.74, is the classic wrong answer.)", difficulty=2),
        mmc("Sophie purchased a gaming console for $550, and this amount includes a "
            "10% GST. What was the GST amount Sophie paid?",
            50, [55, 25, 75],
            "GST = 550 ÷ 11 = $50.", difficulty=2),
        mmc("Oliver bought a bicycle for $719.81, with the total cost including a 10% GST. "
            "How much of that was GST?",
            65.44, [71.98, 32.72, 98.16],
            "GST = 719.81 ÷ 11 = $65.4373… ≈ $65.44.", difficulty=2),
        mmc("Amelia purchased a tote bag for $30.80, which had a 10% GST included. "
            "What is the GST portion of the price Amelia paid?",
            2.80, [3.08, 1.40, 4.20],
            "GST = 30.80 ÷ 11 = $2.80.", difficulty=2),
        mmc("Jack bought a pair of shoes for $1927.20, where the price includes a 10% GST. "
            "How much GST was included in the amount Jack paid?",
            175.20, [192.72, 87.60, 262.80],
            "GST = 1927.20 ÷ 11 = $175.20.", difficulty=2),
        mmc("Calculate the GST payable on a pack of corn chips with a pre-GST price of $3.75.",
            0.38, [0.34, 0.75, 0.19],
            "GST = 10% of 3.75 = $0.375, which rounds to $0.38.", difficulty=1),
        mmc("Calculate the GST payable on 30 cans of soft drink with a pre-GST price of $19.85.",
            1.99, [1.80, 3.97, 0.99],
            "GST = 10% of 19.85 = $1.985, which rounds to $1.99.", difficulty=1),
        mmc("Calculate the GST payable on an Apple Watch with a pre-GST price of $429.",
            42.90, [39, 85.80, 21.45],
            "GST = 10% of 429 = $42.90.", difficulty=1),
        mmc("Calculate the GST payable on a Samsung Galaxy Tablet with a pre-GST price of $379.",
            37.90, [34.45, 75.80, 18.95],
            "GST = 10% of 379 = $37.90.", difficulty=1),
        mmc("What is the final price of a bike with a pre-GST price of $129 after the "
            "10% GST is added?",
            141.90, [139, 154.80, 135.45],
            "Final price = 129 × 1.1 = $141.90.", difficulty=1),
        mmc("What is the final price of a basketball with a pre-GST price of $29 after "
            "the 10% GST is added?",
            31.90, [39, 34.80, 30.45],
            "Final price = 29 × 1.1 = $31.90.", difficulty=1),
        mmc("What is the final price of a 4K UHD TV with a pre-GST price of $1448 after "
            "the 10% GST is added?",
            1592.80, [1458, 1737.60, 1520.40],
            "Final price = 1448 × 1.1 = $1592.80.", difficulty=1),
        mmc("What is the final price of an iPhone with a pre-GST price of $1568 after "
            "the 10% GST is added?",
            1724.80, [1578, 1881.60, 1646.40],
            "Final price = 1568 × 1.1 = $1724.80.", difficulty=1),
    ],
})

# ── Finance pack + Quantitative + Selective: percentage word problems ──
NEW_TOPICS.append({
    "slug": "percentage_word_problems",
    "strand": "Number",
    "topic": "Percentage Word Problems",
    "questions": [
        mmc("Mariam bought a smartphone and sold it at a loss of $150. The loss was 20% "
            "of the original value. How much did she pay for her phone?",
            750, [300, 187.50, 600],
            "20% of the original is $150, so the original = 150 × 5 = $750.", difficulty=2),
        mmc("Koby spent $12 at lunchtime today. This represents 60% of his money. "
            "How much did he have at the beginning?",
            20, [19.20, 7.20, 30],
            "60% = $12, so 10% = $2 and 100% = $20.", difficulty=2),
        mmc("After Jacob spent 24% of his money, he still has $60 in his wallet. "
            "How much did Jacob have at the beginning?",
            78.95, [74.40, 45.60, 250],
            "$60 is 76% of his money, so 60 ÷ 0.76 = $78.95 (to the nearest cent).",
            difficulty=3),
        mmc("A laptop is discounted by 30% and sold for $1200. What was the original price?",
            1714.29, [1560, 840, 4000],
            "The sale price is 70% of the original: 1200 ÷ 0.7 = $1714.29.", difficulty=2),
        mmc("A calculator is sold for $44, which was marked up 30% on the original value. "
            "What was the original price of the calculator?",
            33.85, [30.80, 13.20, 57.20],
            "$44 is 130% of the original: 44 ÷ 1.3 = $33.85 (to the nearest cent).",
            difficulty=2),
        mc("In a mathematics test, Hayden answered 6 questions incorrectly. If he "
           "received a score of 85%, how many questions were in the test?",
           ["40", "35", "45", "24"], 0,
           "6 wrong = 15% of the test, so 1% = 0.4 questions and 100% = 40 questions.",
           difficulty=2),
        mc("In a particular school there are 648 girls, which represents 60% of the "
           "students in the school. What is the population of the school?",
           ["1080", "1037", "389", "972"], 0,
           "60% = 648, so 10% = 108 and 100% = 1080 students.", difficulty=2),
        mc("The cost of all the items in Ravi's shopping cart is $52. The home delivery "
           "fee is an extra $13. What percentage of the total amount Ravi pays is the "
           "home delivery fee?",
           ["20%", "15%", "25%", "40%"], 0,
           "Total paid = 52 + 13 = $65. Fee percentage = 13/65 × 100 = 20%.", difficulty=2),
        mc("Weather forecasters use the formula R = (C/100 × A/100) × 100, where R is "
           "the chance of rain (%), C is the forecaster's confidence (%) and A is the "
           "percentage of the region's area predicted to have rain. Forecasters predict "
           "with 50% confidence that it will rain in 40% of a region's area. What is the "
           "chance of rain in the region?",
           ["20%", "40%", "50%", "90%"], 0,
           "R = (50/100 × 40/100) × 100 = 0.5 × 0.4 × 100 = 20%.", difficulty=2),
        mc("Using the formula R = (C/100 × A/100) × 100 for the chance of rain: "
           "forecasters predict with 50% confidence that the chance of rain in a region "
           "is 30%. What percentage of the region's area do forecasters predict will "
           "have rain?",
           ["60%", "15%", "20%", "80%"], 0,
           "30 = (50/100 × A/100) × 100 = A/2, so A = 60%.", difficulty=3),
        mc("A household solar system is generating 2.167 kW of electricity. The "
           "household is using 0.772 kW and feeding 1.395 kW into the grid. What "
           "percentage of the electricity generated is being used in the household?",
           ["36%", "28%", "55%", "64%"], 0,
           "0.772/2.167 × 100 ≈ 35.6%, which is closest to 36%.", difficulty=2),
        mc("Jenny is paid 3% annual interest on the $6 000 that she has in the bank. "
           "She is offered a bonus 1.5% (on top of the standard 3% interest rate) for "
           "three months on a deposit of $2 000 in an online account. She transfers "
           "$2 000 from her bank account into the online saver account. How much "
           "interest will she have made over the two accounts, in total, in the three "
           "month bonus interest period?",
           ["$52.50", "$210", "$157.50", "$67.50"], 0,
           "Bank: $4 000 at 3% for 3 months = 4000 × 0.03 ÷ 4 = $30. "
           "Online: $2 000 at 4.5% for 3 months = 2000 × 0.045 ÷ 4 = $22.50. "
           "Total = $52.50.", difficulty=3),
    ],
})

# ── Finance pack: profit and loss ──
NEW_TOPICS.append({
    "slug": "profit_and_loss",
    "strand": "Number",
    "topic": "Profit and Loss",
    "questions": [
        mmc("Cost price: $400. Profit: 20%. What is the selling price?",
            480, [420, 320, 800],
            "Selling price = 400 × 1.20 = $480.", difficulty=1),
        mmc("Cost price: $800. Loss: 15%. What is the selling price?",
            680, [920, 120, 785],
            "Selling price = 800 × 0.85 = $680.", difficulty=1),
        mmc("Cost price: $500. Profit: 10%. What is the selling price?",
            550, [510, 450, 600],
            "Selling price = 500 × 1.10 = $550.", difficulty=1),
        mmc("Cost price: $1,000. Profit: 30%. What is the selling price?",
            1300, [1030, 700, 1330],
            "Selling price = 1000 × 1.30 = $1300.", difficulty=1),
        mmc("Cost price: $700. Profit: 12%. What is the selling price?",
            784, [712, 616, 788],
            "Selling price = 700 × 1.12 = $784.", difficulty=1),
        mmc("Cost price: $350. Loss: 8%. What is the selling price?",
            322, [378, 342, 28],
            "Selling price = 350 × 0.92 = $322.", difficulty=1),
        mmc("Selling price: $782. Profit: 15%. What is the cost price?",
            680, [664.70, 899.30, 767],
            "The selling price is 115% of the cost price: 782 ÷ 1.15 = $680. "
            "(782 × 0.85 is the classic wrong method.)", difficulty=2),
        mmc("Selling price: $1,200. Profit: 25%. What is the cost price?",
            960, [900, 1500, 1175],
            "1200 ÷ 1.25 = $960.", difficulty=2),
        mmc("Selling price: $600. Loss: 5%. What is the cost price?",
            631.58, [630, 570, 605],
            "The selling price is 95% of the cost price: 600 ÷ 0.95 = $631.58.",
            difficulty=2),
        mmc("Selling price: $720. Loss: 10%. What was the original cost price?",
            800, [792, 648, 730],
            "720 is 90% of the cost price: 720 ÷ 0.9 = $800.", difficulty=2),
        mmc("Emily sold a guitar for $750 and experienced a loss of 20%. "
            "What was the original cost price of the guitar?",
            937.50, [900, 600, 770],
            "750 is 80% of the cost price: 750 ÷ 0.8 = $937.50.", difficulty=2),
        mmc("James bought a bicycle for $400 and wants to sell it for a profit of 25%. "
            "What should be the selling price of the bicycle?",
            500, [425, 300, 525],
            "Selling price = 400 × 1.25 = $500.", difficulty=1),
        mc("Jett bought a headphone set for $230 and sold it for $350. "
           "What was the result?",
           ["Profit of $120", "Loss of $120", "Profit of $580", "Loss of $230"], 0,
           "Selling price − cost price = 350 − 230 = $120 profit.", difficulty=1),
        mc("Lily bought a smartwatch for $540 and sold it for $380. What was the result?",
           ["Loss of $160", "Profit of $160", "Loss of $920", "Profit of $380"], 0,
           "Cost price − selling price = 540 − 380 = $160 loss.", difficulty=1),
        mc("Chloe bought a laptop for $460 and sold it for $510. Did Chloe make a "
           "profit or a loss? How much?",
           ["Profit of $50", "Loss of $50", "Profit of $150", "Loss of $150"], 0,
           "510 − 460 = $50 profit.", difficulty=1),
        mc("Aryan bought an iPhone for $1760 and sold it for $1350. Did Aryan have a "
           "profit or a loss? How much?",
           ["Loss of $410", "Profit of $410", "Loss of $310", "Loss of $510"], 0,
           "1760 − 1350 = $410 loss.", difficulty=1),
        mc("Leah bought a pair of shoes for $350 and sold them for $390. Did Leah make "
           "a profit or a loss? What is the amount?",
           ["Profit of $40", "Loss of $40", "Profit of $50", "Loss of $50"], 0,
           "390 − 350 = $40 profit.", difficulty=1),
        mc("Nicholas bought a tablet for $600 and sold it for $575. Did Nicholas make "
           "a profit or a loss? How much?",
           ["Loss of $25", "Profit of $25", "Loss of $175", "Profit of $175"], 0,
           "600 − 575 = $25 loss.", difficulty=1),
        mc("Anthony bought a headphone set for $245 and sold it for $260. Did Anthony "
           "make a profit or a loss? What is the amount?",
           ["Profit of $15", "Loss of $15", "Profit of $25", "Loss of $25"], 0,
           "260 − 245 = $15 profit.", difficulty=1),
        mmc("Tom bought a bicycle for $375 and made a profit of $75. "
            "What was the selling price of the bicycle?",
            450, [300, 425, 475],
            "Selling price = cost price + profit = 375 + 75 = $450.", difficulty=1),
        mmc("Jessica sold a dress for $200, with a loss of $30. "
            "What was the cost price of the dress?",
            230, [170, 260, 215],
            "Cost price = selling price + loss = 200 + 30 = $230.", difficulty=1),
        mmc("Emma bought a book for $120 and made a profit of $24. "
            "What was the selling price?",
            144, [96, 134, 154],
            "120 + 24 = $144.", difficulty=1),
        mmc("Liam bought a jacket for $250 and sold it making a profit of $56. "
            "What was the selling price?",
            306, [194, 296, 316],
            "250 + 56 = $306.", difficulty=1),
        mmc("Olivia sold a laptop for $750, with a loss of $75. What was the buying price?",
            825, [675, 815, 850],
            "Buying price = 750 + 75 = $825.", difficulty=1),
        mmc("Noah bought a chair for $150 and sold it making a profit of $37. "
            "What was the selling price?",
            187, [113, 177, 197],
            "150 + 37 = $187.", difficulty=1),
        mmc("Jenny sold a mobile phone for $1450, with a profit of $180. "
            "What was the buying price?",
            1270, [1630, 1260, 1280],
            "Buying price = selling price − profit = 1450 − 180 = $1270.", difficulty=1),
        mmc("Lucas bought a painting for $120 and sold it at a loss of $95. "
            "What was the selling price?",
            25, [215, 35, 95],
            "Selling price = 120 − 95 = $25.", difficulty=1),
        mmc("Mia bought an electric scooter for $250 and sold it making a profit of $57. "
            "What was the selling price?",
            307, [193, 297, 317],
            "250 + 57 = $307.", difficulty=1),
        mmc("Ethan bought a desk for $420 and sold it at a loss of $160. "
            "What was the selling price?",
            260, [580, 250, 270],
            "420 − 160 = $260.", difficulty=1),
        mmc("Isabella sold a printer for $420, with a loss of $130. "
            "What was the buying price?",
            550, [290, 540, 560],
            "Buying price = 420 + 130 = $550.", difficulty=1),
        mmc("Oliver bought a camera for $680 and sold it making a profit of $75. "
            "What was the selling price?",
            755, [605, 745, 765],
            "680 + 75 = $755.", difficulty=1),
    ],
})

# ── Selective + Quantitative: problem solving ──
NEW_TOPICS.append({
    "slug": "problem_solving",
    "strand": "Number",
    "topic": "Problem Solving",
    "questions": [
        mc("Thirty-seven of my sister's friends were asked what type of jewellery they "
           "liked. Fourteen said that they only liked gold whilst twelve said that they "
           "only wore silver. The others replied that they didn't care what they wore. "
           "How many wore some silver?",
           ["23", "24", "25", "26"], 0,
           "Everyone except the 14 gold-only friends might wear silver: 37 − 14 = 23 "
           "(the 12 silver-only plus the 11 who don't care).", difficulty=2),
        mc("Red lollies cost 8 cents each and green lollies cost 9 cents each. A bowl "
           "contains 25 lollies with both types in it, and the total cost of the lollies "
           "is $2.09. How many red and how many green lollies are there?",
           ["red 16, green 9", "red 9, green 16", "red 10, green 15", "red 15, green 10"], 0,
           "If all 25 were green: 25 × 9 = 225c. The total is 209c, which is 16c less; "
           "each red lolly saves 1c, so there are 16 red and 9 green.", difficulty=3),
        mc("A dam, full of water, holds 60 GL. Reservoir A holds 20 GL and Reservoir B "
           "holds 16 GL of water. If the reservoirs are 1/4 full and the dam filled them "
           "up, how much water would be left in the dam?",
           ["33 GL", "27 GL", "36 GL", "24 GL"], 0,
           "A needs 3/4 × 20 = 15 GL and B needs 3/4 × 16 = 12 GL. "
           "60 − 15 − 12 = 33 GL.", difficulty=2),
        mc("A table of cars shows: Land Rover $40 000 with 4 or 5 seats (including a "
           "fitted baby seat); Pajero $38 000 with 6 or 7 seats (including a fitted baby "
           "seat); Odyssey $38 000 with 5 seats (no allowance for a baby seat); X-Trail "
           "$30 000 with 5 seats (including a fitted baby seat); Sportage $27 000 with "
           "5 seats (no allowance for a baby seat). Which car would be the most "
           "economical to buy for a family of five including one baby?",
           ["X-Trail", "Pajero", "Odyssey", "Land Rover"], 0,
           "The family needs 5 seats including a baby seat. The cheapest car that "
           "provides that is the X-Trail at $30 000.", difficulty=2),
        mc("Using the same car table (Land Rover $40 000, up to 5 seats; Pajero $38 000, "
           "up to 7 seats; Odyssey $38 000, 5 seats; X-Trail $30 000, 5 seats; Sportage "
           "$27 000, 5 seats), which car would be the most expensive car per seat?",
           ["Land Rover", "Sportage", "Odyssey", "Pajero"], 0,
           "Cost per seat: Land Rover 40000/5 = $8 000, Odyssey 38000/5 = $7 600, "
           "X-Trail $6 000, Sportage $5 400, Pajero 38000/7 ≈ $5 429. "
           "The Land Rover is the most expensive per seat.", difficulty=2),
        mc("Eddie and three friends are going to a café. Eddie leaves home and drives "
           "4 km east and 4 km south to Chris's house. They then drive 6 km north and "
           "2 km west to pick up Sophie and James from work. They all then drive 4 km "
           "south to the café. Who was closest to the café?",
           ["Eddie and Chris", "Sophie and James", "Eddie", "Chris"], 0,
           "Taking Eddie's home as (0, 0): Chris is at (4, −4), the workplace at (2, 2) "
           "and the café at (2, −2). Eddie's home and Chris's house are both √8 ≈ 2.8 km "
           "from the café; the workplace is 4 km away. Eddie and Chris tie.", difficulty=3),
        mc("Frank was mowing a lawn. In one hour he finished 20%. In the hours "
           "following, he completed 50% of the remaining lawn per hour. For how many "
           "hours was Frank mowing until he got to the last 10% of the lawn?",
           ["4 hours", "1 hour", "2 hours", "3 hours"], 0,
           "After hour 1: 80% left. Hour 2: 40% left. Hour 3: 20% left. "
           "Hour 4: 10% left. So 4 hours.", difficulty=3),
        mc("Remi plans a holiday with these expenses: flights and insurance $800; "
           "accommodation $40 per night; food $450; activities $1 500; spending money "
           "$180. She arrives in the afternoon on Saturday 3 August and leaves at midday "
           "on Sunday 18 August (15 nights). What is the total cost of the holiday?",
           ["$3 530", "$2 970", "$9 340", "$9 830"], 0,
           "Accommodation = 15 × 40 = $600. Total = 800 + 600 + 450 + 1500 + 180 = $3 530.",
           difficulty=2),
        mc("At the time of Remi's planning, 1 Australian dollar = 9 936 Indonesian "
           "rupiah (IDR). How much is Remi's $180 spending money worth in IDR?",
           ["1 788 480 IDR", "10 143 IDR", "993 600 IDR", "4 471 200 IDR"], 0,
           "180 × 9 936 = 1 788 480 IDR.", difficulty=1),
        mc("A hair salon books 'cut only' appointments of 30 min (short hair), 45 min "
           "(medium) and 1 h (long). In one day the salon booked 8 clients with short "
           "hair, 12 with medium hair and 4 with long hair, and one-quarter of the "
           "clients within each group had a 'cut only' booking. What was the total time "
           "booked for 'cut only' appointments?",
           ["4 h 15 min", "6 h", "11 h 30 min", "12 h 45 min"], 0,
           "Cut-only clients: 2 short, 3 medium, 1 long. "
           "2 × 30 + 3 × 45 + 1 × 60 = 60 + 135 + 60 = 255 min = 4 h 15 min.",
           difficulty=3),
        mc("At the same salon, 'cut and colour' appointments take 1 h 30 min (short "
           "hair), 2 h (medium) or 2 h 30 min (long). A hairdresser works a 12-hour "
           "shift with 2 hours of breaks and no overlapping appointments. What is the "
           "maximum number of 'cut and colour' appointments the hairdresser can fit "
           "into the shift?",
           ["6", "5", "7", "8"], 0,
           "Working time = 10 h. The shortest appointment is 1.5 h: 10 ÷ 1.5 = 6.7, "
           "so at most 6 appointments.", difficulty=2),
        mc("In Mölkky, skittles are numbered 1 to 12. If exactly one skittle is knocked "
           "over, the points scored equal the number on the skittle; if two or more are "
           "knocked over, the points equal the number of skittles knocked over. A player "
           "throws three times: first knocking over skittles 1, 3 and 7; then the skittle "
           "numbered 12; then skittles 4 and 5. What is the player's total score?",
           ["17", "6", "24", "32"], 0,
           "Throw 1: three skittles = 3 points. Throw 2: one skittle = 12 points. "
           "Throw 3: two skittles = 2 points. Total = 3 + 12 + 2 = 17.", difficulty=2),
        mc("In Mölkky (max 12 points per throw), a player wins by reaching exactly 50 "
           "points; going over 50 drops them back to 25. Consider these statements — "
           "Statement 1: a player with 38 points cannot reach exactly 50 on their next "
           "throw. Statement 2: a player with 49 points must exceed 50 on their next "
           "throw. Statement 3: it is impossible to win with exactly four throws. "
           "Which statements are always true?",
           ["Statement 3 only", "Statements 1 and 2", "Statements 1 and 3",
            "Statement 2 only"], 0,
           "1 is false (knocking over only skittle 12 gives 38 + 12 = 50). 2 is false "
           "(knocking over only skittle 1 gives exactly 50). 3 is true: the maximum per "
           "throw is 12, and 4 × 12 = 48 < 50.", difficulty=3),
        mc("PV Power pays a solar feed-in tariff of 12c/kWh for the first 14 kWh per day "
           "and 4.9c/kWh thereafter. On one day a household feeds 21 kWh back into the "
           "grid. What is the total amount PV Power credits the household for this day?",
           ["$2.02", "$1.68", "$2.52", "$5.11"], 0,
           "14 × 12c = 168c, plus 7 × 4.9c = 34.3c. Total ≈ $2.02.", difficulty=2),
        mc("Four solar feed-in tariffs are offered: PV Power 12c/kWh for the first "
           "14 kWh per day then 4.9c/kWh; Saber Solar 15c/kWh for the first 15 kWh per "
           "day then 5.4c/kWh, up to a maximum of $650 per year; Greenewable Plus "
           "7c/kWh up to a maximum of $800 per year; Panel Plus Solar 5.4c/kWh with no "
           "conditions. A household feeds in 17 kWh per day. Which company would provide "
           "the greatest credit for one year?",
           ["PV Power", "Saber Solar", "Greenewable Plus", "Panel Plus Solar"], 0,
           "Per day: PV Power 14×12 + 3×4.9 = 182.7c → $666.86/yr. Saber 15×15 + 2×5.4 "
           "= 235.8c → $860.67 but capped at $650. Greenewable 17×7 = 119c → $434.35. "
           "Panel Plus 17×5.4 = 91.8c → $335.07. PV Power pays the most.", difficulty=3),
        mc("People donate $1 each to play a charity game. For each winner, $3 is given "
           "to a wildlife shelter, and whatever money is left over goes to the school "
           "breakfast club. At a fair, 100 people play and 20 of them win. How much "
           "money was given to the school breakfast club?",
           ["$40", "$20", "$60", "$100"], 0,
           "Collected $100; the shelter receives 20 × $3 = $60; the club gets the "
           "remaining $40.", difficulty=2),
        mc("A meeting must start between 5 am and 10 pm in each participant's local "
           "time. When it is 8 am on 27 June in Melbourne, it is 4 pm on 26 June in "
           "Mexico City and 11 pm on 26 June in London. Possible start times are: "
           "I — 7 am Melbourne time; II — 3 pm Melbourne time; III — 9 pm Melbourne "
           "time. Which of the times meet the criteria?",
           ["I and III only", "I only", "II only", "I and II only"], 0,
           "Mexico City is 16 h behind Melbourne and London is 9 h behind. "
           "I: 7 am Mel = 3 pm Mexico, 10 pm London — all OK. "
           "II: 3 pm Mel = 11 pm Mexico — too late. "
           "III: 9 pm Mel = 5 am Mexico, 12 pm London — all OK.", difficulty=3),
        mc("At a school, Unit 3 and 4 Biology has 115 students enrolled and Unit 3 and 4 "
           "General Mathematics has 135. The maximum class size is 25, and both subjects "
           "were timetabled with the minimum allowable number of classes. What was the "
           "total number of classes run for the two subjects?",
           ["11", "4", "5", "10"], 0,
           "Biology: 115 ÷ 25 = 4.6 → 5 classes. General Maths: 135 ÷ 25 = 5.4 → "
           "6 classes. Total = 11.", difficulty=2),
    ],
})

# ── Selective + Quantitative: rates and speed ──
NEW_TOPICS.append({
    "slug": "rates_and_speed",
    "strand": "Number",
    "topic": "Rates and Speed",
    "questions": [
        mc("Andrew rode his bike for 3 1/2 hours and covered 126 km. "
           "What was his average speed in km/h?",
           ["36 km/h", "44.1 km/h", "41.5 km/h", "40 km/h"], 0,
           "Speed = distance ÷ time = 126 ÷ 3.5 = 36 km/h.", difficulty=1),
        mc("A runner completes a 5 km run. For the first 2 km the runner has an average "
           "speed of 10 km/h; for the last 3 km the average speed is 8 km/h. "
           "How long does the runner take to complete the run?",
           ["34 min 30 s", "30 min", "33 min", "37 min 30 s"], 0,
           "First 2 km: 2/10 h = 12 min. Last 3 km: 3/8 h = 22.5 min. "
           "Total = 34.5 min = 34 min 30 s.", difficulty=3),
        mc("Pace (min/km) can be calculated from speed: 10 km/h is a pace of 6 min/km. "
           "A runner is running at a speed of 12 km/h. What is the equivalent pace?",
           ["5.0 min/km", "4.5 min/km", "5.5 min/km", "9.0 min/km"], 0,
           "60 minutes ÷ 12 km = 5.0 min/km.", difficulty=2),
    ],
})

# ── Selective + Quantitative: probability ──
NEW_TOPICS.append({
    "slug": "probability",
    "strand": "Statistics and Probability",
    "topic": "Probability",
    "questions": [
        mc("Two dice are thrown. What is the probability, in lowest terms, of the two "
           "numbers adding up to ten?",
           ["1/12", "1/9", "1/6", "5/36"], 0,
           "The combinations are (4,6), (5,5) and (6,4): 3 out of 36 = 1/12.",
           difficulty=2),
        mc("Two traffic lights, A and B, are on a stretch of road. When light A is red, "
           "light B is green 90% of the time. When light A is green, light B is green "
           "70% of the time. Light A is equally likely to be green or red. What is the "
           "chance of light B being green?",
           ["80%", "50%", "70%", "90%"], 0,
           "0.5 × 90% + 0.5 × 70% = 45% + 35% = 80%.", difficulty=3),
        mc("In a charity game, players roll a die and select a card from a deck. For "
           "every player who rolls an odd number (chance 1/2) and then selects a face "
           "card (chance 3/13), $3 is given to a wildlife shelter. 260 people play. "
           "What is the best estimate of the amount given to the wildlife shelter?",
           ["$90", "$130", "$180", "$210"], 0,
           "Expected winners = 260 × 1/2 × 3/13 = 30. Amount = 30 × $3 = $90.",
           difficulty=3),
    ],
})

# ── Selective + Quantitative: data and statistics ──
NEW_TOPICS.append({
    "slug": "data_and_statistics",
    "strand": "Statistics and Probability",
    "topic": "Data and Statistics",
    "questions": [
        mc("A child's scores for her spelling tests were 7, 1, 2, 5, 2, 3 and 9. "
           "What is the median of these numbers?",
           ["3", "2", "4.14", "5"], 0,
           "Ordered: 1, 2, 2, 3, 5, 7, 9. The middle (4th) value is 3. "
           "(4.14 is the mean, not the median.)", difficulty=1),
        mc("A study recorded the performance of premiers in the last four matches of "
           "each regular season: 56 wins, 15 losses and 1 draw in total. How many past "
           "seasons of competition are included?",
           ["18", "14", "16", "17"], 0,
           "Total matches = 56 + 15 + 1 = 72. Each season contributes 4 matches: "
           "72 ÷ 4 = 18 seasons.", difficulty=2),
        mc("In a golf competition, five golfers scored 76, 74, 85, 72 and 73 at Course X "
           "and 69, 72, 76, 74 and 74 at Course Y. The organisers want to adjust each "
           "golfer's Course Y score so the five adjusted scores have the same mean as "
           "the Course X scores. Which change is needed?",
           ["Increase each golfer's result for Course Y by 3",
            "Decrease each golfer's result for Course Y by 2",
            "Increase each golfer's result for Course Y by 2",
            "Decrease each golfer's result for Course Y by 3"], 0,
           "Course X mean = 380/5 = 76. Course Y mean = 365/5 = 73. "
           "Each Y score must increase by 3.", difficulty=2),
        mc("At a school, Year 11 students had these Unit 3 and 4 enrolments: 77 in "
           "Biology, 61 in General Mathematics and 29 in other subjects (167 enrolments "
           "in total). Students who chose two subjects studied both Biology and General "
           "Mathematics, no one studied more than two, and 16 students studied both. "
           "How many Year 11 students studied at least one Unit 3 and 4 subject?",
           ["151", "122", "138", "167"], 0,
           "167 enrolments count the 16 double-subject students twice: "
           "167 − 16 = 151 students.", difficulty=3),
    ],
})

# ── Quantitative: measurement ──
NEW_TOPICS.append({
    "slug": "measurement",
    "strand": "Geometry",
    "topic": "Measurement",
    "questions": [
        mc("On a flight, Remi may take up to 23 kg of checked luggage and 7 kg of "
           "carry-on luggage. Her suitcase is 1.7 kg when empty and her carry-on bag is "
           "600 g when empty. What is the total maximum, in kilograms, that Remi is "
           "allowed to pack inside her suitcase and carry-on bag?",
           ["27.70 kg", "28.24 kg", "28.30 kg", "30.00 kg"], 0,
           "Suitcase: 23 − 1.7 = 21.3 kg. Carry-on: 7 − 0.6 = 6.4 kg. "
           "Total = 27.7 kg.", difficulty=2),
        mc("One bag of concrete pre-mix makes 0.01 m³ of concrete. A rectangular frame "
           "0.1 m deep with side lengths of 2 m and 3 m is filled to the top. "
           "How many bags of pre-mix are needed?",
           ["60", "3", "12", "20"], 0,
           "Volume = 2 × 3 × 0.1 = 0.6 m³. Bags = 0.6 ÷ 0.01 = 60.", difficulty=2),
        mc("A parcel company defines girth = 2 × (width + height), using the two "
           "shortest sides, and allows a maximum girth of 140 cm. Four model boxes are "
           "all 25 cm high: treehouse 20 cm wide × 60 cm long; car 35 cm × 70 cm; "
           "jet 45 cm × 60 cm; ferris wheel 55 cm × 55 cm. "
           "Which models are allowed to be delivered?",
           ["jet, car and treehouse only", "treehouse only", "car and treehouse only",
            "ferris wheel, jet, car and treehouse"], 0,
           "Girths: treehouse 2(20+25) = 90, car 2(35+25) = 120, jet 2(45+25) = 140 "
           "(exactly the maximum, so allowed), ferris wheel 2(55+25) = 160 — too big.",
           difficulty=3),
    ],
})

# ── Pythagoras pack + Selective: Pythagoras' theorem ──
NEW_TOPICS.append({
    "slug": "pythagoras_theorem",
    "strand": "Geometry",
    "topic": "Pythagoras' Theorem",
    "questions": [
        mc("A right-angled triangle has legs of 8 cm and 6 cm. "
           "What is the length of the hypotenuse?",
           ["10 cm", "14 cm", "5.3 cm", "100 cm"], 0,
           "x² = 8² + 6² = 64 + 36 = 100, so x = 10 cm.", difficulty=1),
        mc("What is the length of the hypotenuse of a right-angled triangle with legs "
           "of 15 cm and 6 cm? Give your answer to 1 decimal place.",
           ["16.2 cm", "13.7 cm", "21 cm", "261 cm"], 0,
           "h² = 15² + 6² = 225 + 36 = 261, so h = √261 ≈ 16.2 cm.", difficulty=2),
        mc("Find the length of the hypotenuse PQ of a right-angled triangle whose legs "
           "are 11 m and 15 m, to 2 decimal places.",
           ["18.60 m", "10.20 m", "26.00 m", "18.36 m"], 0,
           "PQ² = 11² + 15² = 121 + 225 = 346, so PQ = √346 ≈ 18.60 m.", difficulty=2),
        mc("A right-angled triangle has a hypotenuse of 34 cm and one other side of "
           "30 cm. Find the length of the third side, BC.",
           ["16 cm", "45.3 cm", "64 cm", "4 cm"], 0,
           "BC² = 34² − 30² = 1156 − 900 = 256, so BC = 16 cm. "
           "Subtract, don't add, when finding a shorter side.", difficulty=2),
        mc("A right-angled triangle has a hypotenuse of 10 cm and one leg of 8 cm. "
           "Find the length of the missing side.",
           ["6 cm", "12.8 cm", "2 cm", "18 cm"], 0,
           "a² = 10² − 8² = 100 − 64 = 36, so a = 6 cm.", difficulty=1),
        mc("Find the length of the hypotenuse of a right-angled triangle with legs "
           "7.5 m and 9 m, to 1 decimal place.",
           ["11.7 m", "5.0 m", "16.5 m", "11.6 m"], 0,
           "a² = 7.5² + 9² = 56.25 + 81 = 137.25, so a = √137.25 ≈ 11.7 m.", difficulty=2),
        mc("A right-angled triangle has a hypotenuse of 12 m and one leg of 5 m. "
           "Find the other leg, leaving your answer as a surd.",
           ["√119 m", "√169 m", "√7 m", "√60 m"], 0,
           "x² = 12² − 5² = 144 − 25 = 119, so x = √119 m.", difficulty=2),
        mc("What is the length of the diagonal of a square with side length 18 cm? "
           "(1 decimal place)",
           ["25.5 cm", "12.7 cm", "36 cm", "324 cm"], 0,
           "d² = 18² + 18² = 648, so d = √648 ≈ 25.5 cm.", difficulty=2),
        mc("Find the side length of a square with a 72 cm diagonal, to 1 decimal place.",
           ["50.9 cm", "101.8 cm", "36 cm", "8.5 cm"], 0,
           "2x² = 72² = 5184, so x² = 2592 and x = √2592 ≈ 50.9 cm.", difficulty=3),
        mc("Find the length of the diagonal of a rectangle measuring 12.2 m by 7.1 m, "
           "to 1 decimal place.",
           ["14.1 m", "19.3 m", "9.9 m", "14.5 m"], 0,
           "d² = 12.2² + 7.1² = 148.84 + 50.41 = 199.25, so d ≈ 14.1 m.", difficulty=2),
        mc("Christiana walks diagonally from corner to corner in a rectangular field "
           "56 m wide and 212 m long. How far does she walk, to 1 decimal place?",
           ["219.3 m", "268 m", "204.5 m", "156 m"], 0,
           "d² = 56² + 212² = 3136 + 44944 = 48080, so d = √48080 ≈ 219.3 m.",
           difficulty=2),
        mc("How tall is a flag pole if it is anchored 2.2 m from its base with a 9 m "
           "support wire? Correct to one decimal place.",
           ["8.7 m", "9.3 m", "6.8 m", "11.2 m"], 0,
           "h² = 9² − 2.2² = 81 − 4.84 = 76.16, so h = √76.16 ≈ 8.7 m.", difficulty=2),
        mc("Find the height of an isosceles triangle with equal sides of 25 cm and a "
           "base of 22 cm. Correct to one decimal place.",
           ["22.4 cm", "27.3 cm", "11.2 cm", "14.7 cm"], 0,
           "The height splits the base into 11 cm halves: h² = 25² − 11² = 504, "
           "so h = √504 ≈ 22.4 cm.", difficulty=3),
        mc("A ladder leans against a window of a house. If the ladder is 25 m long and "
           "the base of the ladder is 7 m from the base of the house, how high is the "
           "window?",
           ["24 m", "26 m", "18 m", "32 m"], 0,
           "h² = 25² − 7² = 625 − 49 = 576, so h = 24 m.", difficulty=2),
        mc("Two joggers run 8 km north and then 5 km west. What is the shortest "
           "distance, to the nearest tenth of a km, they must travel to return to their "
           "starting point?",
           ["9.4 km", "13 km", "6.2 km", "3 km"], 0,
           "d² = 8² + 5² = 89, so d = √89 ≈ 9.4 km.", difficulty=2),
        mc("A yacht sails 8.1 km north then travels a further distance west. The yacht "
           "is now 12.2 km from its starting point. How far did the yacht travel west? "
           "Correct to 1 decimal place.",
           ["9.1 km", "14.6 km", "4.1 km", "20.3 km"], 0,
           "w² = 12.2² − 8.1² = 148.84 − 65.61 = 83.23, so w = √83.23 ≈ 9.1 km.",
           difficulty=2),
        mc("Do the numbers 8, 13, 17 form a Pythagorean triple?",
           ["No, because 8² + 13² ≠ 17²", "Yes, because 8² + 13² = 17²",
            "Yes, because 8 + 13 > 17", "No, because 8 + 13 ≠ 17"], 0,
           "8² + 13² = 64 + 169 = 233, but 17² = 289. They are not equal, "
           "so it is not a Pythagorean triple.", difficulty=2),
        mc("Is the triangle with sides 6, 9 and 11 right-angled?",
           ["No, because 6² + 9² ≠ 11²", "Yes, because 6² + 9² = 11²",
            "Yes, because 6 + 9 > 11", "No, because 6 + 9 ≠ 11"], 0,
           "6² + 9² = 36 + 81 = 117, but 11² = 121, so the triangle is not "
           "right-angled.", difficulty=2),
        mc("Find the length of the space diagonal of a cube with side length 10 cm "
           "(the diagonal from one corner, through the inside, to the opposite corner), "
           "to 1 decimal place.",
           ["17.3 cm", "14.1 cm", "20 cm", "30 cm"], 0,
           "Face diagonal² = 10² + 10² = 200. Space diagonal² = 200 + 10² = 300, "
           "so the diagonal = √300 ≈ 17.3 cm. (14.1 cm is only the face diagonal.)",
           difficulty=3),
        mc("Pyramid ABCDE has a square base and is 20 cm high. Each sloping edge "
           "measures 30 cm. Calculate the length of the sides of the base, "
           "to 1 decimal place.",
           ["31.6 cm", "22.4 cm", "44.7 cm", "50 cm"], 0,
           "Half-diagonal² = 30² − 20² = 500, so the half-diagonal ≈ 22.36 cm and the "
           "full diagonal ≈ 44.72 cm. The side = 44.72 ÷ √2 ≈ 31.6 cm.", difficulty=3),
        mc("The sloping side of a cone is 10 cm and the height is 8 cm. "
           "What is the length of the radius of the base?",
           ["6 cm", "12.8 cm", "2 cm", "36 cm"], 0,
           "r² = 10² − 8² = 36, so r = 6 cm.", difficulty=2),
        mc("What is the radius of a cone whose slant side is 22 cm and whose height is "
           "18 cm? (1 decimal place)",
           ["12.6 cm", "28.4 cm", "4 cm", "160 cm"], 0,
           "r² = 22² − 18² = 484 − 324 = 160, so r = √160 ≈ 12.6 cm.", difficulty=2),
        mc("Find the area of an equilateral triangle with sides of 4 cm, "
           "to 2 decimal places.",
           ["6.93 cm²", "8 cm²", "13.86 cm²", "4 cm²"], 0,
           "Height² = 4² − 2² = 12, so h = √12 ≈ 3.464 cm. "
           "Area = ½ × 4 × 3.464 ≈ 6.93 cm².", difficulty=3),
        mc("Sarah can reach Charlie by jogging along two pathways that meet at a right "
           "angle — 1 km along the first and 2 km along the second — or by running "
           "directly. How much shorter is running directly, to 2 decimal places?",
           ["0.76 km", "2.24 km", "1.00 km", "0.24 km"], 0,
           "Direct distance = √(1² + 2²) = √5 ≈ 2.24 km. The pathway is 3 km, "
           "so the direct route is 3 − 2.24 = 0.76 km shorter.", difficulty=3),
        mc("A rectangular park measures 240 m by 150 m. Calculate the length of the "
           "diagonal of the park, to 2 decimal places.",
           ["283.02 m", "390 m", "187.35 m", "195 m"], 0,
           "d² = 240² + 150² = 57600 + 22500 = 80100, so d = √80100 ≈ 283.02 m.",
           difficulty=2),
        mc("A 10 m high flagpole stands in the corner of a rectangular park. Point A is "
           "at the other end of the park's 240 m side. Calculate the distance from A to "
           "the top of the flagpole, to 1 decimal place.",
           ["240.2 m", "250.0 m", "240.0 m", "232.1 m"], 0,
           "d² = 240² + 10² = 57700, so d = √57700 ≈ 240.2 m.", difficulty=3),
        mc("A right-angled triangle has legs of length x + 2 and x + 4, and a "
           "hypotenuse of length x + 6. Find the value of x.",
           ["4", "2", "3", "5"], 0,
           "(x + 2)² + (x + 4)² = (x + 6)²: x² + 4x + 4 + x² + 8x + 16 = x² + 12x + 36, "
           "so x² = 16 and x = 4.", difficulty=3),
    ],
})

# ── Selective: trigonometry ──
NEW_TOPICS.append({
    "slug": "trigonometry",
    "strand": "Geometry",
    "topic": "Trigonometry",
    "questions": [
        mc("From a hot air balloon, the marked landing site is measured at 10° down "
           "from the horizontal (angle of depression). If the hot air balloon's basket "
           "is 96 m above the ground, how far horizontally (x) does the balloon need to "
           "travel to reach the landing site?",
           ["x = 96/tan 10°", "x = 96 tan 10°", "x = 96/cos 10°", "x = 96/sin 10°"], 0,
           "tan 10° = opposite/adjacent = 96/x, so x = 96/tan 10°.", difficulty=3),
        mc("A right-angled triangle has legs of 5 and 12 and a hypotenuse of 13. "
           "The angle θ is between the side of length 5 and the hypotenuse. cos θ =",
           ["5/13", "13/5", "12/5", "12/13"], 0,
           "cos θ = adjacent/hypotenuse = 5/13.", difficulty=2),
    ],
})

# ── batch-2 data end ──


def _opt_value(text):
    """Try to reduce an option text to an exact numeric value for the
    mathematically-equal check. Returns None for non-numeric options."""
    s = text.strip().replace("−", "-").replace("$", "").replace("%", "")
    s = s.replace(",", "").replace(" ", " ")
    for unit in (" cm²", " cm", " m²", " m", " km", " kg", " g", " mL", " L",
                 " GL", " min/km", "km/hr", " IDR", " h", " min", " s",
                 " hours", " hour"):
        if s.endswith(unit):
            s = s[: -len(unit)].strip()
    s = s.replace(" ", "")
    try:
        return _F(s)
    except (ValueError, ZeroDivisionError):
        return None


def _validate(topic, q):
    opts = [a["text"] for a in q["answers"]]
    correct = [a for a in q["answers"] if a["is_correct"]]
    assert len(correct) == 1, f"{topic}: not exactly 1 correct: {q['question_text']!r}"
    assert len(opts) >= 2, f"{topic}: needs 2+ options: {q['question_text']!r}"
    assert len(set(opts)) == len(opts), f"{topic}: duplicate option text: {opts}"
    vals = [_opt_value(o) for o in opts]
    nums = [v for v in vals if v is not None]
    assert len(nums) == len(set(nums)), (
        f"{topic}: mathematically equal options {opts} in {q['question_text']!r}")


def main():
    for t in TOPICS:
        t["questions"].extend(EXTRA_QUESTIONS.pop(t["slug"], []))
    assert not EXTRA_QUESTIONS, f"unmatched extension slugs: {list(EXTRA_QUESTIONS)}"
    TOPICS.extend(NEW_TOPICS)
    for t in TOPICS:
        for q in t["questions"]:
            _validate(t["topic"], q)

    manifest = []
    for t in TOPICS:
        data = {
            "subject": "maths",
            "strand": t["strand"],
            "topic": t["topic"],
            "year_level": YEAR,
            "questions": t["questions"],
        }
        payload = json.dumps(data, indent=2, ensure_ascii=False)

        json_path = os.path.join(HERE, f"{t['slug']}_year{YEAR}.json")
        with open(json_path, "w", encoding="utf-8") as fh:
            fh.write(payload + "\n")

        zip_path = os.path.join(HERE, f"{t['slug']}_year{YEAR}.zip")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("questions.json", payload)

        manifest.append((t["topic"], len(t["questions"]),
                         os.path.basename(json_path), os.path.basename(zip_path)))

    print(f"{'TOPIC':<34}{'Qs':<5}{'JSON':<40}ZIP")
    total = 0
    for topic, n, jp, zp in manifest:
        total += n
        print(f"{topic:<34}{n:<5}{jp:<40}{zp}")
    print(f"\nTotal: {len(manifest)} topics, {total} questions")


if __name__ == "__main__":
    main()
