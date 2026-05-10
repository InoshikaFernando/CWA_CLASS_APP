"""
fix_parent_duplicates.py
------------------------
Consolidates duplicate parent records so the admin "Parents" list shows
one row per real person (linked to all their children).

Background
----------
The CSV importer used to create both:
  - Guardian + StudentGuardian (contact records), AND
  - CustomUser + ParentStudent (login-capable account records)
for every parent. The admin Parents page lists both sources, which caused
the same person to appear multiple times (one "Contact" row plus one
"Account" row per child).

This script ports any Guardian records that correspond to an existing
parent CustomUser into ParentStudent links, then deletes the redundant
Guardian (StudentGuardian cascades via FK).

Matching strategy (in order):
  1. Email exact match — Guardian.email == CustomUser.email (canonical).
  2. Name fallback — same (school, first_name, last_name) as an existing
     ParentStudent.parent user in that school. Used when Guardian.email
     has diverged from CustomUser.email (e.g. after sanitise_test_db.sh
     scrambled CustomUser emails to <id>+test@example.com but left
     classroom_guardian untouched). The fallback only fires when exactly
     one candidate user is found — ambiguous matches are skipped.

Guardians with no email match and no unambiguous name match are left
alone — they are treated as contact-only entries and handled by the
view-layer dedupe.

Recommended run order
---------------------
  1. restore_prod_db.sh      # fresh prod dump into test DB
  2. fix_parent_duplicates.py    # runs on canonical (pre-sanitise) data
  3. sanitise_test_db.sh     # scramble emails/phones

If you run out of order (e.g. after sanitise), the name fallback
catches guardians whose emails have drifted from their users.

Usage:
    python fix_parent_duplicates.py [--dry-run]

Idempotent — safe to re-run.
"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
import django; django.setup()

from django.db import transaction
from accounts.models import CustomUser
from classroom.models import Guardian, StudentGuardian, ParentStudent

DRY_RUN = '--dry-run' in sys.argv


def find_parent_user(guardian):
    """Return (user, match_type) or (None, None).

    match_type is 'email' or 'name'. Name fallback only fires when exactly
    one CustomUser in the same school has a ParentStudent link and matches
    first_name + last_name case-insensitively.
    """
    if guardian.email:
        user = CustomUser.objects.filter(email__iexact=guardian.email).first()
        if user:
            return user, 'email'

    # Name fallback — restrict to users who already have a ParentStudent
    # in this school to avoid matching unrelated users with the same name.
    fn = (guardian.first_name or '').strip()
    ln = (guardian.last_name or '').strip()
    if not fn or not ln or guardian.school_id is None:
        return None, None

    candidates = (
        CustomUser.objects
        .filter(
            first_name__iexact=fn,
            last_name__iexact=ln,
            parent_student_links__school_id=guardian.school_id,
            parent_student_links__is_active=True,
        )
        .distinct()
    )
    if candidates.count() == 1:
        return candidates.first(), 'name'
    return None, None


def main():
    print('=' * 60)
    print('Parent duplicate cleanup')
    print('DRY RUN' if DRY_RUN else 'APPLYING CHANGES')
    print('=' * 60)

    stats = {
        'guardians_checked': 0,
        'matched_by_email': 0,
        'matched_by_name': 0,
        'parent_student_links_created': 0,
        'guardians_deleted': 0,
        'guardians_orphan_kept': 0,
    }

    guardians = Guardian.objects.select_related('school').all()
    stats['guardians_checked'] = guardians.count()

    for g in guardians:
        parent_user, match_type = find_parent_user(g)
        if not parent_user:
            stats['guardians_orphan_kept'] += 1
            continue

        if match_type == 'email':
            stats['matched_by_email'] += 1
        elif match_type == 'name':
            stats['matched_by_name'] += 1

        sg_links = StudentGuardian.objects.filter(guardian=g).select_related('student')
        ported = 0
        for sg in sg_links:
            existing = ParentStudent.objects.filter(
                parent=parent_user, student=sg.student, school=g.school,
                is_active=True,
            ).exists()
            if existing:
                continue
            if DRY_RUN:
                ported += 1
                continue
            ParentStudent.objects.create(
                parent=parent_user,
                student=sg.student,
                school=g.school,
                relationship=g.relationship or 'guardian',
                is_primary_contact=sg.is_primary,
                is_active=True,
            )
            ported += 1
        stats['parent_student_links_created'] += ported

        prefix = '[dry] ' if DRY_RUN else ''
        action = 'would port' if DRY_RUN else 'ported'
        delete_action = 'would delete' if DRY_RUN else 'deleted'
        print(
            f'  {prefix}school={g.school_id} guardian={g.id} ({g.email}) '
            f'[{match_type}->user={parent_user.id}] '
            f'-> {action} {ported} link(s), {delete_action} guardian'
        )

        if not DRY_RUN:
            with transaction.atomic():
                g.delete()  # cascades StudentGuardian
        stats['guardians_deleted'] += 1

    print()
    print('-' * 60)
    for k, v in stats.items():
        print(f'  {k}: {v}')
    print('-' * 60)
    if DRY_RUN:
        print('DRY RUN — no changes written.')


if __name__ == '__main__':
    main()
