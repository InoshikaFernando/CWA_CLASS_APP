"""
Management command: flag_undelivered_emails

Catches emails that Resend accepted (status='sent') but never confirmed
delivered via webhook within a grace window — the silent failures that
'sent' alone would hide. Run via cron, e.g. every 15 minutes:

    */15 * * * * /home/cwa/CWA_CLASS_APP/venv/bin/python manage.py flag_undelivered_emails

These rows are reported (logged) so an admin can investigate. We deliberately
do NOT mutate their status — 'sent' remains truthful (Resend did accept it);
the point is visibility into deliveries that stalled.
"""
import logging
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.models import EmailLog

logger = logging.getLogger(__name__)

DEFAULT_GRACE_MINUTES = 20


class Command(BaseCommand):
    help = 'Report emails accepted by Resend but never confirmed delivered.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes', type=int, default=DEFAULT_GRACE_MINUTES,
            help=f'Grace window before flagging (default {DEFAULT_GRACE_MINUTES}).',
        )
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print the report without logging a warning.',
        )

    def handle(self, *args, **options):
        minutes = options['minutes']
        dry_run = options['dry_run']
        cutoff = timezone.now() - timedelta(minutes=minutes)

        # 'sent' = accepted by Resend but no terminal webhook yet. A delivered/
        # opened/clicked/bounced event would have advanced the status away from
        # 'sent', so anything still 'sent' past the cutoff is unconfirmed.
        # Only consider rows we can actually correlate (have a provider id).
        stuck = EmailLog.objects.filter(
            status='sent',
            sent_at__lt=cutoff,
        ).exclude(provider_message_id='').order_by('sent_at')

        count = stuck.count()
        if not count:
            self.stdout.write(f'No unconfirmed emails older than {minutes} min.')
            return

        self.stdout.write(
            f'{count} email(s) accepted but not confirmed delivered after {minutes} min:'
        )
        for log in stuck[:50]:
            self.stdout.write(
                f'  #{log.id} {log.recipient_email} — "{log.subject}" '
                f'(sent {log.sent_at:%Y-%m-%d %H:%M}, id={log.provider_message_id})'
            )
        if count > 50:
            self.stdout.write(f'  ... and {count - 50} more.')

        if not dry_run:
            logger.warning(
                '%d email(s) accepted by Resend but not confirmed delivered after %d min.',
                count, minutes,
            )
