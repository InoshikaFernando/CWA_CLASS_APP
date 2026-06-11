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


def main():
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
