"""
Management command to auto-complete expired class sessions.

Sessions are marked 'completed' if:
  - status is 'scheduled'  AND
  - (date is in the past)  OR  (date is today AND end_time < now)

Run via cron / PythonAnywhere scheduled task, e.g. every 15 minutes:
    python manage.py auto_complete_sessions
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.models import ClassSession


class Command(BaseCommand):
    help = 'Auto-complete sessions that have passed their end time.'

    def handle(self, *args, **options):
        now = timezone.localtime()
        today = now.date()
        current_time = now.time()

        # 1. Past-date sessions still marked as 'scheduled'
        past_qs = ClassSession.objects.filter(
            status='scheduled',
            date__lt=today,
        )
        past_count = past_qs.update(status='completed')

        # 2. Today's sessions whose end_time has passed
        today_qs = ClassSession.objects.filter(
            status='scheduled',
            date=today,
            end_time__lt=current_time,
        )
        today_count = today_qs.update(status='completed')

        total = past_count + today_count

        if total:
            self.stdout.write(self.style.SUCCESS(
                f'Auto-completed {total} session(s) '
                f'({past_count} past-date, {today_count} expired today).'
            ))
        else:
            self.stdout.write('No sessions to auto-complete.')
