from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('billing', '0029_perf_composite_indexes'),
    ]

    operations = [
        migrations.AddField(
            model_name='moduleproduct',
            name='pages_per_month',
            field=models.PositiveIntegerField(
                blank=True,
                help_text='Monthly page quota for AI import modules. NULL = not applicable, 0 = unlimited.',
                null=True,
            ),
        ),
    ]
