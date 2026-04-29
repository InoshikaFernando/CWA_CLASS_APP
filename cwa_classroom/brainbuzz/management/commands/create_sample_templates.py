"""Generate sample question upload template files (JSON, CSV, Excel)."""

import json
import csv
import os

from django.core.management.base import BaseCommand

SAMPLES_DIR = os.path.join(os.path.dirname(__file__), 'samples')

SAMPLE_QUESTIONS = [
    {
        "topic": "Fractions", "level": 5,
        "question_text": "What is 1/2 + 1/4?",
        "question_type": "multiple_choice", "difficulty": 2, "points": 1,
        "explanation": "To add fractions, find a common denominator. 1/2 = 2/4, so 2/4 + 1/4 = 3/4.",
        "correct_short_answer": "",
        "answers": [
            {"text": "3/4", "is_correct": True, "order": 0},
            {"text": "2/6", "is_correct": False, "order": 1},
            {"text": "1/8", "is_correct": False, "order": 2},
            {"text": "2/4", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "Fractions", "level": 5,
        "question_text": "Is 3/6 equivalent to 1/2?",
        "question_type": "true_false", "difficulty": 1, "points": 1,
        "explanation": "3/6 simplifies to 1/2 by dividing numerator and denominator by 3.",
        "correct_short_answer": "",
        "answers": [
            {"text": "True", "is_correct": True, "order": 0},
            {"text": "False", "is_correct": False, "order": 1},
        ],
    },
    {
        "topic": "Fractions", "level": 6,
        "question_text": "Simplify the fraction 12/16 to its lowest terms.",
        "question_type": "short_answer", "difficulty": 2, "points": 2,
        "explanation": "The GCF of 12 and 16 is 4. Dividing both by 4 gives 3/4.",
        "correct_short_answer": "3/4",
        "answers": [],
    },
    {
        "topic": "Arithmetic", "level": 3,
        "question_text": "What is 7 × 8?",
        "question_type": "multiple_choice", "difficulty": 1, "points": 1,
        "explanation": "7 × 8 = 56.",
        "correct_short_answer": "",
        "answers": [
            {"text": "54", "is_correct": False, "order": 0},
            {"text": "56", "is_correct": True, "order": 1},
            {"text": "58", "is_correct": False, "order": 2},
            {"text": "64", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "Arithmetic", "level": 3,
        "question_text": "Division is the inverse (opposite) of multiplication.",
        "question_type": "true_false", "difficulty": 1, "points": 1,
        "explanation": "If a × b = c then c ÷ b = a.",
        "correct_short_answer": "",
        "answers": [
            {"text": "True", "is_correct": True, "order": 0},
            {"text": "False", "is_correct": False, "order": 1},
        ],
    },
    {
        "topic": "Arithmetic", "level": 5,
        "question_text": "Round 4,672 to the nearest hundred.",
        "question_type": "multiple_choice", "difficulty": 2, "points": 1,
        "explanation": "Look at the tens digit (7). Since 7 ≥ 5, round up. 4,672 → 4,700.",
        "correct_short_answer": "",
        "answers": [
            {"text": "4,600", "is_correct": False, "order": 0},
            {"text": "4,700", "is_correct": True, "order": 1},
            {"text": "4,000", "is_correct": False, "order": 2},
            {"text": "5,000", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "BODMAS", "level": 7,
        "question_text": "Evaluate: 3 + 4 × 2 − 1",
        "question_type": "multiple_choice", "difficulty": 2, "points": 1,
        "explanation": "BODMAS: multiplication first → 4 × 2 = 8, then 3 + 8 − 1 = 10.",
        "correct_short_answer": "",
        "answers": [
            {"text": "10", "is_correct": True, "order": 0},
            {"text": "13", "is_correct": False, "order": 1},
            {"text": "14", "is_correct": False, "order": 2},
            {"text": "9", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "Algebra", "level": 7,
        "question_text": "Solve for x: 2x + 5 = 13",
        "question_type": "short_answer", "difficulty": 2, "points": 2,
        "explanation": "Subtract 5 from both sides: 2x = 8. Divide by 2: x = 4.",
        "correct_short_answer": "4",
        "answers": [],
    },
    {
        "topic": "Algebra", "level": 8,
        "question_text": "Which of the following is equivalent to 3(x + 4)?",
        "question_type": "multiple_choice", "difficulty": 2, "points": 1,
        "explanation": "Distribute: 3(x + 4) = 3x + 12.",
        "correct_short_answer": "",
        "answers": [
            {"text": "3x + 12", "is_correct": True, "order": 0},
            {"text": "3x + 4", "is_correct": False, "order": 1},
            {"text": "x + 12", "is_correct": False, "order": 2},
            {"text": "3x + 7", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "Addition", "level": 1,
        "question_text": "What is 5 + 3?",
        "question_type": "multiple_choice", "difficulty": 1, "points": 1,
        "explanation": "Count on from 5: 6, 7, 8. So 5 + 3 = 8.",
        "correct_short_answer": "",
        "answers": [
            {"text": "7", "is_correct": False, "order": 0},
            {"text": "8", "is_correct": True, "order": 1},
            {"text": "9", "is_correct": False, "order": 2},
            {"text": "6", "is_correct": False, "order": 3},
        ],
    },
    {
        "topic": "Addition", "level": 2,
        "question_text": "Fill in the blank: 14 + ___ = 20",
        "question_type": "fill_blank", "difficulty": 1, "points": 1,
        "explanation": "20 − 14 = 6. So the missing number is 6.",
        "correct_short_answer": "6",
        "answers": [],
    },
]


def _build_json_payload():
    questions = []
    for q in SAMPLE_QUESTIONS:
        entry = {
            "topic": q["topic"],
            "level": q["level"],
            "question_text": q["question_text"],
            "question_type": q["question_type"],
            "difficulty": q["difficulty"],
            "points": q["points"],
            "explanation": q["explanation"],
        }
        if q["correct_short_answer"]:
            entry["correct_short_answer"] = q["correct_short_answer"]
        if q["answers"]:
            entry["answers"] = q["answers"]
        questions.append(entry)
    return {"subject": "maths", "questions": questions}


def _build_csv_rows():
    max_answers = max(len(q["answers"]) for q in SAMPLE_QUESTIONS)
    answer_cols = []
    for i in range(1, max_answers + 1):
        answer_cols += [f"answer{i}", f"is_correct{i}"]

    headers = [
        "topic", "level", "question_text", "question_type",
        "difficulty", "points", "explanation", "correct_short_answer",
    ] + answer_cols

    rows = []
    for q in SAMPLE_QUESTIONS:
        row = {
            "topic": q["topic"],
            "level": q["level"],
            "question_text": q["question_text"],
            "question_type": q["question_type"],
            "difficulty": q["difficulty"],
            "points": q["points"],
            "explanation": q["explanation"],
            "correct_short_answer": q["correct_short_answer"],
        }
        for i, ans in enumerate(q["answers"], start=1):
            row[f"answer{i}"] = ans["text"]
            row[f"is_correct{i}"] = "true" if ans["is_correct"] else "false"
        rows.append(row)

    return headers, rows


class Command(BaseCommand):
    help = "Generate sample question upload templates (JSON, CSV, Excel) in management/commands/samples/"

    def handle(self, *args, **options):
        os.makedirs(SAMPLES_DIR, exist_ok=True)

        self._write_json()
        self._write_csv()
        self._write_excel()

        self.stdout.write(self.style.SUCCESS(f"Sample templates written to {SAMPLES_DIR}"))

    def _write_json(self):
        path = os.path.join(SAMPLES_DIR, "sample_maths_questions.json")
        payload = _build_json_payload()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        self.stdout.write(f"  JSON: {path}")

    def _write_csv(self):
        path = os.path.join(SAMPLES_DIR, "sample_maths_questions.csv")
        headers, rows = _build_csv_rows()
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(f"  CSV: {path}")

    def _write_excel(self):
        try:
            import openpyxl
            from openpyxl.styles import Font, PatternFill, Alignment
        except ImportError:
            self.stderr.write("openpyxl not installed — skipping Excel template")
            return

        path = os.path.join(SAMPLES_DIR, "sample_maths_questions.xlsx")
        headers, rows = _build_csv_rows()

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Questions"

        header_font = Font(bold=True, color="FFFFFF")
        header_fill = PatternFill(fill_type="solid", fgColor="2E4057")
        header_align = Alignment(horizontal="center", wrap_text=True)

        for col_idx, header in enumerate(headers, start=1):
            cell = ws.cell(row=1, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = header_align

        alt_fill = PatternFill(fill_type="solid", fgColor="EAF0FB")
        for row_idx, row in enumerate(rows, start=2):
            for col_idx, header in enumerate(headers, start=1):
                cell = ws.cell(row=row_idx, column=col_idx, value=row.get(header, ""))
                cell.alignment = Alignment(wrap_text=True)
                if row_idx % 2 == 0:
                    cell.fill = alt_fill

        ws.freeze_panes = "A2"

        for col_idx, header in enumerate(headers, start=1):
            ws.column_dimensions[
                openpyxl.utils.get_column_letter(col_idx)
            ].width = 20

        ws.column_dimensions["C"].width = 50
        ws.column_dimensions["G"].width = 40

        wb.save(path)
        self.stdout.write(f"  Excel: {path}")
