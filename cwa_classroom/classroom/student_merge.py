"""
Student account merge — detection, validation, and soft-merge service.

Lets an admin/HoI fix accidentally-duplicated student accounts from the UI.
A child sometimes ends up with two (or more) accounts — e.g. a CSV import that
generated a placeholder email per class row, or a kid who self-registers a
second account. This module finds those duplicates and merges them safely.

Merge is **soft**: all of the child's learning + billing data (invoices,
attendance, class enrolments, homework, ...) is re-pointed onto the surviving
"keep" account; the absorbed account and its parent/school links are then
DEACTIVATED (is_active=False), never deleted. Nothing financial is destroyed
(`Invoice.student` is on_delete=CASCADE, so deleting would take invoices with
it — soft-merge sidesteps that entirely), and the change stays auditable and
reversible.

Guardrails — two accounts may only be merged when ALL hold:
  1. same first name (case-insensitive)
  2. same last name (case-insensitive)
  3. linked to exactly the same, non-empty set of parent accounts in the school
These are enforced in validate_merge() and re-checked at POST time, so two
genuinely different children can never be merged.
"""
import logging
from collections import defaultdict

from django.db import IntegrityError, transaction

from accounts.models import CustomUser
from .models import ParentStudent, SchoolStudent

logger = logging.getLogger(__name__)

# Reverse relations we do NOT re-point onto the keep account. Parent/school
# links are handled explicitly (deactivated); the rest are account-scoped or
# historical (roles, audit trail, notifications, email history) and should stay
# with the absorbed account rather than be misattributed to the survivor.
_SKIP_MODELS = {
    'classroom.parentstudent',   # handled: deactivated
    'classroom.schoolstudent',   # handled: deactivated
    'accounts.userrole',
    'accounts.customuser',       # self-FK (blocked_by)
    'audit.auditlog',
    'admin.logentry',
    'classroom.notification',
    'classroom.emaillog',
    'classroom.emailqueue',
    'classroom.emailpreference',
}


def _norm(s):
    return (s or '').strip().lower()


def parent_ids(student, school):
    """Frozenset of parent user ids actively linked to this student in school."""
    return frozenset(
        ParentStudent.objects
        .filter(student=student, school=school, is_active=True)
        .values_list('parent_id', flat=True)
    )


def _activity_score(user):
    """Sort key for choosing the survivor: logged-in, then most data, then
    oldest account. Higher tuple sorts first."""
    homework = getattr(user, 'homework_submissions', None)
    hw = homework.count() if homework is not None else 0
    bf = user.basicfactsresult_set.count() if hasattr(user, 'basicfactsresult_set') else 0
    classes = ClassStudentCount(user)
    return (1 if user.last_login else 0, hw + bf + classes, -user.id)


def ClassStudentCount(user):
    return user.class_student_entries.filter(is_active=True).count()


def _parent_map(school):
    """student_id -> frozenset(active parent ids) for the whole school, in one
    query (avoids an N+1 when scanning every student)."""
    by_student = defaultdict(set)
    for sid, pid in (
        ParentStudent.objects
        .filter(school=school, is_active=True)
        .values_list('student_id', 'parent_id')
    ):
        by_student[sid].add(pid)
    return {sid: frozenset(pids) for sid, pids in by_student.items()}


def find_duplicate_groups(school):
    """Return groups of active student accounts in `school` that satisfy the
    three merge guardrails. Each group is a list of CustomUser (>= 2), sorted
    with the suggested survivor first.
    """
    student_ids = list(
        SchoolStudent.objects
        .filter(school=school, is_active=True)
        .values_list('student_id', flat=True)
    )
    if not student_ids:
        return []

    pmap = _parent_map(school)
    students = CustomUser.objects.filter(id__in=student_ids, is_active=True)

    buckets = defaultdict(list)
    for s in students:
        pids = pmap.get(s.id)
        if not pids:
            continue  # guardrail 3: must share a (non-empty) parent set
        buckets[(_norm(s.first_name), _norm(s.last_name), pids)].append(s)

    groups = []
    for members in buckets.values():
        if len(members) < 2:
            continue
        members.sort(key=_activity_score, reverse=True)
        groups.append(members)
    # Stable, friendly ordering for the UI.
    groups.sort(key=lambda g: (_norm(g[0].first_name), _norm(g[0].last_name)))
    return groups


def get_group_by_ids(school, ids):
    """Load the accounts for `ids` and verify they form ONE valid merge group
    (active, in school, same name, same parent set). Returns the list sorted
    survivor-first, or raises ValueError."""
    ids = [int(i) for i in ids]
    if len(set(ids)) < 2:
        raise ValueError('Select at least two accounts to merge.')
    users = list(CustomUser.objects.filter(id__in=ids, is_active=True))
    if len(users) != len(set(ids)):
        raise ValueError('One or more selected accounts no longer exist or are inactive.')
    in_school = set(
        SchoolStudent.objects
        .filter(school=school, student_id__in=ids, is_active=True)
        .values_list('student_id', flat=True)
    )
    if in_school != set(ids):
        raise ValueError('All accounts must be active students of this school.')
    # Pairwise guardrails against the first account.
    anchor = users[0]
    for other in users[1:]:
        ok, err = validate_merge(anchor, other, school)
        if not ok:
            raise ValueError(err)
    users.sort(key=_activity_score, reverse=True)
    return users


def account_summary(user, school):
    """Per-account data counts shown in the merge modal so the admin sees what
    will move onto the survivor."""
    return {
        'user': user,
        'logged_in': bool(user.last_login),
        'classes': user.class_student_entries.filter(is_active=True).count(),
        'invoices': user.invoices.count(),
        'homework': (user.homework_submissions.count()
                     if hasattr(user, 'homework_submissions') else 0),
    }


def suggest_keep(group):
    """The account the UI pre-selects as the survivor."""
    return max(group, key=_activity_score)


def validate_merge(keep, absorbed, school):
    """Enforce the three guardrails for one (keep, absorbed) pair.
    Returns (ok: bool, error: str|None)."""
    if keep.id == absorbed.id:
        return False, 'Cannot merge an account into itself.'
    if _norm(keep.first_name) != _norm(absorbed.first_name):
        return False, 'First names do not match.'
    if _norm(keep.last_name) != _norm(absorbed.last_name):
        return False, 'Last names do not match.'
    kp, ap = parent_ids(keep, school), parent_ids(absorbed, school)
    if not kp or not ap:
        return False, 'Both accounts must be linked to a parent in this school.'
    if kp != ap:
        return False, 'Accounts are linked to different parents.'
    return True, None


@transaction.atomic
def merge_students(keep, absorbed_list, school, actor=None, request=None):
    """Soft-merge each account in absorbed_list into keep.

    Re-points every data relation (skipping account/audit/parent/school ones),
    then deactivates each absorbed account and its parent + school links.
    Returns a summary dict. Raises ValueError if any pair fails a guardrail.
    """
    for absorbed in absorbed_list:
        ok, err = validate_merge(keep, absorbed, school)
        if not ok:
            raise ValueError(f'Refusing to merge {absorbed.id} into {keep.id}: {err}')

    summary = {
        'keep_id': keep.id,
        'absorbed_ids': [],
        'repointed': defaultdict(int),
        'skipped_collisions': defaultdict(int),
        'warnings': [],
    }

    for absorbed in absorbed_list:
        for rel in absorbed._meta.related_objects:
            if not (rel.one_to_many or rel.one_to_one):
                continue  # M2M (groups/permissions) — nothing to merge
            model = rel.related_model
            key = f'{model._meta.app_label}.{model._meta.model_name}'
            if key in _SKIP_MODELS:
                continue
            field = rel.field
            label = f'{model._meta.app_label}.{model.__name__}'
            for obj in model.objects.filter(**{field.name: absorbed.id}):
                setattr(obj, field.attname, keep.id)
                try:
                    with transaction.atomic():
                        obj.save(update_fields=[field.attname])
                    summary['repointed'][label] += 1
                except IntegrityError:
                    # Keep already owns the equivalent row (unique constraint),
                    # or a OneToOne (e.g. a Subscription) collides. Leave the
                    # row on the now-deactivated absorbed account; flag O2O so a
                    # human notices a subscription that couldn't be carried over.
                    summary['skipped_collisions'][label] += 1
                    if rel.one_to_one:
                        summary['warnings'].append(
                            f'{label} for account {absorbed.id} could not be merged '
                            f'(account {keep.id} already has one) — left in place.'
                        )

        # Deactivate the absorbed account's parent + school links and the
        # account itself. Same-parent guardrail means keep already holds every
        # parent link, so nothing is lost.
        ParentStudent.objects.filter(
            student=absorbed, school=school, is_active=True,
        ).update(is_active=False)
        SchoolStudent.objects.filter(
            student=absorbed, school=school, is_active=True,
        ).update(is_active=False)
        absorbed.is_active = False
        absorbed.save(update_fields=['is_active'])
        summary['absorbed_ids'].append(absorbed.id)

    summary['repointed'] = dict(summary['repointed'])
    summary['skipped_collisions'] = dict(summary['skipped_collisions'])

    try:
        from audit.services import log_event
        log_event(
            user=actor, school=school, category='data_change',
            action='student_accounts_merged', result='allowed',
            detail={
                'keep_id': keep.id,
                'absorbed_ids': summary['absorbed_ids'],
                'repointed': summary['repointed'],
                'skipped_collisions': summary['skipped_collisions'],
            },
            request=request,
        )
    except Exception:  # audit must never break the merge
        logger.exception('Failed to log student merge audit event')

    return summary
