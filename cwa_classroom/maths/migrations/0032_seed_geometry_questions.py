from django.db import migrations


def _seed(apps, schema_editor):
    from maths.seed_geometry import seed
    seed(
        apps.get_model('classroom', 'Subject'),
        apps.get_model('classroom', 'Level'),
        apps.get_model('classroom', 'Topic'),
        apps.get_model('maths', 'Question'),
        apps.get_model('maths', 'Answer'),
    )


def _unseed(apps, schema_editor):
    from maths.seed_geometry import unseed
    unseed(
        apps.get_model('classroom', 'Subject'),
        apps.get_model('classroom', 'Level'),
        apps.get_model('classroom', 'Topic'),
        apps.get_model('maths', 'Question'),
        apps.get_model('maths', 'Answer'),
    )


class Migration(migrations.Migration):
    dependencies = [
        ('maths', '0031_question_grid_spec_alter_question_question_type'),
        ('classroom', '0001_initial'),
    ]
    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
