"""
seed_times_tables.py
--------------------
Creates missing Multiplication and Division times-table topics and seeds
their questions into the database, matching the format of existing ones.

What it creates
---------------
Multiplication topics (parent = id 71 "Multiplication" under Number):
  7×, 8×, 9×   — 12 questions each (n × 1 … n × 12)

Division topics (parent = id 72 "Division" under Number):
  3÷, 4÷, 5÷, 6÷, 7÷, 8÷, 9÷, 12÷  — 12 questions each (n × m ÷ n = ?)

Each question has 4 answer options: 1 correct + 3 plausible wrong answers
(neighbours of the correct value, no negatives, no duplicates).

Level: Year 4 (level_id = 4), matching existing times-table questions.

Usage:
    python seed_times_tables.py [--dry-run]
"""

import os, sys, random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
import django; django.setup()

from django.db import transaction
from maths.models import Question, Answer
from classroom.models import Topic, Level

DRY_RUN = '--dry-run' in sys.argv

# ── Config ────────────────────────────────────────────────────────────────────
MULT_PARENT_ID = 71   # "Multiplication" under Number
DIV_PARENT_ID  = 72   # "Division" under Number
LEVEL_ID       = 4    # Year 4
TABLES_RANGE   = list(range(1, 13))   # 1 through 12

MISSING_MULT = [7, 8, 9]
MISSING_DIV  = [3, 4, 5, 6, 7, 8, 9, 12]
# ─────────────────────────────────────────────────────────────────────────────


def wrong_answers(correct: int, count: int = 3) -> list[str]:
    """Return `count` plausible wrong integer answers near `correct`."""
    candidates = []
    for delta in [1, -1, 2, -2, 3, -3, 4, -4, 5, 10, -5]:
        val = correct + delta
        if val > 0 and val != correct and str(val) not in candidates:
            candidates.append(str(val))
        if len(candidates) >= count:
            break
    # Pad with larger offsets if needed
    offset = 6
    while len(candidates) < count:
        val = correct + offset
        if str(val) not in candidates:
            candidates.append(str(val))
        offset += 1
    return candidates[:count]


def get_or_create_topic(name: str, parent_id: int, slug: str) -> tuple:
    """Return (topic, created) — idempotent. In dry-run mode, only reads, never writes."""
    parent = Topic.objects.get(id=parent_id)
    existing = Topic.objects.filter(name=name, parent=parent).first()
    if existing:
        return existing, False
    if DRY_RUN:
        # Return a mock-like unsaved topic so callers can still inspect it safely
        topic = Topic(name=name, parent=parent, subject=parent.subject,
                      slug=slug, is_active=True)
        return topic, True
    topic, created = Topic.objects.get_or_create(
        name=name,
        parent=parent,
        defaults={'is_active': True, 'subject': parent.subject, 'slug': slug},
    )
    return topic, created


def seed_multiplication(table: int, level):
    name = f"Multiplication ({table}\u00d7)"
    slug = f"multiplication-{table}"
    topic, created = get_or_create_topic(name, MULT_PARENT_ID, slug)
    status = "CREATE" if created else "EXISTS"
    topic_id = topic.id if topic.id else "(new)"
    print(f"  [{status}] {name} (id={topic_id})")

    existing_texts = set(
        Question.objects.filter(topic=topic).values_list('question_text', flat=True)
        if topic.id else []
    )
    added = 0
    for m in TABLES_RANGE:
        text = f"{table} \u00d7 {m} = ?"
        if text in existing_texts:
            continue
        correct = table * m
        wrong = wrong_answers(correct)
        if not DRY_RUN:
            with transaction.atomic():
                q = Question.objects.create(
                    topic=topic,
                    level=level,
                    question_text=text,
                    question_type='multiple_choice',
                    difficulty=1,
                    points=1,
                )
                Answer.objects.create(question=q, answer_text=str(correct), is_correct=True)
                for w in wrong:
                    Answer.objects.create(question=q, answer_text=w, is_correct=False)
        else:
            print(f"    [DRY] would add: {text} = {correct}")
        added += 1
    print(f"    Added {added} questions")
    return added


def seed_division(table: int, level):
    name = f"Division ({table}\u00d7)"
    slug = f"division-{table}"
    topic, created = get_or_create_topic(name, DIV_PARENT_ID, slug)
    status = "CREATE" if created else "EXISTS"
    topic_id = topic.id if topic.id else "(new)"
    print(f"  [{status}] {name} (id={topic_id})")

    existing_texts = set(
        Question.objects.filter(topic=topic).values_list('question_text', flat=True)
        if topic.id else []
    )
    added = 0
    for m in TABLES_RANGE:
        dividend = table * m
        text = f"{dividend} \u00f7 {table} = ?"
        if text in existing_texts:
            continue
        correct = m
        wrong = wrong_answers(correct)
        if not DRY_RUN:
            with transaction.atomic():
                q = Question.objects.create(
                    topic=topic,
                    level=level,
                    question_text=text,
                    question_type='multiple_choice',
                    difficulty=1,
                    points=1,
                )
                Answer.objects.create(question=q, answer_text=str(correct), is_correct=True)
                for w in wrong:
                    Answer.objects.create(question=q, answer_text=w, is_correct=False)
        else:
            print(f"    [DRY] would add: {text} = {correct}")
        added += 1
    print(f"    Added {added} questions")
    return added


def run():
    try:
        level = Level.objects.get(id=LEVEL_ID)
    except Level.DoesNotExist:
        print(f"ERROR: Level id={LEVEL_ID} not found. Check LEVEL_ID config.")
        sys.exit(1)

    total = 0

    print("\n=== Multiplication ===")
    for table in MISSING_MULT:
        total += seed_multiplication(table, level)

    print("\n=== Division ===")
    for table in MISSING_DIV:
        total += seed_division(table, level)

    mode = '[DRY RUN] ' if DRY_RUN else ''
    print(f"\n{mode}Done — {total} question(s) added across "
          f"{len(MISSING_MULT)} multiplication and {len(MISSING_DIV)} division topics.")


if __name__ == '__main__':
    print(f'{"[DRY RUN] " if DRY_RUN else ""}Seeding missing times-table topics and questions...')
    run()
