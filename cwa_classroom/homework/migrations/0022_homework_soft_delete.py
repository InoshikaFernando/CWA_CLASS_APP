import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('homework', '0021_homeworkdraft'),
    ]

    operations = [
        migrations.AddField(
            model_name='homework',
            name='deleted_at',
            field=models.DateTimeField(
                blank=True, db_index=True, null=True,
                help_text=(
                    'Soft-delete timestamp. When set, the homework is hidden '
                    'from all teacher, student and parent views but its '
                    'submissions and grades are preserved in the database.'
                ),
            ),
        ),
        migrations.AddField(
            model_name='homework',
            name='deleted_by',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='+', to=settings.AUTH_USER_MODEL,
                help_text='User who soft-deleted this homework.',
            ),
        ),
    ]
