from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0053_add_fee_fields'),
    ]

    operations = [
        migrations.AlterField(
            model_name='progresscriteria',
            name='level',
            field=models.ForeignKey(
                blank=True,
                help_text='Null = applies to all levels for the chosen subject.',
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='progress_criteria',
                to='classroom.level',
            ),
        ),
        migrations.AlterUniqueTogether(
            name='progresscriteria',
            unique_together=set(),
        ),
    ]
