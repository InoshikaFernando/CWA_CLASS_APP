"""
Management command: send_due_messages

Enqueues all SCHEDULED ScheduledMessage rows whose next_run_at <= now into RQ.
Run via cron every minute:

    * * * * * /path/to/python manage.py send_due_messages
"""
import logging

from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Enqueue due scheduled messages into the RQ default queue.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print how many messages are due without enqueuing.',
        )

    def handle(self, *args, **options):
        from classroom.tasks_messaging import check_due_messages
        from classroom.models import ScheduledMessage
        from django.utils import timezone

        if options['dry_run']:
            now = timezone.now()
            count = ScheduledMessage.objects.filter(
                status=ScheduledMessage.STATUS_SCHEDULED,
                next_run_at__lte=now,
            ).count()
            self.stdout.write(f'[dry-run] {count} message(s) would be enqueued.')
            return

        count = check_due_messages()
        self.stdout.write(f'Enqueued {count} message(s).')
