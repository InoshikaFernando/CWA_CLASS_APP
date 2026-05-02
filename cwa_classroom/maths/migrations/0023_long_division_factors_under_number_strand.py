"""Place 'Long Division' and 'Factors' under the 'Number' strand.

Migrations 0021 and 0022 created these topics without a parent so they
didn't appear in the Number-strand section of the topic browser. This
migration backfills the parent on existing rows; new rows get the
correct parent on creation in 0022 once the strand exists.
"""
from django.db import migrations


def link_to_number_strand(apps, schema_editor):
    Subject = apps.get_model("classroom", "Subject")
    Topic = apps.get_model("classroom", "Topic")

    maths = Subject.objects.filter(name="Mathematics", school__isnull=True).first()
    if maths is None:
        return

    number = Topic.objects.filter(
        subject=maths, name="Number", parent__isnull=True,
    ).first()
    if number is None:
        return

    for name in ("Long Division", "Factors"):
        topic = Topic.objects.filter(
            subject=maths, name=name, parent__isnull=True,
        ).first()
        if topic is not None:
            topic.parent = number
            topic.save(update_fields=["parent"])


def unlink(apps, schema_editor):
    Subject = apps.get_model("classroom", "Subject")
    Topic = apps.get_model("classroom", "Topic")

    maths = Subject.objects.filter(name="Mathematics", school__isnull=True).first()
    if maths is None:
        return
    number = Topic.objects.filter(
        subject=maths, name="Number", parent__isnull=True,
    ).first()
    if number is None:
        return
    Topic.objects.filter(
        subject=maths, name__in=("Long Division", "Factors"), parent=number,
    ).update(parent=None)


class Migration(migrations.Migration):
    dependencies = [
        ("maths", "0022_seed_questions_from_json_banks"),
    ]
    operations = [
        migrations.RunPython(link_to_number_strand, unlink),
    ]
