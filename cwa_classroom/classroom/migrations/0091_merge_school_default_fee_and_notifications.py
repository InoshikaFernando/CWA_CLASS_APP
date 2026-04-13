"""
Merge migration: reconcile 0088_school_default_fee (School.default_fee field)
with 0090_merge_20260412_2204 (notification_type + earlier branch merges).

Both branches share 0087_nullable_bank_account_gst_overrides as a common
ancestor. This merge migration re-unifies the two leaf nodes so `migrate`
can run cleanly on the test server.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0088_school_default_fee'),
        ('classroom', '0090_merge_20260412_2204'),
    ]

    operations = [
    ]
