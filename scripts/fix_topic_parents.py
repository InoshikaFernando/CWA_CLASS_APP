"""
fix_topic_parents.py
--------------------
Fixes orphaned / duplicate topics:

  1. Rename BODMAS/PEMDAS (id=76) -> "BODMAS"

  2. Merge duplicate BODMAS (id=97, 36 questions) into id=76 (144 questions)
     and delete id=97.

  3. BODMAS (id=76) -> parent = Algebra (id=1)

  4. Multiplication / Division subtable variants that are currently
     top-level orphans -> parent = Multiplication (id=71) or Division (id=72)

     Multiplication subtables:  85, 86, 87, 88, 89, 90, 91, 92, 96
     Division subtables:        93, 94, 95

Usage:
    python fix_topic_parents.py [--dry-run]
"""

import os, sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
import django; django.setup()

from classroom.models import Topic   # Topic lives in classroom app
from maths.models import Question
from django.db import transaction

DRY_RUN = '--dry-run' in sys.argv

RENAMES = [
    # (topic_id, new_name)
    (76, 'BODMAS'),   # was "BODMAS/PEMDAS"
]

CHANGES = [
    # (topic_id, new_parent_id, reason)
    (76, 1,  'BODMAS -> Algebra'),

    # Multiplication subtables -> Multiplication (71)
    (85, 71, 'Multiplication (1x) -> Multiplication'),
    (86, 71, 'Multiplication (2x) -> Multiplication'),
    (87, 71, 'Multiplication (11x) -> Multiplication'),
    (88, 71, 'Multiplication (12x) -> Multiplication'),
    (89, 71, 'Multiplication (5x) -> Multiplication'),
    (90, 71, 'Multiplication (10x) -> Multiplication'),
    (91, 71, 'Multiplication (3x) -> Multiplication'),
    (92, 71, 'Multiplication (4x) -> Multiplication'),
    (96, 71, 'Multiplication (6x) -> Multiplication'),

    # Division subtables -> Division (72)
    (93, 72, 'Division (2x) -> Division'),
    (94, 72, 'Division (11x) -> Division'),
    (95, 72, 'Division (10x) -> Division'),
]


def run():
    # ── Step 0: merge duplicate BODMAS (id=97 -> id=76) ─────────────────────
    try:
        keep = Topic.objects.get(id=76)
        dupe = Topic.objects.get(id=97)
        dupe_q = Question.objects.filter(topic=dupe).count()
        print(f'  MERGE id=97 "{dupe.name}" ({dupe_q} questions) -> id=76 "{keep.name}"')
        if not DRY_RUN:
            with transaction.atomic():
                Question.objects.filter(topic=dupe).update(topic=keep)
                # Fix any homework M2M references
                from homework.models import Homework
                for hw in Homework.objects.filter(topics=dupe):
                    hw.topics.remove(dupe)
                    hw.topics.add(keep)
                dupe.delete()
        print(f'  OK   id=76 now has {Question.objects.filter(topic=keep).count()} questions')
    except Topic.DoesNotExist:
        print('  OK   duplicate BODMAS (id=97) already gone — skipping merge')

    # ── Step 1: renames ──────────────────────────────────────────────────────
    for topic_id, new_name in RENAMES:
        try:
            t = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            print(f'  SKIP rename id={topic_id} — not found')
            continue
        if t.name == new_name:
            print(f'  OK   id={topic_id} already named "{new_name}"')
            continue
        print(f'  RENAME id={topic_id} "{t.name}" -> "{new_name}"')
        if not DRY_RUN:
            t.name = new_name
            t.save(update_fields=['name'])

    # ── Step 2: parent assignments ───────────────────────────────────────────
    updated = 0
    for topic_id, new_parent_id, reason in CHANGES:
        try:
            t = Topic.objects.get(id=topic_id)
        except Topic.DoesNotExist:
            print(f'  SKIP id={topic_id} — not found')
            continue

        try:
            parent = Topic.objects.get(id=new_parent_id)
        except Topic.DoesNotExist:
            print(f'  SKIP id={topic_id} — parent id={new_parent_id} not found')
            continue

        if t.parent_id == new_parent_id:
            print(f'  OK   id={topic_id} "{t.name}" already under "{parent.name}"')
            continue

        print(f'  FIX  id={topic_id} "{t.name}" — {reason}')
        if not DRY_RUN:
            t.parent = parent
            t.save(update_fields=['parent'])
        updated += 1

    mode = '[DRY RUN] ' if DRY_RUN else ''
    print(f'\n{mode}Done — {updated} topic(s) updated.')


if __name__ == '__main__':
    print(f'{"[DRY RUN] " if DRY_RUN else ""}Fixing orphaned topic parents...\n')
    run()
