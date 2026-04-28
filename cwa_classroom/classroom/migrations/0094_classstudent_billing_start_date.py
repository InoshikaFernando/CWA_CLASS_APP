from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0093_seed_coding_subject'),
    ]

    operations = [
        migrations.AddField(
            model_name='classstudent',
            name='billing_start_date',
            field=models.DateField(
                blank=True,
                help_text=(
                    'First date this student is billable for this class. '
                    'NULL = bill the full requested period (e.g. backdated data entry '
                    "for a student who was already attending). Set to a date when the "
                    'student genuinely starts mid-period — sessions before this date '
                    'will not be billed.'
                ),
                null=True,
            ),
        ),
    ]
