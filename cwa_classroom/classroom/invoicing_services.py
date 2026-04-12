"""
Invoicing business logic — fee resolution, invoice calculation, payment
processing, fuzzy matching, and credit management.
"""
import csv
import difflib
import io
import logging
import re
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

from .models import (
    ClassRoom, ClassSession, ClassStudent, StudentAttendance,
    DepartmentFee, StudentFeeOverride, InvoiceNumberSequence,
    Invoice, InvoiceLineItem, InvoicePayment, CreditTransaction,
    PaymentReferenceMapping, CSVImport, SchoolStudent,
    SchoolHoliday, PublicHoliday,
    ParentStudent, StudentGuardian,
)
from .fee_utils import get_effective_fee_for_student, get_fee_source_label


# ---------------------------------------------------------------------------
# Fee Resolution
# ---------------------------------------------------------------------------

def resolve_daily_rate(student, classroom, billing_period_end):
    """
    Returns (daily_rate, rate_source) or (None, None) if no fee configured.
    Uses the fee cascade: ClassStudent → ClassRoom → Level → Subject → Department.
    """
    class_student = ClassStudent.objects.filter(
        classroom=classroom, student=student, is_active=True,
    ).first()

    if not class_student:
        return None, None

    fee = get_effective_fee_for_student(class_student)
    if fee is not None:
        source = get_fee_source_label(class_student)
        # Map source labels to rate_source codes
        if 'Student' in source:
            return fee, 'student_override'
        else:
            return fee, 'class_default'

    return None, None


# ---------------------------------------------------------------------------
# Attendance Validation
# ---------------------------------------------------------------------------

def validate_attendance_complete(school, billing_period_start, billing_period_end,
                                  department=None):
    """
    Checks that all completed sessions have attendance for every enrolled student.
    Returns list of dicts: {session, classroom, missing_students}
    Empty list means all attendance is marked.
    """
    sessions_qs = ClassSession.objects.filter(
        classroom__school=school,
        status='completed',
        date__range=(billing_period_start, billing_period_end),
    ).select_related('classroom')

    if department:
        sessions_qs = sessions_qs.filter(classroom__department=department)

    unmarked = []
    for session in sessions_qs:
        enrolled_students = set(
            ClassStudent.objects.filter(
                classroom=session.classroom,
                joined_at__date__lte=session.date,
                is_active=True,
            ).values_list('student_id', flat=True)
        )
        marked_students = set(
            StudentAttendance.objects.filter(
                session=session,
            ).values_list('student_id', flat=True)
        )
        missing = enrolled_students - marked_students
        if missing:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            missing_users = User.objects.filter(id__in=missing)
            unmarked.append({
                'session': session,
                'classroom': session.classroom,
                'missing_students': list(missing_users),
            })

    return unmarked


# ---------------------------------------------------------------------------
# Overlapping Invoice Check
# ---------------------------------------------------------------------------

def check_overlapping_invoices(student, school, billing_period_start, billing_period_end):
    """
    Returns queryset of non-cancelled invoices that overlap with the given period.
    """
    return Invoice.objects.filter(
        student=student,
        school=school,
        billing_period_start__lte=billing_period_end,
        billing_period_end__gte=billing_period_start,
    ).exclude(status='cancelled')


def find_uncovered_date_ranges(issued_invoices, request_start, request_end):
    """
    Given a collection of issued invoices and a requested billing window
    [request_start, request_end], return a list of (start, end) date pairs
    representing the portions of the window NOT already covered by those invoices.

    Example:
        issued: Jan 6–20
        request: Jan 1–31
        → uncovered: [(Jan 1, Jan 5), (Jan 21, Jan 31)]

    Returns an empty list when the invoices fully cover the requested window.
    """
    # Clip each invoice's interval to the requested window
    covered = sorted(
        (
            max(inv.billing_period_start, request_start),
            min(inv.billing_period_end,   request_end),
        )
        for inv in issued_invoices
        if inv.billing_period_start <= request_end
        and inv.billing_period_end >= request_start
    )

    # Merge overlapping/adjacent covered intervals
    merged = []
    for cov_start, cov_end in covered:
        if merged and cov_start <= merged[-1][1] + timedelta(days=1):
            merged[-1] = (merged[-1][0], max(merged[-1][1], cov_end))
        else:
            merged.append((cov_start, cov_end))

    # Collect gaps between/around the merged covered intervals
    gaps = []
    cursor = request_start
    for cov_start, cov_end in merged:
        if cursor < cov_start:
            gaps.append((cursor, cov_start - timedelta(days=1)))
        cursor = cov_end + timedelta(days=1)

    if cursor <= request_end:
        gaps.append((cursor, request_end))

    return gaps


# ---------------------------------------------------------------------------
# Invoice Line Calculation
# ---------------------------------------------------------------------------

_DAY_MAP = {
    'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
    'friday': 4, 'saturday': 5, 'sunday': 6,
}


def ensure_sessions_for_period(school, billing_period_start, billing_period_end, created_by=None):
    """
    Auto-generate scheduled sessions for all active classrooms in the billing
    period.  Skips dates that already have a session and dates that fall on
    school or public holidays.  Only creates sessions for classrooms that have
    a day/time schedule configured.

    Returns the number of new sessions created.
    """
    classrooms = (
        ClassRoom.objects
        .filter(school=school, is_active=True)
        .exclude(day='')
        .exclude(start_time__isnull=True)
        .exclude(end_time__isnull=True)
    )

    if not classrooms.exists():
        return 0

    # Build set of holiday dates to skip
    holiday_dates = set()
    school_holidays = SchoolHoliday.objects.filter(
        school=school,
        start_date__lte=billing_period_end,
        end_date__gte=billing_period_start,
    )
    for h in school_holidays:
        d = max(h.start_date, billing_period_start)
        while d <= min(h.end_date, billing_period_end):
            holiday_dates.add(d)
            d += timedelta(days=1)

    public_holidays = PublicHoliday.objects.filter(
        school=school,
        date__range=(billing_period_start, billing_period_end),
    )
    for h in public_holidays:
        holiday_dates.add(h.date)

    # Existing sessions — avoid duplicates
    existing_keys = set(
        ClassSession.objects
        .filter(classroom__in=classrooms,
                date__range=(billing_period_start, billing_period_end))
        .values_list('classroom_id', 'date')
    )

    to_create = []
    for classroom in classrooms:
        target_wd = _DAY_MAP.get(classroom.day)
        if target_wd is None:
            continue
        # First occurrence of this weekday on or after period start
        days_ahead = (target_wd - billing_period_start.weekday()) % 7
        session_date = billing_period_start + timedelta(days=days_ahead)

        while session_date <= billing_period_end:
            if (session_date not in holiday_dates
                    and (classroom.pk, session_date) not in existing_keys):
                to_create.append(ClassSession(
                    classroom=classroom,
                    date=session_date,
                    start_time=classroom.start_time,
                    end_time=classroom.end_time,
                    status='scheduled',
                    created_by=created_by,
                ))
            session_date += timedelta(weeks=1)

    if to_create:
        ClassSession.objects.bulk_create(to_create, ignore_conflicts=True)

    return len(to_create)


def sync_sessions_for_school(school, created_by=None):
    """
    Synchronise scheduled sessions with the current academic year / term dates.

    1. Creates missing scheduled sessions within all current term date ranges.
    2. Deletes future *scheduled* sessions that now fall outside any term range
       (only sessions with no attendance recorded and no linked invoice).

    Call this after editing academic year dates, term dates, or holidays.
    Returns (created_count, deleted_count).
    """
    from datetime import date as _date
    from .models import Term, StudentAttendance

    today = _date.today()

    terms = Term.objects.filter(
        school=school,
        end_date__gte=today,  # only current/future terms
    ).order_by('start_date')

    if not terms.exists():
        return 0, 0

    classrooms = (
        ClassRoom.objects
        .filter(school=school, is_active=True)
        .exclude(day='')
        .exclude(start_time__isnull=True)
        .exclude(end_time__isnull=True)
    )

    if not classrooms.exists():
        return 0, 0

    # Collect all valid date ranges from terms
    term_ranges = []
    overall_start = None
    overall_end = None
    for term in terms:
        # Only create sessions from today onwards
        effective_start = max(term.start_date, today)
        if effective_start <= term.end_date:
            term_ranges.append((effective_start, term.end_date))
            if overall_start is None or effective_start < overall_start:
                overall_start = effective_start
            if overall_end is None or term.end_date > overall_end:
                overall_end = term.end_date

    if not term_ranges:
        return 0, 0

    # Build set of holiday dates
    holiday_dates = set()
    school_holidays = SchoolHoliday.objects.filter(
        school=school,
        start_date__lte=overall_end,
        end_date__gte=overall_start,
    )
    for h in school_holidays:
        d = max(h.start_date, overall_start)
        while d <= min(h.end_date, overall_end):
            holiday_dates.add(d)
            d += timedelta(days=1)

    public_holidays = PublicHoliday.objects.filter(
        school=school,
        date__range=(overall_start, overall_end),
    )
    for h in public_holidays:
        holiday_dates.add(h.date)

    # --- CREATE missing sessions within term ranges ---
    existing_keys = set(
        ClassSession.objects
        .filter(classroom__in=classrooms,
                date__range=(overall_start, overall_end))
        .values_list('classroom_id', 'date')
    )

    to_create = []
    valid_dates_by_classroom = {}  # track which dates should have sessions

    for classroom in classrooms:
        target_wd = _DAY_MAP.get(classroom.day)
        if target_wd is None:
            continue

        classroom_valid_dates = set()
        for range_start, range_end in term_ranges:
            days_ahead = (target_wd - range_start.weekday()) % 7
            session_date = range_start + timedelta(days=days_ahead)
            while session_date <= range_end:
                if session_date not in holiday_dates:
                    classroom_valid_dates.add(session_date)
                    if (classroom.pk, session_date) not in existing_keys:
                        to_create.append(ClassSession(
                            classroom=classroom,
                            date=session_date,
                            start_time=classroom.start_time,
                            end_time=classroom.end_time,
                            status='scheduled',
                            created_by=created_by,
                        ))
                session_date += timedelta(weeks=1)

        valid_dates_by_classroom[classroom.pk] = classroom_valid_dates

    if to_create:
        ClassSession.objects.bulk_create(to_create, ignore_conflicts=True)

    # --- DELETE future scheduled sessions that are now outside term ranges ---
    # Only delete sessions that: are in the future, are 'scheduled', have no
    # attendance records, and are not linked to any invoice line items.
    from .models import InvoiceLineItem

    # Session IDs that have attendance — keep these
    attended_ids = set(
        StudentAttendance.objects.filter(
            session__classroom__in=classrooms,
            session__date__gte=today,
        ).values_list('session_id', flat=True)
    )

    # Classroom+date pairs covered by an invoice — keep these
    invoiced_pairs = set()
    for li in InvoiceLineItem.objects.filter(
        classroom__in=classrooms,
        invoice__billing_period_end__gte=today,
    ).select_related('invoice'):
        inv = li.invoice
        d = max(inv.billing_period_start, today)
        while d <= inv.billing_period_end:
            invoiced_pairs.add((li.classroom_id, d))
            d += timedelta(days=1)

    orphan_sessions = (
        ClassSession.objects
        .filter(
            classroom__in=classrooms,
            date__gte=today,
            status='scheduled',
        )
        .exclude(id__in=attended_ids)
    )

    deleted_count = 0
    for session in orphan_sessions:
        valid_dates = valid_dates_by_classroom.get(session.classroom_id, set())
        if session.date not in valid_dates:
            if (session.classroom_id, session.date) not in invoiced_pairs:
                session.delete()
                deleted_count += 1

    return len(to_create), deleted_count


def calculate_invoice_lines(student, school, billing_period_start, billing_period_end,
                             attendance_mode, billing_type='post_term', department=None):
    """
    Returns (lines, warnings) where:
    - lines: list of dicts with per-class breakdown
    - warnings: list of dicts for classes with no fee configured

    billing_type:
    - 'post_term': charges based on completed sessions and attendance
    - 'upfront': charges based on all scheduled (non-cancelled) sessions,
      ignoring attendance (for invoicing at term start)

    department:
    - When set, only classrooms belonging to that department produce line items.
      This ensures that scoping an invoice run to a single department does not
      inadvertently include the student's classes in other departments.
    """
    enrollments = ClassStudent.objects.filter(
        classroom__school=school,
        student=student,
        is_active=True,
    ).select_related('classroom', 'classroom__department')

    if department is not None:
        enrollments = enrollments.filter(classroom__department=department)

    lines = []
    warnings = []

    for enrollment in enrollments:
        classroom = enrollment.classroom
        if not classroom.is_active:
            continue

        # Use full billing period — don't restrict by joined_at.
        # If a student has attendance marked for a session, they should be
        # charged for it even if they were formally enrolled after that date.
        all_sessions = ClassSession.objects.filter(
            classroom=classroom,
            date__range=(billing_period_start, billing_period_end),
        ).exclude(status='cancelled')

        if billing_type == 'upfront':
            # Upfront: count all scheduled (non-cancelled) sessions
            sessions_held = all_sessions.count()
            sessions_attended = 0
            sessions_charged = sessions_held
        else:
            # Post-term: only completed sessions count as held
            sessions_held = all_sessions.filter(status='completed').count()

            # Count attendance from ALL non-cancelled sessions (not just completed).
            # This also handles sessions where attendance was marked but status
            # is still 'scheduled'.
            sessions_attended = StudentAttendance.objects.filter(
                session__in=all_sessions,
                student=student,
                status__in=['present', 'late'],
            ).count()

            if attendance_mode == 'all_class_days':
                sessions_charged = sessions_held
            else:
                sessions_charged = sessions_attended

        if sessions_held == 0 and sessions_attended == 0:
            continue

        daily_rate, rate_source = resolve_daily_rate(
            student, classroom, billing_period_end
        )

        if daily_rate is None:
            warnings.append({
                'classroom': classroom,
                'department': classroom.department,
                'student': student,
            })
            continue

        line_amount = daily_rate * sessions_charged

        lines.append({
            'classroom': classroom,
            'department': classroom.department,
            'daily_rate': daily_rate,
            'rate_source': rate_source,
            'sessions_held': sessions_held,
            'sessions_attended': sessions_attended,
            'sessions_charged': sessions_charged,
            'line_amount': line_amount,
        })

    return lines, warnings


# ---------------------------------------------------------------------------
# Invoice Number Generation
# ---------------------------------------------------------------------------

def generate_invoice_number(school, year=None):
    """
    Atomically increments and returns next invoice number.
    Format: INV-{school_id}-{year}-{sequential:04d}
    """
    if year is None:
        year = timezone.now().year

    seq, _ = InvoiceNumberSequence.objects.select_for_update().get_or_create(
        school=school, year=year, defaults={'last_number': 0}
    )
    seq.last_number += 1
    seq.save()
    return f'INV-{school.id}-{year}-{seq.last_number:04d}'


# ---------------------------------------------------------------------------
# Opening Balance
# ---------------------------------------------------------------------------

def set_opening_balance(school_student, amount):
    """
    Set opening balance for a student.
    Positive = student owes money (added to first invoice).
    Negative = student has credit (creates a CreditTransaction).
    Zero = clears any previously set balance.
    """
    if amount < 0:
        # Negative balance = student has credit from before
        CreditTransaction.objects.create(
            student=school_student.student,
            school=school_student.school,
            amount=abs(amount),
            reason='opening_balance',
        )
        school_student.opening_balance = Decimal('0.00')
    else:
        school_student.opening_balance = amount
    school_student.save(update_fields=['opening_balance'])


# ---------------------------------------------------------------------------
# Draft Invoice Creation
# ---------------------------------------------------------------------------

def create_draft_invoices(school, student_data, attendance_mode,
                           billing_period_start, billing_period_end, created_by,
                           billing_type='post_term', period_type='custom'):
    """
    Creates draft Invoice + InvoiceLineItem records.
    student_data: list of {
        student, lines,
        custom_amount (optional), notes (optional),
        period_start (optional override), period_end (optional override),
    }
    Per-student period_start/period_end override the global billing period for
    that student's invoice (used for supplementary gap invoices).
    period_type: 'custom', 'month', 'term', or 'year'
    Returns list of created Invoice objects.
    """
    invoices = []

    with transaction.atomic():
        for data in student_data:
            student = data['student']
            lines = data['lines']
            calculated_amount = sum(l['line_amount'] for l in lines)
            amount = data.get('custom_amount', calculated_amount)
            notes = data.get('notes', '')

            # Per-student period override (supplementary/gap invoices)
            inv_period_start = data.get('period_start', billing_period_start)
            inv_period_end   = data.get('period_end',   billing_period_end)

            invoice_number = generate_invoice_number(school, inv_period_end.year)

            invoice = Invoice.objects.create(
                invoice_number=invoice_number,
                school=school,
                student=student,
                billing_period_start=inv_period_start,
                billing_period_end=inv_period_end,
                attendance_mode=attendance_mode,
                billing_type=billing_type,
                period_type=period_type,
                calculated_amount=calculated_amount,
                amount=amount,
                status='draft',
                notes=notes,
                created_by=created_by,
            )

            for line in lines:
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    classroom=line['classroom'],
                    department=line.get('department'),
                    daily_rate=line['daily_rate'],
                    rate_source=line['rate_source'],
                    sessions_held=line['sessions_held'],
                    sessions_attended=line['sessions_attended'],
                    sessions_charged=line['sessions_charged'],
                    line_amount=line['line_amount'],
                )

            # Add opening balance line item if student has one
            school_student = SchoolStudent.objects.filter(
                school=school, student=student,
            ).first()
            if school_student and school_student.opening_balance > 0:
                ob = school_student.opening_balance
                InvoiceLineItem.objects.create(
                    invoice=invoice,
                    classroom=None,
                    department=None,
                    daily_rate=Decimal('0.00'),
                    rate_source='opening_balance',
                    sessions_held=0,
                    sessions_attended=0,
                    sessions_charged=0,
                    line_amount=ob,
                )
                invoice.calculated_amount += ob
                invoice.amount += ob
                invoice.save(update_fields=['calculated_amount', 'amount'])
                # Consume the opening balance
                school_student.opening_balance = Decimal('0.00')
                school_student.save(update_fields=['opening_balance'])

            invoices.append(invoice)

    # Track invoice usage for subscription billing
    if invoices:
        from billing.entitlements import record_invoice_usage
        record_invoice_usage(school, len(invoices))

    return invoices


# ---------------------------------------------------------------------------
# Issue Invoices
# ---------------------------------------------------------------------------

def issue_invoices(invoice_ids, user):
    """
    Moves draft invoices to issued. Auto-applies credits.
    Sends email notification to each student.
    Returns list of issued invoices.
    """
    invoices = Invoice.objects.filter(
        id__in=invoice_ids, status='draft',
    ).select_related('student', 'school')
    issued = []

    with transaction.atomic():
        now = timezone.now()
        for invoice in invoices:
            invoice.status = 'issued'
            invoice.issued_at = now
            # Get department for effective settings
            first_li = invoice.line_items.select_related(
                'classroom__department'
            ).filter(classroom__department__isnull=False).first()
            dept = first_li.classroom.department if first_li else None
            eff = invoice.school.get_effective_settings(dept)
            due_days = eff.get('invoice_due_days') or 30
            invoice.due_date = now.date() + timedelta(days=due_days)
            invoice.save(update_fields=[
                'status', 'issued_at', 'due_date', 'updated_at',
            ])

            credit_applied = apply_credits_to_invoice(invoice)
            if credit_applied > 0:
                _update_invoice_payment_status(invoice)

            issued.append(invoice)

    # Send email notifications (outside transaction)
    for invoice in issued:
        _send_invoice_email(invoice)

    return issued


def _send_invoice_email(invoice):
    """Send invoice issued email to the student."""
    from .email_service import send_templated_email

    student = invoice.student
    if not student.email:
        return

    school = invoice.school
    line_items = invoice.line_items.select_related('classroom', 'classroom__department').all()

    # Determine the primary department and classroom for settings overrides
    # (use the first line item's classroom/department if available)
    primary_dept = None
    primary_classroom = None
    for li in line_items:
        if li.classroom:
            primary_classroom = li.classroom
            if li.classroom.department:
                primary_dept = li.classroom.department
            break

    # Get effective settings (department then classroom overrides applied)
    eff = school.get_effective_settings(primary_dept, classroom=primary_classroom)

    # Format dates
    invoice_date = ''
    if invoice.issued_at:
        invoice_date = invoice.issued_at.strftime('%b %d, %Y')
    due_date = ''
    if invoice.due_date:
        due_date = invoice.due_date.strftime('%b %d, %Y')

    billing_period = (
        f"{invoice.billing_period_start.strftime('%b %d')} - "
        f"{invoice.billing_period_end.strftime('%b %d, %Y')}"
    )

    # Get student ID code
    school_student = SchoolStudent.objects.filter(
        student=student, school=school,
    ).first()
    student_id_code = school_student.student_id_code if school_student else ''

    context = {
        # School header
        'school_name': school.name,
        'school_address': school.address or '',
        'school_phone': school.phone or '',
        'school_email': school.email or '',
        'abn': eff.get('abn', ''),
        'gst_number': eff.get('gst_number', ''),
        # Student
        'student_name': f'{student.first_name} {student.last_name}'.strip(),
        'student_id_code': student_id_code,
        # Invoice details
        'invoice_number': invoice.invoice_number,
        'invoice_date': invoice_date,
        'due_date': due_date,
        'amount_due': invoice.amount_due,
        # Reference
        'billing_period': billing_period,
        # Line items
        'line_items': [
            {
                'classroom': li.classroom.name if li.classroom else 'Opening Balance',
                'description': (
                    'Balance carried forward'
                    if li.rate_source == 'opening_balance'
                    else billing_period
                ),
                'sessions_charged': (
                    li.sessions_charged
                    if li.rate_source != 'opening_balance'
                    else ''
                ),
                'daily_rate': (
                    li.daily_rate
                    if li.rate_source != 'opening_balance'
                    else ''
                ),
                'line_amount': li.line_amount,
                'is_opening_balance': li.rate_source == 'opening_balance',
            }
            for li in line_items
        ],
        'total': invoice.calculated_amount,
        # Bank details (with department overrides applied)
        'bank_account_name': eff.get('bank_account_name', ''),
        'bank_bsb': eff.get('bank_bsb', ''),
        'bank_account_number': eff.get('bank_account_number', ''),
        'bank_name': eff.get('bank_name', ''),
        # Terms & Notes (with department overrides applied)
        'invoice_terms': eff.get('invoice_terms', ''),
        'notes': invoice.notes or '',
    }

    subject = f'Invoice {invoice.invoice_number} — {school.name}'
    sent_emails = set()

    # 1. Send to student
    try:
        send_templated_email(
            recipient_email=student.email,
            subject=subject,
            template_name='email/transactional/invoice_issued.html',
            context=context,
            recipient_user=student,
            notification_type='invoice',
            school=school,
            department=primary_dept,
        )
        sent_emails.add(student.email.lower())
    except Exception as e:
        logger.exception('Failed to send invoice email for %s: %s', invoice.invoice_number, e)

    # 2. Send to parent accounts (ParentStudent links)
    parent_links = ParentStudent.objects.filter(
        student=student, school=school, is_active=True,
    ).select_related('parent')
    for link in parent_links:
        if link.parent.email and link.parent.email.lower() not in sent_emails:
            try:
                send_templated_email(
                    recipient_email=link.parent.email,
                    subject=subject,
                    template_name='email/transactional/invoice_issued.html',
                    context=context,
                    recipient_user=link.parent,
                    notification_type='invoice',
                )
                sent_emails.add(link.parent.email.lower())
            except Exception as e:
                logger.exception('Failed to send invoice email to parent %s: %s', link.parent.email, e)

    # 3. Send to guardian contacts (StudentGuardian links)
    school_student = SchoolStudent.objects.filter(student=student, school=school).first()
    if school_student:
        guardian_links = StudentGuardian.objects.filter(
            student=student,
        ).select_related('guardian')
        for sg in guardian_links:
            if sg.guardian.email and sg.guardian.email.lower() not in sent_emails:
                try:
                    send_templated_email(
                        recipient_email=sg.guardian.email,
                        subject=subject,
                        template_name='email/transactional/invoice_issued.html',
                        context=context,
                        notification_type='invoice',
                    )
                    sent_emails.add(sg.guardian.email.lower())
                except Exception as e:
                    logger.exception('Failed to send invoice email to guardian %s: %s', sg.guardian.email, e)


# ---------------------------------------------------------------------------
# Cancel Invoice
# ---------------------------------------------------------------------------

def cancel_invoice(invoice, reason, cancelled_by):
    """
    Cancels an invoice. Unlinks confirmed payments as credits.
    """
    with transaction.atomic():
        confirmed_payments = invoice.payments.filter(status='confirmed')
        for payment in confirmed_payments:
            CreditTransaction.objects.create(
                student=invoice.student,
                school=invoice.school,
                amount=payment.amount,
                reason='invoice_cancelled',
                related_payment=payment,
                related_invoice=invoice,
            )
            payment.invoice = None
            payment.save(update_fields=['invoice'])

        invoice.status = 'cancelled'
        invoice.cancelled_by = cancelled_by
        invoice.cancelled_at = timezone.now()
        invoice.cancellation_reason = reason
        invoice.save(update_fields=[
            'status', 'cancelled_by', 'cancelled_at', 'cancellation_reason', 'updated_at'
        ])


# ---------------------------------------------------------------------------
# Payment Recording
# ---------------------------------------------------------------------------

def record_payment(invoice, amount, payment_date, payment_method='bank_transfer',
                    reference_name='', bank_transaction_id='', csv_import=None,
                    notes='', created_by=None, status='confirmed'):
    """
    Creates InvoicePayment, updates invoice status, handles overpayment → credit.
    """
    with transaction.atomic():
        payment = InvoicePayment.objects.create(
            invoice=invoice,
            student=invoice.student,
            school=invoice.school,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            reference_name=reference_name,
            bank_transaction_id=bank_transaction_id,
            csv_import=csv_import,
            status=status,
            notes=notes,
            created_by=created_by,
        )

        if status == 'confirmed' and invoice:
            total_paid = invoice.amount_paid
            overpayment = total_paid - invoice.amount
            if overpayment > 0:
                CreditTransaction.objects.create(
                    student=invoice.student,
                    school=invoice.school,
                    amount=overpayment,
                    reason='overpayment',
                    related_payment=payment,
                    related_invoice=invoice,
                )
            _update_invoice_payment_status(invoice)

    return payment


def _update_invoice_payment_status(invoice):
    """Auto-updates invoice status based on total payments."""
    total_paid = invoice.amount_paid
    if total_paid >= invoice.amount:
        new_status = 'paid'
    elif total_paid > 0:
        new_status = 'partially_paid'
    else:
        return

    if invoice.status in ('issued', 'partially_paid') and invoice.status != new_status:
        invoice.status = new_status
        invoice.save(update_fields=['status', 'updated_at'])


# ---------------------------------------------------------------------------
# Credit Balance
# ---------------------------------------------------------------------------

def get_credit_balance(student, school):
    """Returns current credit balance as Decimal."""
    result = CreditTransaction.objects.filter(
        student=student, school=school,
    ).aggregate(total=models.Sum('amount'))
    return result['total'] or Decimal('0.00')


def apply_credits_to_invoice(invoice):
    """
    Auto-applies available credit balance to reduce amount due.
    Creates a negative CreditTransaction. Returns amount applied.
    """
    balance = get_credit_balance(invoice.student, invoice.school)
    if balance <= 0:
        return Decimal('0.00')

    amount_due = invoice.amount_due
    if amount_due <= 0:
        return Decimal('0.00')

    apply_amount = min(balance, amount_due)

    CreditTransaction.objects.create(
        student=invoice.student,
        school=invoice.school,
        amount=-apply_amount,
        reason='applied_to_invoice',
        related_invoice=invoice,
    )

    InvoicePayment.objects.create(
        invoice=invoice,
        student=invoice.student,
        school=invoice.school,
        amount=apply_amount,
        payment_date=timezone.now().date(),
        payment_method='other',
        reference_name='Credit applied',
        status='confirmed',
    )

    return apply_amount


# ---------------------------------------------------------------------------
# Reference Name Matching (Fuzzy)
# ---------------------------------------------------------------------------

def normalize_reference(reference_name):
    """Trim, collapse spaces, lowercase."""
    ref = reference_name.strip().lower()
    ref = re.sub(r'\s+', ' ', ref)
    return ref


def tokenize_reference(reference_name):
    """Split by spaces, commas, &, 'and'. Return list of non-empty tokens."""
    normalized = normalize_reference(reference_name)
    tokens = re.split(r'[\s,&]+|(?:\band\b)', normalized)
    return [t.strip() for t in tokens if t and t.strip()]


def fuzzy_match_students(reference_name, school):
    """
    Returns list of (student, confidence_score) tuples sorted by score desc.
    First checks exact mapping, then falls back to fuzzy token matching.
    """
    normalized = normalize_reference(reference_name)

    mapping = PaymentReferenceMapping.objects.filter(
        school=school, reference_name=normalized,
    ).first()
    if mapping:
        if mapping.is_ignored:
            return []
        if mapping.student:
            return [(mapping.student, 1.0)]

    tokens = tokenize_reference(reference_name)
    if not tokens:
        return []

    school_students = SchoolStudent.objects.filter(
        school=school, is_active=True,
    ).select_related('student')

    student_scores = {}

    for ss in school_students:
        user = ss.student
        first = (user.first_name or '').lower()
        last = (user.last_name or '').lower()

        best_score = 0.0
        matched_tokens = 0

        for token in tokens:
            first_score = difflib.SequenceMatcher(None, token, first).ratio() if first else 0
            last_score = difflib.SequenceMatcher(None, token, last).ratio() if last else 0
            token_best = max(first_score, last_score)
            if token_best >= 0.6:
                matched_tokens += 1
                best_score = max(best_score, token_best)

        if matched_tokens > 0:
            confidence = best_score * (matched_tokens / len(tokens))
            if confidence >= 0.4:
                student_scores[user] = confidence

    results = sorted(student_scores.items(), key=lambda x: x[1], reverse=True)
    return results[:10]


# ---------------------------------------------------------------------------
# CSV Processing
# ---------------------------------------------------------------------------

MAX_CSV_SIZE = 10 * 1024 * 1024  # 10MB
MAX_CSV_ROWS = 10000


def parse_csv_file(file_content):
    """
    Parses CSV content string. Returns (headers, rows) or raises ValueError.
    """
    try:
        content = file_content.decode('utf-8')
    except UnicodeDecodeError:
        content = file_content.decode('latin-1')

    # Normalise line endings to avoid csv reader errors
    content = content.replace('\r\n', '\n').replace('\r', '\n')

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    if len(rows) < 2:
        raise ValueError('CSV file must have at least a header row and one data row.')

    if len(rows) - 1 > MAX_CSV_ROWS:
        raise ValueError(f'CSV exceeds maximum of {MAX_CSV_ROWS} rows.')

    headers = rows[0]
    data_rows = rows[1:]
    return headers, data_rows


def parse_xls_file_invoicing(file_content):
    """Parse .xls file for invoicing. Returns (headers, data_rows)."""
    try:
        import xlrd
    except ImportError:
        raise ValueError('XLS support requires the xlrd package. Install with: pip install xlrd')

    wb = xlrd.open_workbook(file_contents=file_content)
    sh = wb.sheet_by_index(0)
    if sh.nrows < 2:
        raise ValueError('XLS file must have at least a header row and one data row.')
    if sh.nrows - 1 > MAX_CSV_ROWS:
        raise ValueError(f'XLS exceeds maximum of {MAX_CSV_ROWS} rows.')

    headers = [str(sh.cell_value(0, c)).strip() for c in range(sh.ncols)]
    data_rows = []
    for r in range(1, sh.nrows):
        row = []
        for c in range(sh.ncols):
            cell = sh.cell(r, c)
            if cell.ctype == xlrd.XL_CELL_DATE:
                try:
                    dt = xlrd.xldate_as_datetime(cell.value, wb.datemode)
                    row.append(dt.strftime('%Y-%m-%d'))
                except Exception:
                    row.append(str(cell.value))
            elif cell.ctype == xlrd.XL_CELL_NUMBER:
                if cell.value == int(cell.value):
                    row.append(str(int(cell.value)))
                else:
                    row.append(str(cell.value))
            else:
                row.append(str(cell.value).strip())
        data_rows.append(row)
    return headers, data_rows


def parse_upload_file_invoicing(file_content, filename):
    """Route to correct parser based on file extension."""
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'csv'
    if ext == 'xls':
        return parse_xls_file_invoicing(file_content)
    elif ext == 'xlsx':
        raise ValueError('XLSX format is not supported. Please save as .xls or export as .csv.')
    else:
        return parse_csv_file(file_content)


def process_csv_rows(data_rows, column_mapping, school):
    """
    Processes parsed CSV rows through the matching pipeline.
    column_mapping: {date_col, amount_col, reference_col, transaction_id_col, amount_type}
    Returns dict with categorized results.
    """
    date_col = column_mapping['date_col']
    amount_col = column_mapping['amount_col']
    reference_col = column_mapping['reference_col']
    transaction_id_col = column_mapping.get('transaction_id_col')
    amount_type = column_mapping.get('amount_type', 'credit')

    auto_matched = []
    multi_match = []
    unmatched = []
    skipped = []
    duplicates = []

    seen_transaction_ids = set()

    for i, row in enumerate(data_rows):
        if len(row) <= max(date_col, amount_col, reference_col):
            skipped.append({'row_index': i, 'row': row, 'reason': 'Incomplete row'})
            continue

        raw_amount = row[amount_col].strip().replace(',', '').replace('$', '')
        try:
            amount = Decimal(raw_amount)
        except Exception:
            skipped.append({'row_index': i, 'row': row, 'reason': 'Invalid amount'})
            continue

        if amount_type == 'credit' and amount <= 0:
            skipped.append({'row_index': i, 'row': row, 'reason': 'Non-credit amount'})
            continue
        elif amount_type == 'debit' and amount >= 0:
            skipped.append({'row_index': i, 'row': row, 'reason': 'Non-debit amount'})
            continue

        amount = abs(amount)

        transaction_id = ''
        if transaction_id_col is not None and len(row) > transaction_id_col:
            transaction_id = row[transaction_id_col].strip()

        if transaction_id:
            if transaction_id in seen_transaction_ids:
                duplicates.append({
                    'row_index': i, 'row': row, 'reason': 'Duplicate transaction ID'
                })
                continue
            seen_transaction_ids.add(transaction_id)

            existing = InvoicePayment.objects.filter(
                school=school, bank_transaction_id=transaction_id,
            ).exists()
            if existing:
                duplicates.append({
                    'row_index': i, 'row': row, 'reason': 'Already imported'
                })
                continue

        reference = row[reference_col].strip()
        date_str = row[date_col].strip()

        entry = {
            'row_index': i,
            'reference': reference,
            'amount': amount,
            'date_str': date_str,
            'transaction_id': transaction_id,
        }

        matches = fuzzy_match_students(reference, school)

        if matches and matches[0][1] >= 0.8:
            if len(matches) >= 2 and matches[1][1] >= 0.6:
                entry['candidates'] = [(s, round(sc * 100)) for s, sc in matches[:5]]
                multi_match.append(entry)
            else:
                entry['student'] = matches[0][0]
                entry['confidence'] = round(matches[0][1] * 100)
                auto_matched.append(entry)
        elif matches:
            entry['candidates'] = [(s, round(sc * 100)) for s, sc in matches[:5]]
            unmatched.append(entry)
        else:
            entry['candidates'] = []
            unmatched.append(entry)

    return {
        'auto_matched': auto_matched,
        'multi_match': multi_match,
        'unmatched': unmatched,
        'skipped': skipped,
        'duplicates': duplicates,
    }
