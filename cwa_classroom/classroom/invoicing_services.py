"""
Invoicing business logic — fee resolution, invoice calculation, payment
processing, fuzzy matching, and credit management.
"""
import csv
import difflib
import io
import re
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

from .models import (
    ClassRoom, ClassSession, ClassStudent, StudentAttendance,
    DepartmentFee, StudentFeeOverride, InvoiceNumberSequence,
    Invoice, InvoiceLineItem, InvoicePayment, CreditTransaction,
    PaymentReferenceMapping, CSVImport, SchoolStudent,
)


# ---------------------------------------------------------------------------
# Fee Resolution
# ---------------------------------------------------------------------------

def resolve_daily_rate(student, classroom, billing_period_end):
    """
    Returns (daily_rate, rate_source) or (None, None) if no fee configured.
    Resolution order: student override → department default.
    Rate is resolved against billing_period_end date.
    """
    override = StudentFeeOverride.objects.filter(
        student=student,
        school=classroom.school,
        effective_from__lte=billing_period_end,
    ).order_by('-effective_from').first()

    if override:
        return override.daily_rate, 'student_override'

    if classroom.department_id:
        dept_fee = DepartmentFee.objects.filter(
            department=classroom.department,
            effective_from__lte=billing_period_end,
        ).order_by('-effective_from').first()
        if dept_fee:
            return dept_fee.daily_rate, 'department_default'

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


# ---------------------------------------------------------------------------
# Invoice Line Calculation
# ---------------------------------------------------------------------------

def calculate_invoice_lines(student, school, billing_period_start, billing_period_end,
                             attendance_mode):
    """
    Returns (lines, warnings) where:
    - lines: list of dicts with per-class breakdown
    - warnings: list of dicts for classes with no fee configured
    """
    enrollments = ClassStudent.objects.filter(
        classroom__school=school,
        student=student,
    ).select_related('classroom', 'classroom__department')

    lines = []
    warnings = []

    for enrollment in enrollments:
        classroom = enrollment.classroom
        if not classroom.is_active:
            continue

        joined_date = enrollment.joined_at.date()
        effective_start = max(billing_period_start, joined_date)

        if effective_start > billing_period_end:
            continue

        sessions = ClassSession.objects.filter(
            classroom=classroom,
            status='completed',
            date__range=(effective_start, billing_period_end),
        )
        sessions_held = sessions.count()

        sessions_attended = StudentAttendance.objects.filter(
            session__in=sessions,
            student=student,
            status__in=['present', 'late'],
        ).count()

        if attendance_mode == 'all_class_days':
            sessions_charged = sessions_held
        else:
            sessions_charged = sessions_attended

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
# Draft Invoice Creation
# ---------------------------------------------------------------------------

def create_draft_invoices(school, student_data, attendance_mode,
                           billing_period_start, billing_period_end, created_by):
    """
    Creates draft Invoice + InvoiceLineItem records.
    student_data: list of {student, lines, custom_amount (optional), notes (optional)}
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

            invoice_number = generate_invoice_number(school, billing_period_end.year)

            invoice = Invoice.objects.create(
                invoice_number=invoice_number,
                school=school,
                student=student,
                billing_period_start=billing_period_start,
                billing_period_end=billing_period_end,
                attendance_mode=attendance_mode,
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

            invoices.append(invoice)

    return invoices


# ---------------------------------------------------------------------------
# Issue Invoices
# ---------------------------------------------------------------------------

def issue_invoices(invoice_ids, user):
    """
    Moves draft invoices to issued. Auto-applies credits.
    Returns list of issued invoices.
    """
    invoices = Invoice.objects.filter(id__in=invoice_ids, status='draft')
    issued = []

    with transaction.atomic():
        for invoice in invoices:
            invoice.status = 'issued'
            invoice.save(update_fields=['status', 'updated_at'])

            credit_applied = apply_credits_to_invoice(invoice)
            if credit_applied > 0:
                _update_invoice_payment_status(invoice)

            issued.append(invoice)

    return issued


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

    reader = csv.reader(io.StringIO(content))
    rows = list(reader)

    if len(rows) < 2:
        raise ValueError('CSV file must have at least a header row and one data row.')

    if len(rows) - 1 > MAX_CSV_ROWS:
        raise ValueError(f'CSV exceeds maximum of {MAX_CSV_ROWS} rows.')

    headers = rows[0]
    data_rows = rows[1:]
    return headers, data_rows


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
