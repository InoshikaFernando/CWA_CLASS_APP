"""Repair ``ClassRoom.subject`` where the old level-inference got it wrong.

Until the accompanying view change, a class's subject was never stored from what
the user picked — it was read off ``levels.first()``. ``Level.Meta.ordering`` is
``level_number`` and ``level_number`` is globally unique, so Maths (1-10) always
sorted ahead of every other subject (300+): **a class holding any maths level
was labelled Mathematics whatever it taught.**

The rules here are exactly the ones ``manage.py audit_class_subjects`` reports,
so the audit output run beforehand *is* this migration's change list.

  * levels resolve to exactly one subject  -> set it
  * no levels and no subject               -> the department's first subject
  * levels spanning 2+ subjects            -> SKIPPED and logged. Never guessed:
                                              only a human knows which the class
                                              actually teaches.
  * a level whose subject is unknowable    -> SKIPPED and logged

Run 0118 first (this migration depends on it) so Year levels name their subject
before anything is inferred from them.

Recovery: every change is written to the audit log as ``class_subject_repaired``
with the previous ``subject_id``, so any class can be put back with a single
update. Nothing is deleted, and no level mapping is touched.

Known and accepted consequence: teacher-entered progress recorded against the
*old* subject's criteria, and teacher comments filed under it, stop displaying
on that class's progress page (both are scoped by ``classroom.subject``). The
rows survive. Student work — homework, worksheet, quiz and coding submissions —
is unaffected: none of it references ``classroom.subject`` or
``ProgressCriteria``. The audit reports these counts before you run this.
"""

import logging

from django.db import migrations

logger = logging.getLogger(__name__)

MATHS_LEVEL_CEILING = 200


def _level_subject_id(level, maths_id):
    """Subject a level belongs to, or None when that is unknowable."""
    if level.subject_id:
        return level.subject_id
    if level.level_number < MATHS_LEVEL_CEILING and maths_id:
        return maths_id
    return None


def repair(apps, schema_editor):
    ClassRoom = apps.get_model('classroom', 'ClassRoom')
    DepartmentSubject = apps.get_model('classroom', 'DepartmentSubject')
    Subject = apps.get_model('classroom', 'Subject')
    AuditLog = apps.get_model('audit', 'AuditLog')

    maths = (
        Subject.objects.filter(slug='mathematics', school__isnull=True).first()
        or Subject.objects.filter(slug='mathematics').first()
    )
    maths_id = maths.id if maths else None

    repaired = skipped = 0

    classrooms = (
        ClassRoom.objects.filter(is_active=True)
        .select_related('department')
        .prefetch_related('levels')
    )

    for classroom in classrooms.iterator(chunk_size=500):
        subject_ids = set()
        unknown = False
        for level in classroom.levels.all():
            sid = _level_subject_id(level, maths_id)
            if sid:
                subject_ids.add(sid)
            else:
                unknown = True

        if unknown or len(subject_ids) > 1:
            skipped += 1
            logger.warning(
                'class_subject_repair: skipped classroom id=%s name=%r — '
                '%s. Needs a human.',
                classroom.id, classroom.name,
                'levels span %d subjects' % len(subject_ids)
                if len(subject_ids) > 1
                else 'a level has no resolvable subject',
            )
            continue

        if len(subject_ids) == 1:
            proposed_id = subject_ids.pop()
        elif classroom.subject_id:
            continue  # No levels, but already labelled — leave it.
        else:
            ds = (
                DepartmentSubject.objects
                .filter(department_id=classroom.department_id)
                .order_by('order', 'subject__name')
                .first()
            )
            if ds is None:
                continue
            proposed_id = ds.subject_id

        if proposed_id == classroom.subject_id:
            continue

        previous_id = classroom.subject_id
        classroom.subject_id = proposed_id
        classroom.save(update_fields=['subject'])
        repaired += 1

        AuditLog.objects.create(
            user=None,
            school_id=classroom.school_id,
            category='data_change',
            action='class_subject_repaired',
            detail={
                'classroom_id': classroom.id,
                'classroom_name': classroom.name,
                'previous_subject_id': previous_id,
                'new_subject_id': proposed_id,
                'migration': '0119_repair_classroom_subject',
            },
        )

    logger.info(
        'class_subject_repair: %d classroom(s) repaired, %d skipped for review.',
        repaired, skipped,
    )


def unrepair(apps, schema_editor):
    """Put every repaired class back, from the audit trail this wrote."""
    ClassRoom = apps.get_model('classroom', 'ClassRoom')
    AuditLog = apps.get_model('audit', 'AuditLog')

    entries = AuditLog.objects.filter(action='class_subject_repaired')
    for entry in entries.iterator():
        detail = entry.detail or {}
        if detail.get('migration') != '0119_repair_classroom_subject':
            continue
        ClassRoom.objects.filter(id=detail.get('classroom_id')).update(
            subject_id=detail.get('previous_subject_id'),
        )
    entries.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0118_backfill_level_subject'),
        ('audit', '0003_add_revertible_fields'),
    ]

    operations = [
        migrations.RunPython(repair, unrepair),
    ]
