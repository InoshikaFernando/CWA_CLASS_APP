from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0006_add_quiz_builder'),
    ]

    operations = [
        migrations.AddField(
            model_name='brainbuzzparticipant',
            name='avatar',
            # Use empty string as the DB-level default so MySQL doesn't need to
            # store a 4-byte emoji in the column default (which requires the
            # column to already have utf8mb4 charset, which ALTER TABLE ADD
            # COLUMN doesn't guarantee).  The model-level default='🦁' still
            # applies when creating BrainBuzzParticipant objects in Python.
            field=models.CharField(default='', max_length=10, blank=True),
        ),
    ]
