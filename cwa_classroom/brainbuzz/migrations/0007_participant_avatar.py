from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('brainbuzz', '0006_add_quiz_builder'),
    ]

    operations = [
        migrations.AddField(
            model_name='brainbuzzparticipant',
            name='avatar',
            field=models.CharField(default='🦁', max_length=10),
        ),
    ]
