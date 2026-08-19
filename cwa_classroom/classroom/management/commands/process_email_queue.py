"""
Management command: process_email_queue

Drains the EmailQueue table up to the remaining daily sending quota.

This command IS the delivery path for every invoice email — invoices are
force-queued at issue time — so if it stops running, invoices are marked
issued and silently never sent. Install it via the /etc/cron.d/cwa-email
drop-in written by deploy/setup-app-prod.sh; do not hand-add it to a crontab.

    */2 * * * * cwa /home/cwa/CWA_CLASS_APP/scripts/cron_process_email_queue.sh \
        /home/cwa/CWA_CLASS_APP /etc/cwa/cwa.env >> /var/log/cwa/email_queue.log 2>&1
"""
import logging

from django.core.mail import EmailMultiAlternatives
from django.core.management.base import BaseCommand
from django.utils import timezone

from classroom.email_service import DAILY_EMAIL_LIMIT
from classroom.models import EmailLog, EmailQueue, Invoice

logger = logging.getLogger(__name__)

# How many times a row may be attempted before it is left alone. Without a cap
# a permanently undeliverable address is retried on every run forever, cannot be
# suppressed, and writes a fresh failed EmailLog each time.
MAX_ATTEMPTS = 5


def _invoice_number_from_subject(subject):
    """'Invoice INV-4-2026-1524 — Maths Hub' -> 'INV-4-2026-1524'."""
    if not subject or not subject.startswith('Invoice '):
        return None
    parts = subject.split(None, 2)
    return parts[1] if len(parts) >= 2 else None


def _resolve_attribution(queued, invoice_cache):
    """Return (school, invoice) to stamp on this row's EmailLog.

    Prefers the foreign keys carried on the queue row. Rows queued before those
    columns existed have neither, so fall back to the invoice number embedded in
    the deterministic subject line — that repairs the attribution of an existing
    backlog as it drains, instead of writing yet more unattributable logs.
    """
    if queued.invoice_id:
        return queued.school, queued.invoice
    if queued.notification_type != 'invoice':
        return queued.school, None

    number = _invoice_number_from_subject(queued.subject)
    if not number:
        return queued.school, None
    if number not in invoice_cache:
        invoice_cache[number] = (
            Invoice.objects.select_related('school')
            .filter(invoice_number=number).first()
        )
    invoice = invoice_cache[number]
    if invoice is None:
        return queued.school, None
    return queued.school or invoice.school, invoice


class Command(BaseCommand):
    help = 'Send queued emails up to the remaining daily limit.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Print what would be sent without actually sending.',
        )
        parser.add_argument(
            '--limit', type=int,
            help='Send at most this many emails this run (on top of the daily cap).',
        )

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        today = timezone.now().date()

        # Retry rows that failed but have attempts left. Rows at the cap stay
        # failed so a dead address cannot loop, and so an operator can suppress
        # one by setting attempts past the cap.
        retried = EmailQueue.objects.filter(
            status=EmailQueue.STATUS_FAILED,
            sent_at__isnull=True,
            attempts__lt=MAX_ATTEMPTS,
        ).update(status=EmailQueue.STATUS_PENDING, error_message='')
        if retried:
            self.stdout.write(f'Reset {retried} failed email(s) to pending for retry.')

        exhausted = EmailQueue.objects.filter(
            status=EmailQueue.STATUS_FAILED,
            sent_at__isnull=True,
            attempts__gte=MAX_ATTEMPTS,
        ).count()
        if exhausted:
            self.stdout.write(
                f'{exhausted} email(s) left failed after {MAX_ATTEMPTS} attempts '
                f'— not retried. Fix the address and requeue if still needed.'
            )

        queue = EmailQueue.objects.filter(
            status=EmailQueue.STATUS_PENDING,
        ).order_by('created_at')

        # DAILY_EMAIL_LIMIT <= 0 means no cap — drain the whole queue.
        if DAILY_EMAIL_LIMIT > 0:
            sent_today = EmailLog.objects.filter(status='sent', sent_at__date=today).count()
            remaining = DAILY_EMAIL_LIMIT - sent_today
            if remaining <= 0:
                self.stdout.write(
                    f'Daily limit already reached ({sent_today}/{DAILY_EMAIL_LIMIT}). Nothing sent.')
                return
            pending = list(queue[:remaining])
            limit_note = f'{sent_today} already sent today, limit {DAILY_EMAIL_LIMIT}'
        else:
            pending = list(queue)
            limit_note = 'no daily limit'

        if options['limit'] is not None:
            pending = pending[:options['limit']]
            limit_note += f", --limit {options['limit']}"

        if not pending:
            self.stdout.write('No queued emails to send.')
            return

        # A backlog means the cron stopped; say so rather than draining quietly.
        oldest = pending[0].created_at
        age_hours = (timezone.now() - oldest).total_seconds() / 3600
        if age_hours > 1:
            msg = (
                f'Oldest queued email is {age_hours:.1f}h old ({oldest:%Y-%m-%d %H:%M} UTC) '
                f'— the queue was not being drained on schedule.'
            )
            self.stdout.write(self.style.WARNING(msg))
            logger.warning('process_email_queue: %s', msg)

        self.stdout.write(f'Sending {len(pending)} queued email(s) ({limit_note}).')

        sent = 0
        failed = 0
        invoice_cache = {}

        for queued in pending:
            if dry_run:
                self.stdout.write(
                    f'  [dry-run] Would send to {queued.recipient_email}: {queued.subject}')
                continue

            school, invoice = _resolve_attribution(queued, invoice_cache)
            queued.attempts += 1
            queued.last_attempt_at = timezone.now()

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
                queued.save(update_fields=[
                    'status', 'sent_at', 'attempts', 'last_attempt_at',
                ])

                EmailLog.objects.create(
                    recipient=queued.recipient,
                    recipient_email=queued.recipient_email,
                    subject=queued.subject,
                    notification_type=queued.notification_type,
                    campaign=queued.campaign,
                    school=school,
                    invoice=invoice,
                    status='sent',
                    # Correlation key for the Resend delivery webhooks. Dropping
                    # it here left every queued email permanently un-tracked.
                    provider_message_id=getattr(msg, 'resend_message_id', ''),
                )
                sent += 1

            except Exception as e:
                logger.exception(
                    'process_email_queue: failed to send to %s: %s', queued.recipient_email, e)
                queued.status = EmailQueue.STATUS_FAILED
                queued.error_message = str(e)
                queued.save(update_fields=[
                    'status', 'error_message', 'attempts', 'last_attempt_at',
                ])

                EmailLog.objects.create(
                    recipient=queued.recipient,
                    recipient_email=queued.recipient_email,
                    subject=queued.subject,
                    notification_type=queued.notification_type,
                    campaign=queued.campaign,
                    school=school,
                    invoice=invoice,
                    status='failed',
                    error_message=str(e),
                )
                failed += 1

        self.stdout.write(f'Done. Sent: {sent}, Failed: {failed}.')
