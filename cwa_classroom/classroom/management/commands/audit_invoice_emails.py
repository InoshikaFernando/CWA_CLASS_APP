"""
Management command: audit_invoice_emails

Reconciles issued invoices against what was actually emailed, so an institute
can answer "who received their invoice and who did not?".

Read-only — it never sends, queues or modifies anything.

Why this is not just a dashboard query: invoice emails are queued
(``issue_invoices`` force-queues every one) and the queue drain writes an
``EmailLog`` without the ``invoice`` foreign key, so the dashboard's Email
column cannot see them. The evidence still exists in three places, which this
command joins back together:

  1. ``EmailQueue``  — one row per recipient per invoice email, never deleted,
     carrying the delivery status (pending / sent / failed).
  2. ``EmailLog``    — written on the invoice FK for invoices issued before the
     queue was introduced, and by subject for everything since.
  3. The invoice's own contacts — a student/parent/guardian with no email
     address on file was never queued at all, and is the silent miss.

Both the queue and the log carry the deterministic subject
``Invoice <number> — <school name>``, and invoice numbers are globally unique,
so the second whitespace-separated token recovers the invoice.

Usage:
    python manage.py audit_invoice_emails
    python manage.py audit_invoice_emails --school wizards --since 2026-07-01
    python manage.py audit_invoice_emails --only-missed --csv /tmp/missed.csv
"""
import csv
import datetime
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from classroom.models import (
    EmailLog, EmailQueue, Invoice, ParentStudent, School, SchoolStudent,
    StudentGuardian,
)

# Invoice states that should have produced an email. Drafts were never issued;
# cancelled invoices get their own (separate) cancellation email.
EMAILABLE_STATUSES = ('issued', 'partially_paid', 'paid')

# Verdicts, worst first — this is also the report's grouping order.
VERDICT_NO_RECIPIENT = 'NO RECIPIENT'    # nobody to email: the silent miss
VERDICT_NEVER_QUEUED = 'NEVER SENT'      # had recipients, no email exists
VERDICT_STUCK = 'STUCK IN QUEUE'         # queued but still pending/failed
VERDICT_BOUNCED = 'BOUNCED'              # provider rejected it
VERDICT_SENT = 'SENT'                    # handed to the provider, or delivered

VERDICT_ORDER = [
    VERDICT_NO_RECIPIENT, VERDICT_NEVER_QUEUED, VERDICT_STUCK,
    VERDICT_BOUNCED, VERDICT_SENT,
]


def _invoice_number_from_subject(subject):
    """Recover the invoice number from 'Invoice INV-3-2026-0007 — School'.

    Returns None for any subject that is not an invoice email.
    """
    if not subject or not subject.startswith('Invoice '):
        return None
    parts = subject.split(None, 2)
    if len(parts) < 2:
        return None
    return parts[1]


def resolve_contacts(invoice):
    """Return the contacts an invoice email would be addressed to today.

    Mirrors the recipient policy used when the invoice is emailed. Returns
    ``(contacts, policy)`` where each contact is ``(label, email_or_None)``.
    Contacts with no address are still listed — they are the reason an invoice
    reaches nobody, so the report has to show them.
    """
    from classroom.invoicing_services import _resolve_invoice_recipients

    student = invoice.student
    school = invoice.school

    primary_dept = None
    primary_classroom = None
    for li in invoice.line_items.select_related(
        'classroom', 'classroom__department',
    ).all():
        if li.classroom:
            primary_classroom = li.classroom
            if li.classroom.department:
                primary_dept = li.classroom.department
            break

    eff = school.get_effective_settings(primary_dept, classroom=primary_classroom)
    policy = eff.get('invoice_recipient_policy', 'parents_fallback_student')

    parent_links = list(
        ParentStudent.objects.filter(
            student=student, school=school, is_active=True,
        ).select_related('parent')
    )
    school_student = SchoolStudent.objects.filter(
        student=student, school=school,
    ).first()
    guardian_links = list(
        StudentGuardian.objects.filter(student=student).select_related('guardian')
    ) if school_student else []

    send_to_student, send_to_parents = _resolve_invoice_recipients(
        policy, parent_links, guardian_links,
    )

    contacts = []
    if send_to_student:
        contacts.append(('student', student.email))
    if send_to_parents:
        for link in parent_links:
            contacts.append(
                (f'parent:{link.parent.get_full_name() or link.parent.username}',
                 link.parent.email),
            )
        for sg in guardian_links:
            contacts.append(
                (f'guardian:{sg.guardian.first_name} {sg.guardian.last_name}'.strip(),
                 sg.guardian.email),
            )
    return contacts, policy


class Command(BaseCommand):
    help = 'Reconcile issued invoices against the emails actually sent for them.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--school', help='Limit to one school by slug.',
        )
        parser.add_argument(
            '--since', help='Only invoices issued on/after this date (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--until', help='Only invoices issued on/before this date (YYYY-MM-DD).',
        )
        parser.add_argument(
            '--only-missed', action='store_true',
            help='Show only invoices nobody received (NO RECIPIENT / NEVER SENT / STUCK).',
        )
        parser.add_argument(
            '--csv', dest='csv_path',
            help='Also write the full per-invoice result to this CSV path.',
        )

    def _parse_date(self, value, label):
        try:
            return datetime.date.fromisoformat(value)
        except ValueError:
            raise CommandError(f'--{label} must be YYYY-MM-DD, got {value!r}')

    def handle(self, *args, **options):
        invoices = (
            Invoice.objects
            .filter(status__in=EMAILABLE_STATUSES)
            .select_related('student', 'school')
            .order_by('school__name', 'invoice_number')
        )

        if options['school']:
            school = School.objects.filter(slug=options['school']).first()
            if not school:
                raise CommandError(f'No school with slug {options["school"]!r}.')
            invoices = invoices.filter(school=school)

        if options['since']:
            invoices = invoices.filter(
                issued_at__date__gte=self._parse_date(options['since'], 'since'))
        if options['until']:
            invoices = invoices.filter(
                issued_at__date__lte=self._parse_date(options['until'], 'until'))

        invoices = list(invoices)
        if not invoices:
            self.stdout.write('No issued invoices match the given filters.')
            return

        numbers = {inv.invoice_number for inv in invoices}

        # --- Evidence 1: queue rows, matched back by subject -----------------
        queued_by_number = defaultdict(list)
        for row in EmailQueue.objects.filter(
            notification_type='invoice',
        ).only('subject', 'recipient_email', 'status', 'created_at', 'sent_at'):
            number = _invoice_number_from_subject(row.subject)
            if number in numbers:
                queued_by_number[number].append(row)

        # --- Evidence 2: email logs, by FK (pre-queue) or subject (since) ----
        logs_by_number = defaultdict(list)
        for log in EmailLog.objects.filter(
            Q(invoice__invoice_number__in=numbers)
            | Q(notification_type='invoice'),
        ).select_related('invoice').only(
            'subject', 'recipient_email', 'status', 'sent_at', 'bounce_reason',
            'invoice__invoice_number',
        ):
            number = (
                log.invoice.invoice_number if log.invoice_id
                else _invoice_number_from_subject(log.subject)
            )
            if number in numbers:
                logs_by_number[number].append(log)

        rows = []
        for invoice in invoices:
            contacts, policy = resolve_contacts(invoice)
            addressable = [email for _, email in contacts if email]
            queued = queued_by_number.get(invoice.invoice_number, [])
            logs = logs_by_number.get(invoice.invoice_number, [])

            log_states = {l.status for l in logs}
            queue_states = {q.status for q in queued}

            if not queued and not logs:
                verdict = VERDICT_NO_RECIPIENT if not addressable else VERDICT_NEVER_QUEUED
            elif log_states & {'bounced', 'complained', 'failed'}:
                verdict = VERDICT_BOUNCED
            elif queue_states & {EmailQueue.STATUS_PENDING, EmailQueue.STATUS_FAILED}:
                verdict = VERDICT_STUCK
            else:
                verdict = VERDICT_SENT

            reached = sorted({
                l.recipient_email for l in logs if l.status not in ('failed',)
            } | {
                q.recipient_email for q in queued if q.status == EmailQueue.STATUS_SENT
            })

            rows.append({
                'verdict': verdict,
                'school': invoice.school.name,
                'invoice_number': invoice.invoice_number,
                'student': invoice.student.get_full_name() or invoice.student.username,
                'issued_at': invoice.issued_at.date().isoformat() if invoice.issued_at else '',
                'period': f'{invoice.billing_period_start} to {invoice.billing_period_end}',
                'amount': str(invoice.amount),
                'policy': policy,
                'contacts_on_file': '; '.join(
                    f'{label}={email or "NO EMAIL"}' for label, email in contacts
                ) or 'none',
                'reached': '; '.join(reached),
                'bounce_reason': '; '.join(
                    sorted({l.bounce_reason for l in logs if l.bounce_reason})
                ),
            })

        self._report(rows, only_missed=options['only_missed'])

        if options['csv_path']:
            self._write_csv(rows, options['csv_path'])

    def _report(self, rows, only_missed):
        by_verdict = defaultdict(list)
        for row in rows:
            by_verdict[row['verdict']].append(row)

        self.stdout.write('')
        self.stdout.write(f'Invoice email audit — {len(rows)} issued invoice(s) examined')
        self.stdout.write('=' * 78)
        for verdict in VERDICT_ORDER:
            self.stdout.write(f'  {verdict:<16} {len(by_verdict[verdict]):>5}')
        self.stdout.write('')

        missed_verdicts = (VERDICT_NO_RECIPIENT, VERDICT_NEVER_QUEUED, VERDICT_STUCK)
        show = missed_verdicts if only_missed else VERDICT_ORDER

        for verdict in show:
            group = by_verdict[verdict]
            if not group:
                continue
            self.stdout.write(f'--- {verdict} ({len(group)}) ---')
            for row in group:
                self.stdout.write(
                    f'  {row["invoice_number"]}  {row["student"]}  '
                    f'issued {row["issued_at"]}  ${row["amount"]}  [{row["school"]}]'
                )
                self.stdout.write(f'      policy: {row["policy"]}')
                self.stdout.write(f'      contacts: {row["contacts_on_file"]}')
                if row['reached']:
                    self.stdout.write(f'      reached: {row["reached"]}')
                if row['bounce_reason']:
                    self.stdout.write(f'      bounce: {row["bounce_reason"]}')
            self.stdout.write('')

        total_missed = sum(len(by_verdict[v]) for v in missed_verdicts)
        if total_missed:
            self.stdout.write(
                f'{total_missed} invoice(s) reached nobody. Fix the contact '
                f'details listed above, then use Resend on each invoice.'
            )
        else:
            self.stdout.write('Every issued invoice in scope reached at least one recipient.')

    def _write_csv(self, rows, path):
        fieldnames = [
            'verdict', 'school', 'invoice_number', 'student', 'issued_at',
            'period', 'amount', 'policy', 'contacts_on_file', 'reached',
            'bounce_reason',
        ]
        with open(path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        self.stdout.write(f'Wrote {len(rows)} row(s) to {path}')
