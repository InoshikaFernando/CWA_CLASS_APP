"""
Management command to auto-publish scheduled homework.

Run via cron every 5 minutes on PythonAnywhere:
    */5 * * * * python manage.py publish_scheduled_homework
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from homework.models import Homework


class Command(BaseCommand):
    help = 'Publish homework assignments that have reached their scheduled publish time.'

    def handle(self, *args, **options):
        now = timezone.now()
        count = Homework.objects.filter(
            status=Homework.STATUS_SCHEDULED,
            scheduled_publish_at__lte=now,
            is_active=True,
        ).update(
            status=Homework.STATUS_ACTIVE,
            published_at=now,
        )

        if count:
            self.stdout.write(
                self.style.SUCCESS(f'Published {count} scheduled homework(s).')
            )
        else:
            self.stdout.write('No scheduled homework to publish.')
