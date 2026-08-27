"""Give every maths ``Level`` the subject it has always belonged to.

Year levels 1-9 were created before ``Level.subject`` existed — ``setup_dev``
still creates them with a display name only — so they carry NULL. Migration
0101 backfilled Year 10 alone, when it added it.

A level that belongs to no subject:

* appears in no subject group on the Edit Class page, so its checkbox is never
  rendered and **saving that page silently drops it from the class**;
* is offered under *every* subject by the department level admin
  (``Q(subject=subj) | Q(subject__isnull=True)``), so a Year level can be mapped
  under a department that does not teach maths.

Scope, per the ``Level`` docstring: ``level_number`` below 100 is a Year level
and 100-199 is Basic Facts — both Mathematics. **200+ is school-created and is
deliberately left alone**: a custom level carries no promise about its subject
and guessing one would be worse than leaving it blank.

Nothing else is touched. No ``DepartmentLevel`` mapping is created, altered or
removed, so an existing odd mapping survives for a human to review (the
``audit_class_subjects`` command lists them).
"""

from django.db import migrations

# Year levels (1-99) and Basic Facts (100-199) are maths. 200+ is school custom.
MATHS_LEVEL_CEILING = 200


def set_maths_subject(apps, schema_editor):
    Level = apps.get_model('classroom', 'Level')
    Subject = apps.get_model('classroom', 'Subject')

    maths = (
        Subject.objects.filter(slug='mathematics', school__isnull=True).first()
        or Subject.objects.filter(slug='mathematics').first()
        or Subject.objects.filter(name='Mathematics').first()
    )
    if maths is None:
        # A fresh or test database with no Mathematics subject yet — nothing to
        # attach these levels to. Same guard as 0101.
        return

    Level.objects.filter(
        subject__isnull=True,
        level_number__lt=MATHS_LEVEL_CEILING,
    ).update(subject=maths)


def clear_maths_subject(apps, schema_editor):
    """Reverse: only the rows this migration could have set.

    Year 10 is excluded — 0101 set its subject and owns putting it back.
    """
    Level = apps.get_model('classroom', 'Level')
    Subject = apps.get_model('classroom', 'Subject')

    maths = (
        Subject.objects.filter(slug='mathematics', school__isnull=True).first()
        or Subject.objects.filter(slug='mathematics').first()
    )
    if maths is None:
        return

    Level.objects.filter(
        subject=maths,
        level_number__lt=MATHS_LEVEL_CEILING,
    ).exclude(level_number=10).update(subject=None)


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0117_school_free_ai_grading'),
    ]

    operations = [
        migrations.RunPython(set_maths_subject, clear_maths_subject),
    ]
