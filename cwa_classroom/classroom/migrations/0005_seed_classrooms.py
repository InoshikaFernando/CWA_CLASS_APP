import uuid
from django.db import migrations


def seed_classrooms(apps, schema_editor):
    ClassRoom = apps.get_model('classroom', 'ClassRoom')
    Level = apps.get_model('classroom', 'Level')
    Subject = apps.get_model('classroom', 'Subject')

    subject = Subject.objects.filter(name='Mathematics').first()

    for year in range(1, 10):  # Year 1 – Year 9
        level = Level.objects.filter(level_number=year).first()
        if not level:
            continue
        if ClassRoom.objects.filter(name=f'Year {year}').exists():
            continue
        classroom = ClassRoom(
            name=f'Year {year}',
            code=uuid.uuid4().hex[:8].upper(),
            is_active=True,
            subject=subject,
        )
        classroom.save()
        classroom.levels.add(level)


def reverse_seed_classrooms(apps, schema_editor):
    ClassRoom = apps.get_model('classroom', 'ClassRoom')
    for year in range(1, 10):
        ClassRoom.objects.filter(name=f'Year {year}').delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0004_classroom_subject'),
    ]

    operations = [
        migrations.RunPython(seed_classrooms, reverse_seed_classrooms),
    ]
