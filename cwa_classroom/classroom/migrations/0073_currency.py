from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0072_term_holidays'),
    ]

    operations = [
        migrations.CreateModel(
            name='Currency',
            fields=[
                ('code', models.CharField(
                    max_length=3,
                    primary_key=True,
                    serialize=False,
                    help_text='ISO 4217 three-letter currency code (e.g. NZD, USD).',
                )),
                ('name', models.CharField(
                    max_length=100,
                    help_text='e.g. "New Zealand Dollar"',
                )),
                ('symbol', models.CharField(
                    max_length=5,
                    help_text='e.g. "$", "£", "€"',
                )),
                ('symbol_position', models.CharField(
                    max_length=6,
                    choices=[('before', 'Before amount'), ('after', 'After amount')],
                    default='before',
                )),
                ('decimal_places', models.PositiveSmallIntegerField(
                    default=2,
                    help_text='Number of decimal places (typically 2; 0 for JPY, KRW).',
                )),
                ('is_active', models.BooleanField(
                    default=True,
                    help_text='Only active currencies are shown in dropdowns.',
                )),
            ],
            options={
                'verbose_name': 'Currency',
                'verbose_name_plural': 'Currencies',
                'ordering': ['code'],
            },
        ),
    ]
