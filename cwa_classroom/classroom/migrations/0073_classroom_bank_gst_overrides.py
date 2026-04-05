from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0072_term_holidays'),
    ]

    operations = [
        migrations.AddField(
            model_name='classroom',
            name='bank_name',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='classroom',
            name='bank_bsb',
            field=models.CharField(blank=True, max_length=20, verbose_name='BSB'),
        ),
        migrations.AddField(
            model_name='classroom',
            name='bank_account_number',
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name='classroom',
            name='bank_account_name',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='classroom',
            name='gst_number',
            field=models.CharField(blank=True, max_length=50, verbose_name='GST / VAT Number'),
        ),
    ]
