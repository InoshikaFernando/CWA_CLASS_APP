from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0003_topic_parent'),
    ]

    operations = [
        migrations.AddField(
            model_name='classroom',
            name='subject',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='classrooms',
                to='classroom.subject',
            ),
        ),
    ]
