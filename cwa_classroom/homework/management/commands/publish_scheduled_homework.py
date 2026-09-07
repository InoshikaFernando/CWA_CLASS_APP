"""
Auto-publish scheduled homework whose publish time has arrived.

Installed by deploy/setup-app-prod.sh as /etc/cron.d/cwa-publish-homework,
running every 5 minutes (see cwa_classroom/MANAGEMENT_COMMANDS.md):
    */5 * * * * cwa cd /home/cwa/CWA_CLASS_APP && venv/bin/python cwa_classroom/manage.py publish_scheduled_homework

This command is the ONLY thing that sets published_at on a scheduled
homework, and students gate on published_at — so if the cron is missing,
every scheduled set is created, stays invisible, and is never sent, with
nothing erroring anywhere.
"""

from django.core.management.base import BaseCommand
from django.utils import timezone

from homework.models import Homework


class Command(BaseCommand):
    help = 'Publish homework whose scheduled publish_at time has been reached.'

    def handle(self, *args, **options):
        now = timezone.now()
        due = Homework.objects.filter(
            published_at__isnull=True,
            publish_at__isnull=False,
            publish_at__lte=now,
        )

        count = 0
        for homework in due:
            # publish() sets published_at and notifies students (in-app + email).
            # Idempotent, so a re-run never double-sends.
            homework.publish()
            count += 1

        if count:
            self.stdout.write(self.style.SUCCESS(f'Published {count} scheduled homework(s).'))
        else:
            self.stdout.write('No scheduled homework to publish.')
