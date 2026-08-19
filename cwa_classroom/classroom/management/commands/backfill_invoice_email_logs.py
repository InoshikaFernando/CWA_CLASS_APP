"""
Management command: backfill_invoice_email_logs

One-off repair for invoice EmailLog rows that were written without their
``invoice`` foreign key.

Every invoice email is force-queued at issue time, and until v1.17.11 the queue
drain created the EmailLog without ``invoice`` or ``school``. The invoicing
dashboard's Email column joins on ``EmailLog.invoice``, so those invoices read
"Not sent" even when the email was delivered — including the 316 emails
recovered on 19 August 2026. The delivery happened; only the record is wrong.

The subject line is deterministic and invoice numbers are globally unique:

    Invoice INV-4-2026-1524 — Maths Hub Melbourne Pty Ltd
    Invoice INV-4-2026-1524 Cancelled — Maths Hub Melbourne Pty Ltd

so the second whitespace-separated token identifies the invoice exactly. This
only ever fills in NULLs — an EmailLog that already has an invoice is never
touched, and no row's status, timestamps or recipient are altered.

``provider_message_id`` is deliberately NOT invented: it was never captured for
these rows, so their Resend delivery state is unrecoverable and they stay at
whatever status they were written with.

Dry-run by default; pass --apply to write.

    python manage.py backfill_invoice_email_logs
    python manage.py backfill_invoice_email_logs --apply
    python manage.py backfill_invoice_email_logs --apply --since 2026-06-01
"""
import datetime
from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from classroom.management.commands.process_email_queue import (
    _invoice_number_from_subject,
)
from classroom.models import EmailLog, Invoice

# The notification types whose subject carries an invoice number.
INVOICE_NOTIFICATION_TYPES = ('invoice', 'invoice_cancelled')

BATCH_SIZE = 500


class Command(BaseCommand):
    help = 'Attach the invoice/school FKs to invoice EmailLog rows that lost them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help='Write the changes. Without this the command only reports.')
        parser.add_argument(
            '--since',
            help='Only rows sent on/after this date (YYYY-MM-DD).')
        parser.add_argument(
            '--limit', type=int,
            help='Process at most this many rows (for a cautious first pass).')

    def handle(self, *args, **opts):
        apply_changes = opts['apply']

        rows = EmailLog.objects.filter(
            notification_type__in=INVOICE_NOTIFICATION_TYPES,
            invoice__isnull=True,
        ).order_by('sent_at')

        if opts['since']:
            try:
                since = datetime.date.fromisoformat(opts['since'])
            except ValueError:
                raise CommandError(f'--since must be YYYY-MM-DD, got {opts["since"]!r}')
            rows = rows.filter(sent_at__date__gte=since)

        if opts['limit']:
            rows = rows[:opts['limit']]

        rows = list(rows)
        if not rows:
            self.stdout.write('No unattributed invoice email logs found — nothing to do.')
            return

        # Resolve every referenced invoice in one query rather than per row.
        numbers = set()
        for log in rows:
            number = _invoice_number_from_subject(log.subject)
            if number:
                numbers.add(number)

        invoices = {
            inv.invoice_number: inv
            for inv in Invoice.objects.filter(
                invoice_number__in=numbers).select_related('school')
        }

        matched = []
        unmatched = Counter()
        for log in rows:
            number = _invoice_number_from_subject(log.subject)
            if not number:
                unmatched['subject not parseable'] += 1
                continue
            invoice = invoices.get(number)
            if invoice is None:
                unmatched['invoice no longer exists'] += 1
                continue
            log.invoice = invoice
            if log.school_id is None:
                log.school = invoice.school
            matched.append(log)

        self.stdout.write(f'Unattributed invoice email logs: {len(rows)}')
        self.stdout.write(f'  matchable to an invoice:       {len(matched)}')
        for reason, count in unmatched.most_common():
            self.stdout.write(f'  skipped ({reason}): {count}')

        if matched:
            affected = {log.invoice_id for log in matched}
            self.stdout.write(
                f'  distinct invoices repaired:    {len(affected)}')
            self.stdout.write('  sample:')
            for log in matched[:5]:
                self.stdout.write(
                    f'    {log.invoice.invoice_number}  {log.recipient_email}  '
                    f'{log.status}  {log.sent_at:%Y-%m-%d %H:%M}')

        if not apply_changes:
            self.stdout.write(
                self.style.WARNING(
                    '\nDry run — nothing written. Re-run with --apply to save.'))
            return

        with transaction.atomic():
            EmailLog.objects.bulk_update(
                matched, ['invoice', 'school'], batch_size=BATCH_SIZE)

        self.stdout.write(self.style.SUCCESS(
            f'\nUpdated {len(matched)} email log(s). The invoicing dashboard '
            f'will now show these invoices as emailed.'))
