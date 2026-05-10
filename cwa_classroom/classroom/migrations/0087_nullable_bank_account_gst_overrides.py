"""
Make bank_account_number and gst_number nullable on Department and ClassRoom.

NULL now explicitly means "no override — inherit from parent level", which is
semantically cleaner than the previous empty-string convention and matches the
get_resolved_account_number() / get_resolved_gst() resolution chain.

Existing empty strings are left as-is; the resolution methods treat both
NULL and '' as "no override", so no data migration is required.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0086_parentstudent_school_nullable'),
    ]

    operations = [
        # Department.bank_account_number
        migrations.AlterField(
            model_name='department',
            name='bank_account_number',
            field=models.CharField(
                blank=True,
                help_text='Account number override for invoices. Null = inherit from school.',
                max_length=30,
                null=True,
            ),
        ),
        # Department.gst_number
        migrations.AlterField(
            model_name='department',
            name='gst_number',
            field=models.CharField(
                blank=True,
                help_text='GST/VAT number override. Null = inherit from school.',
                max_length=50,
                null=True,
                verbose_name='GST / VAT Number',
            ),
        ),
        # ClassRoom.bank_account_number
        migrations.AlterField(
            model_name='classroom',
            name='bank_account_number',
            field=models.CharField(
                blank=True,
                help_text='Account number override for invoices. Null = inherit from department.',
                max_length=30,
                null=True,
            ),
        ),
        # ClassRoom.gst_number
        migrations.AlterField(
            model_name='classroom',
            name='gst_number',
            field=models.CharField(
                blank=True,
                help_text='GST/VAT number override. Null = inherit from department.',
                max_length=50,
                null=True,
                verbose_name='GST / VAT Number',
            ),
        ),
    ]
