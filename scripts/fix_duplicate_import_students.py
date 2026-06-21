"""
fix_duplicate_import_students.py
--------------------------------
Merges duplicate STUDENT accounts that the CSV importer created for a single
real child, then hard-deletes the redundant ("phantom") accounts.

Background
----------
The student CSV importer used to generate a *numbered* placeholder email per
row when a student had no email of their own (parent+name, parent+name1,
parent+name2 ...). A child listed on multiple rows — one row per class in
Teachworks-style exports — therefore got one separate account per row,
defeating the email-based dedup. The 2026-04-04 import created 70+ duplicate
student accounts across ~35 families (school 4). The importer bug itself is
fixed in classroom/import_services.py; this script cleans up the data that bug
already produced.

What "duplicate" means here
---------------------------
Two or more DISTINCT CustomUser rows that
  * are linked (active ParentStudent) to the SAME parent, and
  * share the SAME first_name + last_name.
The unique_parent_student constraint does NOT catch these because the student
*ids* differ — only the names collide.

Merge strategy
--------------
Per (parent, first_name, last_name) group:
  1. Choose a CANONICAL account — the one with the strongest "real use" signal
     (has logged in > most learning activity), tie-broken by lowest id. In the
     2026-04-04 data the canonical is always the lowest-id, un-numbered-email
     account (the credentials the family actually used).
  2. Re-point every reverse FK on each phantom account to the canonical:
     class enrolments, invoices, attendance, progress, homework, etc. are
     PRESERVED under the canonical account. Where a uniqueness constraint would
     collide (e.g. both accounts already enrolled in the same class, or both
     have a SchoolStudent for the school), the phantom's redundant row is
     dropped instead of re-pointed.
  3. Hard-delete the phantom CustomUser.

Nothing real is lost — billing, attendance and learning history all survive on
the single surviving account; only the empty duplicate shells are removed.

Safety
------
  * --dry-run prints every account, its chosen canonical, and a per-model
    breakdown of what would be re-pointed / dropped, WITHOUT writing anything.
  * Each group is merged in its own transaction — a failure rolls back that
    group only.
  * A group is SKIPPED (left untouched, flagged) if more than one account in it
    shows login/activity, since that needs a human to decide which is real.
  * Idempotent: re-running after a successful pass finds no duplicates.

Usage
-----
    python fix_duplicate_import_students.py            # DRY RUN (default, safe)
    python fix_duplicate_import_students.py --dry-run  # same — explicit
    python fix_duplicate_import_students.py --apply    # actually write changes

Writing requires the explicit --apply flag, so an accidental run never mutates
data. Recommended: dry-run on a fresh prod restore in DEV, eyeball the output
(especially the 11 split-billing families), then --apply.
"""

import os
import sys
from collections import defaultdict

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(BASE_DIR, '..', 'cwa_classroom'))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'cwa_classroom.settings')
import django  # noqa: E402
django.setup()

from django.db import transaction, IntegrityError  # noqa: E402
from django.db.models import Q  # noqa: E402
from accounts.models import CustomUser  # noqa: E402
from classroom.models import ParentStudent  # noqa: E402

# Dry-run is the DEFAULT. Writing requires the explicit --apply flag so an
# accidental invocation can never mutate data.
DRY_RUN = '--apply' not in sys.argv

# Reverse FK accessors that represent the student's own LEARNING / BILLING
# history. Used only to score which account is "real" when picking canonical.
ACTIVITY_RELATIONS = (
    'homework_submissions', 'homeworksubmission_set',
    'basicfactsresult_set', 'puzzlesession_set',
    'studentpuzzleprogress_set', 'studentexercisesubmission_set',
)


def _norm(s):
    return (s or '').strip().lower()


def find_duplicate_groups():
    """Return list of {parent_id, name, users:[CustomUser,...]} with >1 user."""
    links = (
        ParentStudent.objects
        .filter(is_active=True)
        .select_related('parent', 'student')
    )
    buckets = defaultdict(dict)  # (parent_id, fn, ln) -> {student_id: user}
    for link in links:
        s = link.student
        key = (link.parent_id, _norm(s.first_name), _norm(s.last_name))
        buckets[key][s.id] = s

    groups = []
    for (parent_id, fn, ln), users_by_id in buckets.items():
        if len(users_by_id) < 2:
            continue
        users = [users_by_id[i] for i in sorted(users_by_id)]
        groups.append({
            'parent_id': parent_id,
            'name': f'{users[0].first_name} {users[0].last_name}',
            'users': users,
        })
    return sorted(groups, key=lambda g: (g['name'], g['parent_id']))


def login_or_activity(user):
    """(has_logged_in, activity_row_count) for canonical scoring / safety."""
    logged_in = 1 if user.last_login else 0
    count = 0
    for rel in ACTIVITY_RELATIONS:
        mgr = getattr(user, rel, None)
        if mgr is not None:
            try:
                count += mgr.count()
            except Exception:
                pass
    return logged_in, count


def pick_canonical(users):
    """Return (canonical, others, multiple_active).

    Canonical = strongest real-use signal, tie-broken by lowest id.
    multiple_active=True means >1 account shows login/activity → caller skips.
    """
    scored = []
    active_count = 0
    for u in users:
        logged_in, activity = login_or_activity(u)
        if logged_in or activity:
            active_count += 1
        # higher is better; lowest id as final tie-break (negate id)
        scored.append(((logged_in, activity, -u.id), u))
    scored.sort(key=lambda t: t[0], reverse=True)
    canonical = scored[0][1]
    others = [u for u in users if u.id != canonical.id]
    return canonical, others, active_count > 1


def merge_user(phantom, canonical):
    """Re-point every reverse FK from phantom -> canonical, dropping rows that
    would violate a uniqueness constraint. Returns (repointed, dropped) per
    model name dict. Does NOT delete the phantom user (caller does)."""
    repointed = defaultdict(int)
    dropped = defaultdict(int)

    for rel in phantom._meta.related_objects:
        # related_objects are REVERSE relations: a FK on another model pointing
        # at CustomUser shows up here as one_to_many (O2O as one_to_one). Skip
        # M2M (groups/permissions) — a student has none and they need no merge.
        if not (rel.one_to_many or rel.one_to_one):
            continue
        field = rel.field
        model = rel.related_model
        label = f'{model._meta.app_label}.{model.__name__}.{field.name}'
        rows = list(model.objects.filter(**{field.name: phantom.id}))
        for obj in rows:
            # ParentStudent's uniqueness is a *conditional* UniqueConstraint,
            # which MySQL does NOT enforce — so IntegrityError won't fire and a
            # blind re-point would create a NEW duplicate link. Dedupe by hand:
            # if the canonical is already linked to the same (parent, school),
            # the phantom's link is redundant — drop it.
            if model is ParentStudent and field.name == 'student':
                clash = (
                    ParentStudent.objects
                    .filter(parent_id=obj.parent_id, student_id=canonical.id,
                            school_id=obj.school_id)
                    .exclude(pk=obj.pk)
                    .exists()
                )
                if clash:
                    ParentStudent.objects.filter(pk=obj.pk).delete()
                    dropped[label] += 1
                    continue
            setattr(obj, field.attname, canonical.id)
            try:
                with transaction.atomic():
                    obj.save(update_fields=[field.attname])
                repointed[label] += 1
            except IntegrityError:
                # Canonical already has the equivalent row (unique_together).
                model.objects.filter(pk=obj.pk).delete()
                dropped[label] += 1
    return repointed, dropped


def main():
    print('=' * 70)
    print('Duplicate import-student merge')
    print('DRY RUN — no changes written' if DRY_RUN else 'APPLYING CHANGES')
    print('=' * 70)

    groups = find_duplicate_groups()
    stats = {
        'groups_found': len(groups),
        'groups_merged': 0,
        'groups_skipped_ambiguous': 0,
        'phantoms_deleted': 0,
        'rows_repointed': 0,
        'rows_dropped': 0,
    }

    for g in groups:
        canonical, phantoms, ambiguous = pick_canonical(g['users'])
        header = (
            f"\n[{g['name']}] parent={g['parent_id']} "
            f"accounts={[u.id for u in g['users']]} "
            f"-> canonical={canonical.id} ({canonical.email})"
        )
        print(header)

        if ambiguous:
            stats['groups_skipped_ambiguous'] += 1
            print('  !! SKIPPED — more than one account shows login/activity; '
                  'needs manual review.')
            continue

        group_repointed = defaultdict(int)
        group_dropped = defaultdict(int)

        def _do_merge():
            for phantom in phantoms:
                rp, dr = merge_user(phantom, canonical)
                for k, v in rp.items():
                    group_repointed[k] += v
                for k, v in dr.items():
                    group_dropped[k] += v
                # Phantom's own ParentStudent link(s) are now re-pointed or
                # dropped above; remove the account itself.
                CustomUser.objects.filter(pk=phantom.id).delete()
                stats['phantoms_deleted'] += 1

        if DRY_RUN:
            # Re-point inside a transaction we roll back, so we can REPORT the
            # exact effect (incl. unique-collision drops) without persisting.
            try:
                with transaction.atomic():
                    _do_merge()
                    raise _Rollback()
            except _Rollback:
                pass
        else:
            with transaction.atomic():
                _do_merge()

        for label in sorted(set(group_repointed) | set(group_dropped)):
            rp = group_repointed.get(label, 0)
            dr = group_dropped.get(label, 0)
            bits = []
            if rp:
                bits.append(f'{rp} re-pointed')
            if dr:
                bits.append(f'{dr} dropped (dup)')
            print(f'    {label}: ' + ', '.join(bits))
            stats['rows_repointed'] += rp
            stats['rows_dropped'] += dr

        print(f'  -> {"would delete" if DRY_RUN else "deleted"} '
              f'{len(phantoms)} phantom account(s): {[p.id for p in phantoms]}')
        stats['groups_merged'] += 1

    print('\n' + '-' * 70)
    for k, v in stats.items():
        print(f'  {k}: {v}')
    print('-' * 70)
    if DRY_RUN:
        print('DRY RUN — nothing was written. Re-run with --apply to write changes.')


class _Rollback(Exception):
    """Used to abort the dry-run transaction after measuring its effect."""


if __name__ == '__main__':
    main()
