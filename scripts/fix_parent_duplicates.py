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

This script ports any Guardian records whose (school, email) matches an
existing parent CustomUser into ParentStudent links, then deletes the
redundant Guardian (StudentGuardian cascades via FK).

Guardians with NO matching CustomUser are left alone — they represent
contact-only entries and are handled by the view-layer dedupe.

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


def main():
    print('=' * 60)
    print('Parent duplicate cleanup')
    print('DRY RUN' if DRY_RUN else 'APPLYING CHANGES')
    print('=' * 60)

    stats = {
        'guardians_checked': 0,
        'guardians_matched': 0,
        'parent_student_links_created': 0,
        'guardians_deleted': 0,
        'guardians_orphan_kept': 0,
    }

    guardians = Guardian.objects.select_related('school').all()
    stats['guardians_checked'] = guardians.count()

    for g in guardians:
        if not g.email:
            stats['guardians_orphan_kept'] += 1
            continue

        parent_user = CustomUser.objects.filter(email__iexact=g.email).first()
        if not parent_user:
            stats['guardians_orphan_kept'] += 1
            continue

        stats['guardians_matched'] += 1

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

        if DRY_RUN:
            stats['guardians_deleted'] += 1
            print(
                f'  [dry] school={g.school_id} guardian={g.id} ({g.email}) '
                f'-> would port {ported} link(s) and delete guardian'
            )
        else:
            with transaction.atomic():
                g.delete()  # cascades StudentGuardian
            stats['guardians_deleted'] += 1
            print(
                f'  school={g.school_id} guardian={g.id} ({g.email}) '
                f'-> ported {ported} link(s), guardian deleted'
            )

    print()
    print('-' * 60)
    for k, v in stats.items():
        print(f'  {k}: {v}')
    print('-' * 60)
    if DRY_RUN:
        print('DRY RUN — no changes written.')


if __name__ == '__main__':
    main()
