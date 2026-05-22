from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0098_emailqueue'),
    ]

    operations = [
        migrations.AddField(
            model_name='emaillog',
            name='school',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='email_logs',
                to='classroom.school',
            ),
        ),
        migrations.AddField(
            model_name='emaillog',
            name='invoice',
            field=models.ForeignKey(
                blank=True,
                db_index=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='email_logs',
                to='classroom.invoice',
            ),
        ),
    ]
