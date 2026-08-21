"""
audit_invoice_emails_readonly.py — paste-and-run invoice email reconciliation.

READ-ONLY. Sends nothing, queues nothing, changes nothing. Safe on production.

Answers "who received their invoice and who did not?" without needing a deploy:
run it through `manage.py shell` on the droplet against the live database.

    cd /home/cwa/CWA_CLASS_APP
    venv/bin/python cwa_classroom/manage.py shell \
        < scripts/audit_invoice_emails_readonly.py

Filters come from the environment so the script itself needs no editing:

    AUDIT_SINCE=2026-07-01 AUDIT_SCHOOL=wizards \
        venv/bin/python cwa_classroom/manage.py shell \
        < scripts/audit_invoice_emails_readonly.py

    AUDIT_SINCE   YYYY-MM-DD, only invoices issued on/after this date
    AUDIT_UNTIL   YYYY-MM-DD, only invoices issued on/before this date
    AUDIT_SCHOOL  school slug, defaults to every school
    AUDIT_CSV     path to also write a CSV, e.g. /tmp/invoice_email_audit.csv

Why this cannot be read off the dashboard: invoice emails are force-queued, and
the queue drain writes an EmailLog with no invoice foreign key, so the Email
column shows "never emailed" for every invoice regardless of the truth. This
script rejoins the evidence by the deterministic subject line
"Invoice <number> — <school>" plus the invoice's own contact records.
"""
import csv
import datetime
import os
from collections import defaultdict

from django.db.models import Q

from classroom.invoicing_services import _resolve_invoice_recipients
from classroom.models import (
    EmailLog, EmailQueue, Invoice, ParentStudent, School, SchoolStudent,
    StudentGuardian,
)

EMAILABLE_STATUSES = ('issued', 'partially_paid', 'paid')

NO_RECIPIENT = 'NO RECIPIENT'    # nobody on file has an email address
NEVER_SENT = 'NEVER SENT'        # contactable, but no email was ever created
STUCK = 'STUCK IN QUEUE'         # queued, still pending or failed
BOUNCED = 'BOUNCED'              # the provider rejected it
SENT = 'SENT'                    # handed to the provider / delivered
ORDER = [NO_RECIPIENT, NEVER_SENT, STUCK, BOUNCED, SENT]
MISSED = (NO_RECIPIENT, NEVER_SENT, STUCK)


def invoice_number_from_subject(subject):
    """'Invoice INV-3-2026-0007 — Wizards' -> 'INV-3-2026-0007'."""
    if not subject or not subject.startswith('Invoice '):
        return None
    parts = subject.split(None, 2)
    return parts[1] if len(parts) >= 2 else None


def resolve_contacts(invoice):
    """Who this invoice would be addressed to, including contacts with no email."""
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

    parent_links = list(ParentStudent.objects.filter(
        student=student, school=school, is_active=True,
    ).select_related('parent'))
    school_student = SchoolStudent.objects.filter(
        student=student, school=school,
    ).first()
    guardian_links = list(StudentGuardian.objects.filter(
        student=student,
    ).select_related('guardian')) if school_student else []

    send_to_student, send_to_parents = _resolve_invoice_recipients(
        policy, parent_links, guardian_links,
    )

    contacts = []
    if send_to_student:
        contacts.append(('student', student.email))
    if send_to_parents:
        for link in parent_links:
            name = link.parent.get_full_name() or link.parent.username
            contacts.append((f'parent:{name}', link.parent.email))
        for sg in guardian_links:
            name = f'{sg.guardian.first_name} {sg.guardian.last_name}'.strip()
            contacts.append((f'guardian:{name}', sg.guardian.email))
    return contacts, policy


def main():
    since = os.environ.get('AUDIT_SINCE')
    until = os.environ.get('AUDIT_UNTIL')
    slug = os.environ.get('AUDIT_SCHOOL')
    csv_path = os.environ.get('AUDIT_CSV')

    invoices = (
        Invoice.objects
        .filter(status__in=EMAILABLE_STATUSES)
        .select_related('student', 'school')
        .order_by('school__name', 'invoice_number')
    )
    if slug:
        school = School.objects.filter(slug=slug).first()
        if not school:
            print(f'No school with slug {slug!r}. Known slugs:')
            for s in School.objects.order_by('name').values_list('slug', 'name'):
                print(f'  {s[0]}  ({s[1]})')
            return
        invoices = invoices.filter(school=school)
    if since:
        invoices = invoices.filter(issued_at__date__gte=datetime.date.fromisoformat(since))
    if until:
        invoices = invoices.filter(issued_at__date__lte=datetime.date.fromisoformat(until))

    invoices = list(invoices)
    if not invoices:
        print('No issued invoices match those filters.')
        return

    numbers = {inv.invoice_number for inv in invoices}

    queued_by_number = defaultdict(list)
    for row in EmailQueue.objects.filter(notification_type='invoice').only(
        'subject', 'recipient_email', 'status', 'created_at', 'sent_at',
    ):
        number = invoice_number_from_subject(row.subject)
        if number in numbers:
            queued_by_number[number].append(row)

    logs_by_number = defaultdict(list)
    for log in EmailLog.objects.filter(
        Q(invoice__invoice_number__in=numbers) | Q(notification_type='invoice'),
    ).select_related('invoice').only(
        'subject', 'recipient_email', 'status', 'sent_at', 'bounce_reason',
        'invoice__invoice_number',
    ):
        number = (
            log.invoice.invoice_number if log.invoice_id
            else invoice_number_from_subject(log.subject)
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
            verdict = NEVER_SENT if addressable else NO_RECIPIENT
        elif log_states & {'bounced', 'complained', 'failed'}:
            verdict = BOUNCED
        elif queue_states & {EmailQueue.STATUS_PENDING, EmailQueue.STATUS_FAILED}:
            verdict = STUCK
        else:
            verdict = SENT

        reached = sorted(
            {l.recipient_email for l in logs if l.status != 'failed'}
            | {q.recipient_email for q in queued if q.status == EmailQueue.STATUS_SENT}
        )

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

    by_verdict = defaultdict(list)
    for row in rows:
        by_verdict[row['verdict']].append(row)

    print('')
    print(f'Invoice email audit — {len(rows)} issued invoice(s) examined')
    if since or until or slug:
        print(f'  filters: school={slug or "all"} since={since or "-"} until={until or "-"}')
    print('=' * 78)
    for verdict in ORDER:
        print(f'  {verdict:<16} {len(by_verdict[verdict]):>5}')
    print('')

    for verdict in ORDER:
        group = by_verdict[verdict]
        if not group:
            continue
        print(f'--- {verdict} ({len(group)}) ---')
        for row in group:
            print(f'  {row["invoice_number"]}  {row["student"]}  '
                  f'issued {row["issued_at"]}  ${row["amount"]}  [{row["school"]}]')
            print(f'      period:   {row["period"]}')
            print(f'      policy:   {row["policy"]}')
            print(f'      contacts: {row["contacts_on_file"]}')
            if row['reached']:
                print(f'      reached:  {row["reached"]}')
            if row['bounce_reason']:
                print(f'      bounce:   {row["bounce_reason"]}')
        print('')

    total_missed = sum(len(by_verdict[v]) for v in MISSED)
    if total_missed:
        print(f'{total_missed} invoice(s) reached nobody.')
    else:
        print('Every issued invoice in scope reached at least one recipient.')

    if csv_path:
        fieldnames = [
            'verdict', 'school', 'invoice_number', 'student', 'issued_at',
            'period', 'amount', 'policy', 'contacts_on_file', 'reached',
            'bounce_reason',
        ]
        with open(csv_path, 'w', newline='', encoding='utf-8') as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        print(f'Wrote {len(rows)} row(s) to {csv_path}')


main()
