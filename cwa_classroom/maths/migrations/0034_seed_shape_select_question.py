from django.db import migrations


def _seed(apps, schema_editor):
    # seed() is idempotent (get_or_create keyed on text + type), so re-running it
    # only adds the new shape_select starter — the draw_on_grid / measure
    # questions from 0032 already exist and are left untouched.
    from maths.seed_geometry import seed
    seed(
        apps.get_model('classroom', 'Subject'),
        apps.get_model('classroom', 'Level'),
        apps.get_model('classroom', 'Topic'),
        apps.get_model('maths', 'Question'),
        apps.get_model('maths', 'Answer'),
    )


def _unseed(apps, schema_editor):
    Question = apps.get_model('maths', 'Question')
    from maths.seed_geometry import SHAPE_SELECT_TEXT
    Question.objects.filter(
        question_type='shape_select', question_text=SHAPE_SELECT_TEXT
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        ('maths', '0033_question_shape_spec_alter_question_question_type'),
        ('classroom', '0007_seed_topic_level_links'),
    ]
    operations = [
        migrations.RunPython(_seed, _unseed),
    ]
