"""
fix_unsimplified_fraction_answers.py
-------------------------------------
One-off script: swap correct answers that are unsimplified fractions
(e.g. 2/4, 3/6, 4/8) to their simplified equivalents (1/2, 1/3)
when the simplified form already exists as another answer option.

Usage (run from the project root where manage.py lives):
    python fix_unsimplified_fraction_answers.py [--dry-run]

Add --dry-run to preview changes without writing to the database.
"""

import os
import sys
import re
import django
from fractions import Fraction

# ── Bootstrap Django ──────────────────────────────────────────────────────────
# Adjust this path if manage.py is in a subdirectory.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
django.setup()
# ─────────────────────────────────────────────────────────────────────────────

from maths.models import Question, Answer  # noqa: E402

DRY_RUN = '--dry-run' in sys.argv


def parse_fraction(text):
    """Return a Fraction if text is strictly 'n/d', else None."""
    m = re.match(r'^\s*(\d+)/(\d+)\s*$', text)
    if m:
        return Fraction(int(m.group(1)), int(m.group(2)))
    return None


def run():
    fixed = 0
    skipped = 0

    questions = Question.objects.prefetch_related('answers').iterator(chunk_size=500)

    for q in questions:
        answers = list(q.answers.all())
        correct_list = [a for a in answers if a.is_correct]
        if not correct_list:
            continue

        correct_ans = correct_list[0]
        f_correct = parse_fraction(correct_ans.answer_text)
        if f_correct is None:
            continue

        # Fraction() auto-simplifies: Fraction(2, 4) → Fraction(1, 2)
        simplified = Fraction(f_correct.numerator, f_correct.denominator)
        if str(simplified) == correct_ans.answer_text.strip():
            # Already in simplest form — nothing to do
            continue

        # Look for the simplified form as a (currently wrong) option
        target = None
        for a in answers:
            f_other = parse_fraction(a.answer_text)
            if f_other and f_other == simplified and not a.is_correct:
                target = a
                break

        if target is None:
            skipped += 1
            continue

        print(
            f'  Q{q.id}: "{q.question_text[:60]}"'
            f'\n    current correct: "{correct_ans.answer_text.strip()}"'
            f'  →  new correct: "{target.answer_text.strip()}"'
        )

        if not DRY_RUN:
            correct_ans.is_correct = False
            correct_ans.save(update_fields=['is_correct'])
            target.is_correct = True
            target.save(update_fields=['is_correct'])

        fixed += 1

    mode = '[DRY RUN] ' if DRY_RUN else ''
    print(f'\n{mode}Done — {fixed} question(s) fixed, {skipped} skipped '
          f'(unsimplified correct with no simplified alternative).')


if __name__ == '__main__':
    print(f'{"[DRY RUN] " if DRY_RUN else ""}Scanning questions for unsimplified fraction answers...\n')
    run()
