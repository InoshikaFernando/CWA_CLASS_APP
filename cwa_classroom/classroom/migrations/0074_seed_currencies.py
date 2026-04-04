from django.db import migrations


CURRENCIES = [
    # code, name, symbol, symbol_position, decimal_places
    ('AUD', 'Australian Dollar',      '$',  'before', 2),
    ('CAD', 'Canadian Dollar',        '$',  'before', 2),
    ('EUR', 'Euro',                   '€',  'before', 2),
    ('GBP', 'British Pound Sterling', '£',  'before', 2),
    ('INR', 'Indian Rupee',           '₹',  'before', 2),
    ('JPY', 'Japanese Yen',           '¥',  'before', 0),
    ('KRW', 'South Korean Won',       '₩',  'before', 0),
    ('NZD', 'New Zealand Dollar',     '$',  'before', 2),
    ('SGD', 'Singapore Dollar',       '$',  'before', 2),
    ('USD', 'United States Dollar',   '$',  'before', 2),
    ('ZAR', 'South African Rand',     'R',  'before', 2),
]


def seed_currencies(apps, schema_editor):
    Currency = apps.get_model('classroom', 'Currency')
    for code, name, symbol, symbol_position, decimal_places in CURRENCIES:
        Currency.objects.get_or_create(
            code=code,
            defaults={
                'name': name,
                'symbol': symbol,
                'symbol_position': symbol_position,
                'decimal_places': decimal_places,
                'is_active': True,
            },
        )


def unseed_currencies(apps, schema_editor):
    Currency = apps.get_model('classroom', 'Currency')
    Currency.objects.filter(code__in=[c[0] for c in CURRENCIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0073_currency'),
    ]

    operations = [
        migrations.RunPython(seed_currencies, reverse_code=unseed_currencies),
    ]
