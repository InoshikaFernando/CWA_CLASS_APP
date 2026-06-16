"""
Management command: process_email_queue

Drains the EmailQueue table. The live email path no longer queues emails
(invoices and lifecycle emails send synchronously), so this command is kept
primarily as a one-time tool to flush any backlog left behind by the old
queue, e.g. invoices/welcome emails that were enqueued but never delivered:

    # Send every pending email, ignoring the historical daily cap:
    python manage.py process_email_queue --ignore-daily-limit

    # Preview first:
    python manage.py process_email_queue --ignore-daily-limit --dry-run

Without --ignore-daily-limit it still honours DAILY_EMAIL_LIMIT, matching the
old cron behaviour.
"""
import logging

from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.email_service import DAILY_EMAIL_LIMIT
from classroom.models import EmailLog, EmailQueue

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Send queued emails up to the remaining daily limit.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be sent without actually sending.',
        )
        parser.add_argument(
            '--ignore-daily-limit', action='store_true',
            help='Send every pending email regardless of DAILY_EMAIL_LIMIT '
                 '(use for a one-time backlog flush).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        ignore_limit = options['ignore_daily_limit']
        today = timezone.now().date()

        # Reset previously failed emails back to pending for one retry attempt
        retried = EmailQueue.objects.filter(
            status=EmailQueue.STATUS_FAILED,
            sent_at__isnull=True,
        ).update(status=EmailQueue.STATUS_PENDING, error_message='')
        if retried:
            self.stdout.write(f'Reset {retried} previously failed email(s) to pending for retry.')

        pending_qs = EmailQueue.objects.filter(status=EmailQueue.STATUS_PENDING).order_by('created_at')

        if ignore_limit:
            pending = list(pending_qs)
        else:
            sent_today = EmailLog.objects.filter(status='sent', sent_at__date=today).count()
            remaining = DAILY_EMAIL_LIMIT - sent_today

            if remaining <= 0:
                self.stdout.write(f'Daily limit already reached ({sent_today}/{DAILY_EMAIL_LIMIT}). Nothing sent.')
                return

            pending = list(pending_qs[:remaining])

        if not pending:
            self.stdout.write('No queued emails to send.')
            return

        if ignore_limit:
            self.stdout.write(f'Sending {len(pending)} queued email(s) (daily limit ignored).')
        else:
            self.stdout.write(f'Sending {len(pending)} queued email(s) ({sent_today} already sent today, limit {DAILY_EMAIL_LIMIT}).')

        sent = 0
        failed = 0

        for queued in pending:
            if dry_run:
                self.stdout.write(f'  [dry-run] Would send to {queued.recipient_email}: {queued.subject}')
                continue

            try:
                msg = EmailMultiAlternatives(
                    queued.subject,
                    queued.text_content,
                    queued.from_email,
                    [queued.recipient_email],
                    cc=queued.cc or [],
                    reply_to=queued.reply_to or [],
                )
                msg.attach_alternative(queued.html_content, 'text/html')
                msg.send(fail_silently=False)

                queued.status = EmailQueue.STATUS_SENT
                queued.sent_at = timezone.now()
                queued.save(update_fields=['status', 'sent_at'])

                EmailLog.objects.create(
                    recipient=queued.recipient,
                    recipient_email=queued.recipient_email,
                    subject=queued.subject,
                    notification_type=queued.notification_type,
                    campaign=queued.campaign,
                    status='sent',
                )
                sent += 1

            except Exception as e:
                logger.exception('process_email_queue: failed to send to %s: %s', queued.recipient_email, e)
                queued.status = EmailQueue.STATUS_FAILED
                queued.error_message = str(e)
                queued.save(update_fields=['status', 'error_message'])

                EmailLog.objects.create(
                    recipient=queued.recipient,
                    recipient_email=queued.recipient_email,
                    subject=queued.subject,
                    notification_type=queued.notification_type,
                    campaign=queued.campaign,
                    status='failed',
                    error_message=str(e),
                )
                failed += 1

        self.stdout.write(f'Done. Sent: {sent}, Failed: {failed}.')
