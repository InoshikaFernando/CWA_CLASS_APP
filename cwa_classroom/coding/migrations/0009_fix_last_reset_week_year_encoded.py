"""
Migration: fix CodingTimeLog.last_reset_week to be year-encoded.

The old field stored only the ISO week number (1–53), so week 14 of 2027 would
match week 14 of 2026 and never trigger a reset across the year boundary.

The new format is  year * 100 + week  (e.g. 202615), which is unique per year.

Existing rows that already have a non-zero last_reset_week are backfilled by
combining the current year with the stored week number, preserving the weekly
reset boundary for any active sessions.  Rows with last_reset_week=0 (default,
no reset has ever happened) are left as 0 so the first heartbeat naturally
resets the weekly counter.
"""
from django.db import migrations, models
from django.utils import timezone


def backfill_year_encoded_week(apps, schema_editor):
    CodingTimeLog = apps.get_model('coding', 'CodingTimeLog')
    current_year = timezone.now().isocalendar()[0]
    # Only update rows where a week has already been recorded (non-zero).
    for log in CodingTimeLog.objects.exclude(last_reset_week=0):
        old_week = log.last_reset_week
        # If it's already year-encoded (> 9999) leave it alone.
        if old_week <= 53:
            log.last_reset_week = current_year * 100 + old_week
            log.save(update_fields=['last_reset_week'])


class Migration(migrations.Migration):

    dependencies = [
        ('coding', '0008_add_forbidden_code_patterns'),
    ]

    operations = [
        migrations.AlterField(
            model_name='codingtimelog',
            name='last_reset_week',
            field=models.IntegerField(
                default=0,
                help_text='Year-encoded ISO week of last weekly reset (year * 100 + week, e.g. 202615)',
            ),
        ),
        migrations.RunPython(backfill_year_encoded_week, migrations.RunPython.noop),
    ]
