"""
Add School.default_fee — school-wide fallback fee for the fee cascade.

Fee cascade is now:
  ClassStudent.fee_override
  → ClassRoom.fee_override
  → DepartmentLevel.fee_override
  → DepartmentSubject.fee_override
  → Department.default_fee
  → School.default_fee   ← NEW
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classroom', '0087_nullable_bank_account_gst_overrides'),
    ]

    operations = [
        migrations.AddField(
            model_name='school',
            name='default_fee',
            field=models.DecimalField(
                blank=True,
                decimal_places=2,
                help_text='School-wide default fee per session. Used when no class, level, subject, or department fee is configured.',
                max_digits=8,
                null=True,
            ),
        ),
    ]
