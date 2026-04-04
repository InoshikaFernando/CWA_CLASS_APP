from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0072_term_holidays'),
    ]

    operations = [
        migrations.AddField(
            model_name='term',
            name='is_confirmed',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='term',
            name='confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
