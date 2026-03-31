from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0002_studentlevelenrollment'),
    ]

    operations = [
        migrations.AddField(
            model_name='topic',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                help_text='Leave blank for top-level topics; set for subtopics.',
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='subtopics',
                to='classroom.topic',
            ),
        ),
    ]
