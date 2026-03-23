"""
Salary business logic — rate resolution, salary line calculation,
salary slip generation, payment processing.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.db import models, transaction
from django.utils import timezone

logger = logging.getLogger(__name__)

from .models import (
    ClassRoom, ClassTeacher,
    TeacherHourlyRate, TeacherRateOverride, SalaryNumberSequence,
    SalarySlip, SalarySlipLineItem, SalaryPayment, SchoolTeacher,
)
from attendance.models import ClassSession, TeacherAttendance


# ---------------------------------------------------------------------------
# Rate Resolution
# ---------------------------------------------------------------------------

def resolve_hourly_rate(teacher, school, billing_period_end):
    """
    Returns (hourly_rate, rate_source) or (None, None) if no rate configured.
    Cascade: TeacherRateOverride (per-teacher) → TeacherHourlyRate (school default).
    """
    override = TeacherRateOverride.objects.filter(
        teacher=teacher,
        school=school,
        effective_from__lte=billing_period_end,
    ).order_by('-effective_from').first()

    if override:
        return override.hourly_rate, 'teacher_override'

    default = TeacherHourlyRate.objects.filter(
        school=school,
        effective_from__lte=billing_period_end,
    ).order_by('-effective_from').first()

    if default:
        return default.hourly_rate, 'school_default'

    return None, None


# ---------------------------------------------------------------------------
# Attendance Validation
# ---------------------------------------------------------------------------

def validate_teacher_attendance_complete(school, billing_period_start, billing_period_end,
                                          department=None):
    """
    Checks that all completed sessions have teacher attendance marked
    for every assigned teacher (ClassTeacher).
    Returns list of dicts: {session, classroom, missing_teachers}
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
        assigned_teachers = set(
            ClassTeacher.objects.filter(
                classroom=session.classroom,
            ).values_list('teacher_id', flat=True)
        )
        marked_teachers = set(
            TeacherAttendance.objects.filter(
                session=session,
            ).values_list('teacher_id', flat=True)
        )
        missing = assigned_teachers - marked_teachers
        if missing:
            from django.contrib.auth import get_user_model
            User = get_user_model()
            missing_users = User.objects.filter(id__in=missing)
            unmarked.append({
                'session': session,
                'classroom': session.classroom,
                'missing_teachers': list(missing_users),
            })

    return unmarked


# ---------------------------------------------------------------------------
# Overlapping Salary Slip Check
# ---------------------------------------------------------------------------

def check_overlapping_salary_slips(teacher, school, billing_period_start, billing_period_end):
    """
    Returns queryset of non-cancelled salary slips that overlap with the given period.
    """
    return SalarySlip.objects.filter(
        teacher=teacher,
        school=school,
        billing_period_start__lte=billing_period_end,
        billing_period_end__gte=billing_period_start,
    ).exclude(status='cancelled')


# ---------------------------------------------------------------------------
# Session Hours Calculation
# ---------------------------------------------------------------------------

def _compute_session_hours(session):
    """Returns hours as Decimal for a single ClassSession."""
    start_dt = datetime.combine(session.date, session.start_time)
    end_dt = datetime.combine(session.date, session.end_time)
    if end_dt <= start_dt:
        end_dt += timedelta(days=1)
    delta = end_dt - start_dt
    hours = Decimal(str(delta.total_seconds())) / Decimal('3600')
    return hours.quantize(Decimal('0.01'))


# ---------------------------------------------------------------------------
# Salary Line Calculation
# ---------------------------------------------------------------------------

def calculate_salary_lines(teacher, school, billing_period_start, billing_period_end):
    """
    Returns (lines, warnings) where:
    - lines: list of dicts with per-class breakdown
    - warnings: list of dicts for classes with no hourly rate configured
    """
    assignments = ClassTeacher.objects.filter(
        classroom__school=school,
        teacher=teacher,
    ).select_related('classroom', 'classroom__department')

    lines = []
    warnings = []

    for assignment in assignments:
        classroom = assignment.classroom
        if not classroom.is_active:
            continue

        all_sessions = ClassSession.objects.filter(
            classroom=classroom,
            date__range=(billing_period_start, billing_period_end),
        ).exclude(status='cancelled')

        # Sessions where teacher was present
        attended_session_ids = TeacherAttendance.objects.filter(
            session__in=all_sessions,
            teacher=teacher,
            status='present',
        ).values_list('session_id', flat=True)

        attended_sessions = all_sessions.filter(id__in=attended_session_ids)
        sessions_taught = attended_sessions.count()

        if sessions_taught == 0:
            continue

        # Calculate total hours from actual session times
        total_hours = Decimal('0')
        for session in attended_sessions:
            total_hours += _compute_session_hours(session)

        hours_per_session = (total_hours / sessions_taught).quantize(Decimal('0.01'))

        hourly_rate, rate_source = resolve_hourly_rate(
            teacher, school, billing_period_end
        )

        if hourly_rate is None:
            warnings.append({
                'classroom': classroom,
                'department': classroom.department,
                'teacher': teacher,
            })
            continue

        line_amount = (hourly_rate * total_hours).quantize(Decimal('0.01'))

        lines.append({
            'classroom': classroom,
            'department': classroom.department,
            'hourly_rate': hourly_rate,
            'rate_source': rate_source,
            'sessions_taught': sessions_taught,
            'hours_per_session': hours_per_session,
            'total_hours': total_hours,
            'line_amount': line_amount,
        })

    return lines, warnings


# ---------------------------------------------------------------------------
# Salary Number Generation
# ---------------------------------------------------------------------------

def generate_salary_number(school, year=None):
    """
    Atomically increments and returns next salary slip number.
    Format: SAL-{school_id}-{year}-{sequential:04d}
    """
    if year is None:
        year = timezone.now().year

    seq, _ = SalaryNumberSequence.objects.select_for_update().get_or_create(
        school=school, year=year, defaults={'last_number': 0}
    )
    seq.last_number += 1
    seq.save()
    return f'SAL-{school.id}-{year}-{seq.last_number:04d}'


# ---------------------------------------------------------------------------
# Draft Salary Slip Creation
# ---------------------------------------------------------------------------

def create_draft_salary_slips(school, teacher_data, billing_period_start,
                                billing_period_end, created_by):
    """
    Creates draft SalarySlip + SalarySlipLineItem records.
    teacher_data: list of {teacher, lines, custom_amount (optional), notes (optional)}
    Returns list of created SalarySlip objects.
    """
    slips = []

    with transaction.atomic():
        for data in teacher_data:
            teacher = data['teacher']
            lines = data['lines']
            calculated_amount = sum(l['line_amount'] for l in lines)
            amount = data.get('custom_amount', calculated_amount)
            notes = data.get('notes', '')

            slip_number = generate_salary_number(school, billing_period_end.year)

            slip = SalarySlip.objects.create(
                slip_number=slip_number,
                school=school,
                teacher=teacher,
                billing_period_start=billing_period_start,
                billing_period_end=billing_period_end,
                calculated_amount=calculated_amount,
                amount=amount,
                status='draft',
                notes=notes,
                created_by=created_by,
            )

            for line in lines:
                SalarySlipLineItem.objects.create(
                    salary_slip=slip,
                    classroom=line['classroom'],
                    department=line.get('department'),
                    hourly_rate=line['hourly_rate'],
                    rate_source=line['rate_source'],
                    sessions_taught=line['sessions_taught'],
                    hours_per_session=line['hours_per_session'],
                    total_hours=line['total_hours'],
                    line_amount=line['line_amount'],
                )

            slips.append(slip)

    return slips


# ---------------------------------------------------------------------------
# Issue Salary Slips
# ---------------------------------------------------------------------------

def issue_salary_slips(slip_ids, user):
    """
    Moves draft salary slips to issued.
    Returns list of issued salary slips.
    """
    slips = SalarySlip.objects.filter(
        id__in=slip_ids, status='draft',
    ).select_related('teacher', 'school')
    issued = []

    with transaction.atomic():
        now = timezone.now()
        for slip in slips:
            slip.status = 'issued'
            slip.issued_at = now
            due_days = slip.school.invoice_due_days or 30
            slip.due_date = now.date() + timedelta(days=due_days)
            slip.save(update_fields=[
                'status', 'issued_at', 'due_date', 'updated_at',
            ])
            issued.append(slip)

    return issued


# ---------------------------------------------------------------------------
# Cancel Salary Slip
# ---------------------------------------------------------------------------

def cancel_salary_slip(salary_slip, reason, cancelled_by):
    """Cancels a salary slip."""
    with transaction.atomic():
        salary_slip.status = 'cancelled'
        salary_slip.cancelled_by = cancelled_by
        salary_slip.cancelled_at = timezone.now()
        salary_slip.cancellation_reason = reason
        salary_slip.save(update_fields=[
            'status', 'cancelled_by', 'cancelled_at', 'cancellation_reason', 'updated_at'
        ])


# ---------------------------------------------------------------------------
# Payment Recording
# ---------------------------------------------------------------------------

def record_salary_payment(salary_slip, amount, payment_date, payment_method='bank_transfer',
                           reference_name='', bank_transaction_id='',
                           notes='', created_by=None, status='confirmed'):
    """
    Creates SalaryPayment and updates salary slip status.
    """
    with transaction.atomic():
        payment = SalaryPayment.objects.create(
            salary_slip=salary_slip,
            teacher=salary_slip.teacher,
            school=salary_slip.school,
            amount=amount,
            payment_date=payment_date,
            payment_method=payment_method,
            reference_name=reference_name,
            bank_transaction_id=bank_transaction_id,
            status=status,
            notes=notes,
            created_by=created_by,
        )

        if status == 'confirmed' and salary_slip:
            _update_salary_slip_payment_status(salary_slip)

    return payment


def _update_salary_slip_payment_status(salary_slip):
    """Auto-updates salary slip status based on total payments."""
    total_paid = salary_slip.amount_paid
    if total_paid >= salary_slip.amount:
        new_status = 'paid'
    elif total_paid > 0:
        new_status = 'partially_paid'
    else:
        return

    if salary_slip.status in ('issued', 'partially_paid') and salary_slip.status != new_status:
        salary_slip.status = new_status
        salary_slip.save(update_fields=['status', 'updated_at'])
