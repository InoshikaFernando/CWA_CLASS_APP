"""
Invoicing views — fee configuration, invoice generation, payment
reconciliation (CSV + manual), and reference mapping management.
"""
import calendar
import json
import logging
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import models
from django.core.paginator import Paginator
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from audit.services import log_event
from .models import (
    School, Department, ClassRoom, ClassStudent, SchoolStudent, SchoolTeacher,
    DepartmentFee, StudentFeeOverride, Invoice, InvoiceLineItem,
    CSVColumnTemplate, CSVImport, PaymentReferenceMapping,
    InvoicePayment, CreditTransaction, Term, AcademicYear,
)
from .views import RoleRequiredMixin
from . import invoicing_services as svc
from .fee_utils import get_effective_fee_for_class, _get_class_fee_source

logger = logging.getLogger(__name__)


INVOICING_ROLES = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.ACCOUNTANT]


def _get_invoicing_schools(user):
    """Get schools accessible for invoicing (admin OR HoI via SchoolTeacher)."""
    if user.has_role(Role.ACCOUNTANT):
        return School.objects.filter(
            school_teachers__teacher=user, school_teachers__is_active=True,
        ).distinct()
    from .views import _get_user_school_ids
    return School.objects.filter(id__in=_get_user_school_ids(user), is_active=True)


def _get_single_school(user):
    """Get the first available school for the user."""
    schools = _get_invoicing_schools(user)
    return schools.first()


def _parse_date(date_str):
    """Parse a date string from form input. Returns date or None."""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d').date()
    except ValueError:
        return None


# ===========================================================================
# Fee Configuration
# ===========================================================================

class FeeConfigurationView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        departments = Department.objects.filter(school=school, is_active=True)
        classrooms = ClassRoom.objects.filter(
            school=school, is_active=True,
        ).select_related('department', 'subject').order_by('department__name', 'name')

        for cr in classrooms:
            cr.effective_fee = get_effective_fee_for_class(cr)
            cr.fee_source = _get_class_fee_source(cr)

        student_overrides = StudentFeeOverride.objects.filter(
            school=school,
        ).select_related('student').order_by('-effective_from')

        seen = set()
        unique_overrides = []
        for override in student_overrides:
            if override.student_id not in seen:
                seen.add(override.student_id)
                unique_overrides.append(override)

        students = SchoolStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('student').order_by('student__first_name', 'student__last_name')

        return render(request, 'invoicing/fee_configuration.html', {
            'school': school,
            'classrooms': classrooms,
            'student_overrides': unique_overrides,
            'students': students,
        })


class SetClassroomFeeView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request, classroom_id):
        school = _get_single_school(request.user)
        classroom = get_object_or_404(ClassRoom, id=classroom_id, school=school)

        rate_str = request.POST.get('fee_override', '').strip()

        if not rate_str:
            classroom.fee_override = None
            classroom.save(update_fields=['fee_override'])
            log_event(
                user=request.user, school=school, category='data_change',
                action='classroom_fee_cleared',
                detail={'classroom_id': classroom.id, 'classroom': classroom.name},
                request=request,
            )
            messages.success(request, f'Fee cleared for {classroom.name} — will inherit from cascade.')
            return redirect('fee_configuration')

        try:
            fee = Decimal(rate_str)
            if fee < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Fee must be a number >= 0.')
            return redirect('fee_configuration')

        classroom.fee_override = fee
        classroom.save(update_fields=['fee_override'])
        log_event(
            user=request.user, school=school, category='data_change',
            action='classroom_fee_set',
            detail={'classroom_id': classroom.id, 'classroom': classroom.name,
                    'fee_override': str(fee)},
            request=request,
        )
        messages.success(request, f'Fee set for {classroom.name}: ${fee}/session.')
        return redirect('fee_configuration')


class BatchClassroomFeeView(RoleRequiredMixin, View):
    """Batch update fees for multiple classrooms in one POST."""
    required_roles = INVOICING_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            return redirect('fee_configuration')

        classroom_ids_str = request.POST.get('classroom_ids', '')
        if not classroom_ids_str:
            return redirect('fee_configuration')

        classroom_ids = [int(x) for x in classroom_ids_str.split(',') if x.strip().isdigit()]
        updated = 0

        with transaction.atomic():
            for cid in classroom_ids:
                classroom = ClassRoom.objects.filter(id=cid, school=school).first()
                if not classroom:
                    continue
                rate_str = request.POST.get(f'fee_{cid}', '').strip()
                if not rate_str:
                    classroom.fee_override = None
                else:
                    try:
                        classroom.fee_override = Decimal(rate_str)
                    except (InvalidOperation, ValueError):
                        continue
                classroom.save(update_fields=['fee_override'])
                updated += 1

        if updated:
            log_event(
                user=request.user, school=school, category='data_change',
                action='classroom_fees_batch_updated',
                detail={'updated_count': updated,
                        'classroom_ids': classroom_ids},
                request=request,
            )
            messages.success(request, f'{updated} class fee{"s" if updated != 1 else ""} updated.')
        return redirect('fee_configuration')


class BatchOpeningBalanceView(RoleRequiredMixin, View):
    """Batch update opening balances for multiple students in one POST."""
    required_roles = INVOICING_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            return redirect('opening_balances')

        student_ids_str = request.POST.get('student_ids', '')
        if not student_ids_str:
            return redirect('opening_balances')

        student_ids = [int(x) for x in student_ids_str.split(',') if x.strip().isdigit()]
        updated = 0

        with transaction.atomic():
            for sid in student_ids:
                ss = SchoolStudent.objects.filter(school=school, student_id=sid, is_active=True).first()
                if not ss:
                    continue
                bal_str = request.POST.get(f'balance_{sid}', '').strip()
                try:
                    ss.opening_balance = Decimal(bal_str) if bal_str else Decimal('0')
                except (InvalidOperation, ValueError):
                    continue
                ss.save(update_fields=['opening_balance'])
                updated += 1

        if updated:
            log_event(
                user=request.user, school=school, category='data_change',
                action='opening_balances_batch_updated',
                detail={'updated_count': updated,
                        'student_ids': student_ids},
                request=request,
            )
            messages.success(request, f'{updated} balance{"s" if updated != 1 else ""} updated.')
        return redirect('opening_balances')


class AddStudentFeeOverrideView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('fee_configuration')

        student_id = request.POST.get('student_id')
        rate_str = request.POST.get('daily_rate', '').strip()
        reason = request.POST.get('reason', '').strip()
        date_str = request.POST.get('effective_from', '').strip()

        ss = SchoolStudent.objects.filter(
            school=school, student_id=student_id, is_active=True,
        ).first()
        if not ss:
            messages.error(request, 'Student not found in this school.')
            return redirect('fee_configuration')

        try:
            daily_rate = Decimal(rate_str)
            if daily_rate < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Daily rate must be a number >= 0.')
            return redirect('fee_configuration')

        effective_from = _parse_date(date_str)
        if not effective_from:
            messages.error(request, 'Valid effective date is required.')
            return redirect('fee_configuration')

        StudentFeeOverride.objects.create(
            student=ss.student,
            school=school,
            daily_rate=daily_rate,
            reason=reason,
            effective_from=effective_from,
            created_by=request.user,
        )
        name = f'{ss.student.first_name} {ss.student.last_name}'.strip() or ss.student.username
        log_event(
            user=request.user, school=school, category='data_change',
            action='student_fee_override_added',
            detail={'student_id': ss.student_id, 'student': name,
                    'daily_rate': str(daily_rate), 'effective_from': str(effective_from),
                    'reason': reason},
            request=request,
        )
        messages.success(request, f'Fee override set for {name}: ${daily_rate}/day.')
        return redirect('fee_configuration')


# ===========================================================================
# Invoice Generation
# ===========================================================================

class GenerateInvoicesView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        departments = Department.objects.filter(school=school, is_active=True)
        terms = Term.objects.filter(school=school).select_related('academic_year')

        # Compute period options for quick-select
        today = date.today()

        # Next month
        if today.month == 12:
            next_month_start = date(today.year + 1, 1, 1)
        else:
            next_month_start = date(today.year, today.month + 1, 1)
        next_month_end = date(
            next_month_start.year,
            next_month_start.month,
            calendar.monthrange(next_month_start.year, next_month_start.month)[1],
        )
        next_month_label = next_month_start.strftime('%B %Y')

        # Next term (first term starting after today)
        next_term = Term.objects.filter(
            school=school, start_date__gt=today,
        ).select_related('academic_year').order_by('start_date').first()

        # Current academic year (for "year" option)
        current_year = AcademicYear.objects.filter(
            school=school, is_current=True,
        ).first()

        return render(request, 'invoicing/generate_invoices.html', {
            'school': school,
            'departments': departments,
            'terms': terms,
            'next_month_start': next_month_start.isoformat(),
            'next_month_end': next_month_end.isoformat(),
            'next_month_label': next_month_label,
            'next_term': next_term,
            'current_year': current_year,
        })

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        start = _parse_date(request.POST.get('billing_period_start'))
        end = _parse_date(request.POST.get('billing_period_end'))
        mode = request.POST.get('attendance_mode', 'all_class_days')
        billing_type = request.POST.get('billing_type', 'post_term')
        period_type = request.POST.get('period_type', 'custom')
        dept_id = request.POST.get('department_id')

        if not start or not end:
            messages.error(request, 'Both start and end dates are required.')
            return redirect('generate_invoices')

        if start > end:
            messages.error(request, 'Start date must be before end date.')
            return redirect('generate_invoices')

        # Future periods: force upfront billing and all-class-days mode
        today = date.today()
        is_future = end > today
        if is_future:
            billing_type = 'upfront'
            mode = 'all_class_days'

        department = None
        if dept_id:
            department = Department.objects.filter(id=dept_id, school=school).first()

        # Validate attendance completeness (skip for upfront billing)
        if billing_type != 'upfront':
            unmarked = svc.validate_attendance_complete(school, start, end, department)
            if unmarked:
                departments = Department.objects.filter(school=school, is_active=True)
                terms = Term.objects.filter(school=school).select_related('academic_year')
                return render(request, 'invoicing/generate_invoices.html', {
                    'school': school,
                    'departments': departments,
                    'terms': terms,
                    'unmarked_sessions': unmarked,
                    'form_data': {
                        'billing_period_start': str(start),
                        'billing_period_end': str(end),
                        'attendance_mode': mode,
                        'billing_type': billing_type,
                        'department_id': dept_id,
                    },
                })

        # For upfront billing, auto-create scheduled sessions for the period
        if billing_type == 'upfront':
            sessions_created = svc.ensure_sessions_for_period(
                school, start, end, created_by=request.user,
            )
            if sessions_created:
                logger.info('Auto-created %d sessions for %s (%s to %s)',
                            sessions_created, school, start, end)

        # Get students in scope
        students_qs = SchoolStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('student')

        student_data = []
        all_warnings = []
        skipped_overlap = []
        skipped_no_enrollment = []

        for ss in students_qs:
            student = ss.student

            overlaps = svc.check_overlapping_invoices(student, school, start, end)
            if overlaps.exists():
                skipped_overlap.append(student.get_full_name() or student.username)
                continue

            # Check if student has any active class enrollments
            active_enrollments = ClassStudent.objects.filter(
                classroom__school=school, student=student, is_active=True,
                classroom__is_active=True,
            ).exists()
            if not active_enrollments:
                skipped_no_enrollment.append(student.get_full_name() or student.username)

            lines, warnings = svc.calculate_invoice_lines(
                student, school, start, end, mode, billing_type=billing_type
            )
            all_warnings.extend(warnings)

            if lines:
                student_data.append({
                    'student': student,
                    'lines': lines,
                })

        if not student_data:
            reasons = []
            total_students = students_qs.count()

            if total_students == 0:
                messages.warning(request, 'No invoices generated — no active students found in this school.')
                return redirect('generate_invoices')

            if skipped_overlap:
                reasons.append(
                    f'{len(skipped_overlap)} student(s) already have invoices for this period: '
                    f'{", ".join(sorted(skipped_overlap)[:5])}'
                    f'{"..." if len(skipped_overlap) > 5 else ""}'
                )

            if skipped_no_enrollment:
                reasons.append(
                    f'{len(skipped_no_enrollment)} student(s) have no active class enrollments: '
                    f'{", ".join(sorted(skipped_no_enrollment)[:5])}'
                    f'{"..." if len(skipped_no_enrollment) > 5 else ""}'
                )

            if all_warnings:
                classrooms = set(w['classroom'].name for w in all_warnings)
                reasons.append(
                    f'Fees not configured for: {", ".join(sorted(classrooms))}. '
                    f'Set fees on the Fee Configuration page.'
                )

            # Check if sessions exist at all in this period
            session_count = ClassSession.objects.filter(
                classroom__school=school,
                classroom__is_active=True,
                date__range=(start, end),
            ).exclude(status='cancelled').count()
            if session_count == 0:
                reasons.append(
                    f'No sessions found between {start} and {end}. '
                    f'Sessions are auto-created for upfront billing, or use '
                    f'"Create Session" on each class page.'
                )

            if reasons:
                msg = 'No invoices generated. Reasons: ' + ' | '.join(reasons)
            else:
                msg = (
                    f'No invoices generated for {total_students} student(s). '
                    f'Check that students are enrolled in active classes with sessions '
                    f'and fees configured for the period {start} to {end}.'
                )
            messages.warning(request, msg)
            return redirect('generate_invoices')

        # Create drafts
        with transaction.atomic():
            invoices = svc.create_draft_invoices(
                school, student_data, mode, start, end, request.user,
                billing_type=billing_type, period_type=period_type,
            )

        invoice_ids = [inv.id for inv in invoices]
        request.session['draft_invoice_ids'] = invoice_ids

        log_event(
            user=request.user, school=school, category='data_change',
            action='invoice_generated',
            detail={'count': len(invoices), 'invoice_ids': invoice_ids,
                    'period_start': str(start), 'period_end': str(end),
                    'mode': mode, 'billing_type': billing_type,
                    'period_type': period_type},
            request=request,
        )
        return redirect('invoice_preview')


class InvoicePreviewView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        invoice_ids = request.session.get('draft_invoice_ids', [])
        invoices = Invoice.objects.filter(
            id__in=invoice_ids, status='draft',
        ).select_related('student').prefetch_related('line_items', 'line_items__classroom', 'line_items__department')

        if not invoices:
            messages.info(request, 'No draft invoices to review.')
            return redirect('generate_invoices')

        total = sum(inv.amount for inv in invoices)

        return render(request, 'invoicing/invoice_preview.html', {
            'invoices': invoices,
            'total': total,
        })

    def post(self, request):
        """Handle inline edits to amount and notes on draft invoices."""
        invoice_id = request.POST.get('invoice_id')
        invoice = get_object_or_404(Invoice, id=invoice_id, status='draft')

        amount_str = request.POST.get('amount', '').strip()
        notes = request.POST.get('notes', '')

        if amount_str:
            try:
                invoice.amount = Decimal(amount_str)
            except InvalidOperation:
                messages.error(request, 'Invalid amount.')
                return redirect('invoice_preview')

        invoice.notes = notes
        invoice.save(update_fields=['amount', 'notes', 'updated_at'])
        log_event(
            user=request.user, school=invoice.school, category='data_change',
            action='invoice_edited',
            detail={'invoice_id': invoice.id, 'invoice_number': invoice.invoice_number},
            request=request,
        )
        messages.success(request, f'Invoice {invoice.invoice_number} updated.')
        return redirect('invoice_preview')


class IssueInvoicesView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request):
        school = _get_single_school(request.user)

        # Accept invoice IDs from POST body or session
        post_ids = request.POST.getlist('invoice_ids')
        if post_ids:
            invoice_ids = [int(i) for i in post_ids if i.isdigit()]
        else:
            invoice_ids = request.session.get('draft_invoice_ids', [])

        if not invoice_ids:
            messages.error(request, 'No draft invoices to issue.')
            return redirect('invoice_list')

        # Scope to user's school for safety
        invoice_ids = list(Invoice.objects.filter(
            id__in=invoice_ids, school=school, status='draft',
        ).values_list('id', flat=True))

        if not invoice_ids:
            messages.error(request, 'No draft invoices found.')
            return redirect('invoice_list')

        issued = svc.issue_invoices(invoice_ids, request.user)
        request.session.pop('draft_invoice_ids', None)

        log_event(
            user=request.user, school=school, category='data_change',
            action='invoice_issued',
            detail={'count': len(issued),
                    'invoice_ids': [inv.id for inv in issued]},
            request=request,
        )
        messages.success(request, f'{len(issued)} invoice(s) issued successfully.')
        return redirect('invoice_list')


class DeleteDraftInvoicesView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request):
        invoice_ids = request.session.get('draft_invoice_ids', [])
        count = Invoice.objects.filter(id__in=invoice_ids, status='draft').delete()[0]
        request.session.pop('draft_invoice_ids', None)
        school = _get_single_school(request.user)
        log_event(
            user=request.user, school=school, category='data_change',
            action='invoice_deleted',
            detail={'count': count, 'invoice_ids': invoice_ids, 'status': 'draft'},
            request=request,
        )
        messages.success(request, f'{count} draft invoice(s) deleted.')
        return redirect('generate_invoices')


# ===========================================================================
# Invoice List & Detail
# ===========================================================================

class InvoiceListView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        invoices = Invoice.objects.filter(school=school).select_related('student')

        status_filter = request.GET.get('status')
        if status_filter:
            invoices = invoices.filter(status=status_filter)

        search = request.GET.get('q', '').strip()
        if search:
            invoices = invoices.filter(
                models.Q(student__first_name__icontains=search) |
                models.Q(student__last_name__icontains=search) |
                models.Q(invoice_number__icontains=search)
            )

        dept_filter = request.GET.get('department')
        if dept_filter:
            invoices = invoices.filter(
                line_items__department_id=dept_filter,
            ).distinct()

        paginator = Paginator(invoices, 25)
        page = paginator.get_page(request.GET.get('page'))

        departments = Department.objects.filter(school=school, is_active=True)
        draft_invoices = Invoice.objects.filter(school=school, status='draft')
        draft_count = draft_invoices.count()
        draft_ids = list(draft_invoices.values_list('id', flat=True))

        return render(request, 'invoicing/invoice_list.html', {
            'school': school,
            'page': page,
            'departments': departments,
            'status_filter': status_filter or '',
            'search': search,
            'dept_filter': dept_filter or '',
            'draft_count': draft_count,
            'draft_ids': draft_ids,
        })


class InvoiceDetailView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request, invoice_id):
        school = _get_single_school(request.user)
        invoice = get_object_or_404(Invoice, id=invoice_id, school=school)
        line_items = invoice.line_items.select_related('classroom', 'department')
        payments = invoice.payments.order_by('-created_at')
        credit_balance = svc.get_credit_balance(invoice.student, invoice.school)

        # Get effective settings (department overrides applied)
        primary_dept = None
        for li in line_items:
            if li.classroom and li.classroom.department:
                primary_dept = li.classroom.department
                break
        effective_settings = school.get_effective_settings(primary_dept)

        return render(request, 'invoicing/invoice_detail.html', {
            'invoice': invoice,
            'school': school,
            'line_items': line_items,
            'payments': payments,
            'credit_balance': credit_balance,
            'effective_settings': effective_settings,
        })


class InvoiceEditView(RoleRequiredMixin, View):
    """Edit a draft invoice: line items, dates, notes."""
    required_roles = INVOICING_ROLES

    def _get_invoice(self, request, invoice_id):
        school = _get_single_school(request.user)
        return get_object_or_404(Invoice, id=invoice_id, school=school)

    def get(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        if invoice.status != 'draft':
            messages.error(request, 'Only draft invoices can be edited.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        line_items = invoice.line_items.select_related('classroom', 'department')
        return render(request, 'invoicing/invoice_edit.html', {
            'invoice': invoice,
            'line_items': line_items,
        })

    def post(self, request, invoice_id):
        invoice = self._get_invoice(request, invoice_id)
        if invoice.status != 'draft':
            messages.error(request, 'Only draft invoices can be edited.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        action = request.POST.get('action', 'save')

        # --- Handle add line item ---
        if action == 'add_line':
            description = request.POST.get('new_description', '').strip()
            amount_str = request.POST.get('new_amount', '').strip()
            if not description or not amount_str:
                messages.error(request, 'Description and amount are required for new line items.')
                return redirect('invoice_edit', invoice_id=invoice.id)
            try:
                amount = Decimal(amount_str)
            except (InvalidOperation, ValueError):
                messages.error(request, 'Invalid amount for new line item.')
                return redirect('invoice_edit', invoice_id=invoice.id)

            InvoiceLineItem.objects.create(
                invoice=invoice,
                classroom=None,
                department=None,
                daily_rate=amount,
                rate_source='opening_balance',
                sessions_held=0,
                sessions_attended=0,
                sessions_charged=0,
                line_amount=amount,
            )
            # Recalculate totals
            self._recalculate_totals(invoice)
            invoice.notes = (invoice.notes or '').rstrip()
            note_line = f'Manual line added: {description} (${amount})'
            if invoice.notes:
                invoice.notes += '\n' + note_line
            else:
                invoice.notes = note_line
            invoice.save(update_fields=['amount', 'calculated_amount', 'notes', 'updated_at'])
            messages.success(request, 'Line item added.')
            return redirect('invoice_edit', invoice_id=invoice.id)

        # --- Handle remove line item ---
        if action == 'remove_line':
            line_id = request.POST.get('line_id')
            if line_id:
                deleted, _ = InvoiceLineItem.objects.filter(
                    id=line_id, invoice=invoice,
                ).delete()
                if deleted:
                    self._recalculate_totals(invoice)
                    invoice.save(update_fields=['amount', 'calculated_amount', 'updated_at'])
                    messages.success(request, 'Line item removed.')
                else:
                    messages.error(request, 'Line item not found.')
            return redirect('invoice_edit', invoice_id=invoice.id)

        # --- Handle save (update line amounts, dates, notes) ---
        with transaction.atomic():
            # Update existing line items
            for line in invoice.line_items.all():
                amount_key = f'line_amount_{line.id}'
                amount_str = request.POST.get(amount_key, '').strip()
                if amount_str:
                    try:
                        new_amount = Decimal(amount_str)
                        if new_amount != line.line_amount:
                            line.line_amount = new_amount
                            line.save(update_fields=['line_amount'])
                    except (InvalidOperation, ValueError):
                        pass  # skip invalid amounts

            # Update invoice-level fields
            due_date_str = request.POST.get('due_date', '').strip()
            notes = request.POST.get('notes', '')

            if due_date_str:
                parsed_date = _parse_date(due_date_str)
                if parsed_date:
                    invoice.due_date = parsed_date
                else:
                    messages.error(request, 'Invalid due date format.')
                    return redirect('invoice_edit', invoice_id=invoice.id)
            else:
                invoice.due_date = None

            invoice.notes = notes

            # Recalculate totals from line items
            self._recalculate_totals(invoice)
            invoice.save(update_fields=[
                'due_date', 'notes', 'amount', 'calculated_amount', 'updated_at',
            ])

        log_event(
            user=request.user, school=invoice.school, category='data_change',
            action='invoice_edited',
            detail={'invoice_id': invoice.id, 'invoice_number': invoice.invoice_number,
                    'action': action},
            request=request,
        )
        messages.success(request, f'Invoice {invoice.invoice_number} updated.')
        return redirect('invoice_detail', invoice_id=invoice.id)

    @staticmethod
    def _recalculate_totals(invoice):
        """Recalculate calculated_amount and amount from line items."""
        total = invoice.line_items.aggregate(
            total=models.Sum('line_amount'),
        )['total'] or Decimal('0.00')
        invoice.calculated_amount = total
        invoice.amount = total


class CancelInvoiceView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request, invoice_id):
        school = _get_single_school(request.user)
        invoice = get_object_or_404(Invoice, id=invoice_id, school=school)

        if invoice.status == 'cancelled':
            messages.error(request, 'Invoice is already cancelled.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        if invoice.status == 'draft':
            inv_id = invoice.id
            inv_number = invoice.invoice_number
            invoice.delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='invoice_deleted',
                detail={'invoice_id': inv_id, 'invoice_number': inv_number,
                        'status': 'draft'},
                request=request,
            )
            messages.success(request, 'Draft invoice deleted.')
            return redirect('invoice_list')

        reason = request.POST.get('cancellation_reason', '').strip()
        if not reason:
            messages.error(request, 'Cancellation reason is required.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        svc.cancel_invoice(invoice, reason, request.user)
        log_event(
            user=request.user, school=school, category='data_change',
            action='invoice_voided',
            detail={'invoice_id': invoice.id, 'invoice_number': invoice.invoice_number,
                    'reason': reason},
            request=request,
        )
        messages.success(request, f'Invoice {invoice.invoice_number} cancelled.')
        return redirect('invoice_detail', invoice_id=invoice.id)


class RecordManualPaymentView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request, invoice_id):
        school = _get_single_school(request.user)
        invoice = get_object_or_404(Invoice, id=invoice_id, school=school)

        if invoice.status in ('cancelled', 'draft'):
            messages.error(request, 'Cannot record payment on this invoice.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        amount_str = request.POST.get('amount', '').strip()
        date_str = request.POST.get('payment_date', '').strip()
        method = request.POST.get('payment_method', 'cash')
        notes = request.POST.get('notes', '').strip()

        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Amount must be a positive number.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        payment_date = _parse_date(date_str)
        if not payment_date:
            messages.error(request, 'Valid payment date is required.')
            return redirect('invoice_detail', invoice_id=invoice.id)

        svc.record_payment(
            invoice=invoice,
            amount=amount,
            payment_date=payment_date,
            payment_method=method,
            notes=notes,
            created_by=request.user,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='payment_recorded',
            detail={'invoice_id': invoice.id, 'invoice_number': invoice.invoice_number,
                    'amount': str(amount), 'method': method,
                    'payment_date': str(payment_date)},
            request=request,
        )
        messages.success(request, f'Payment of ${amount} recorded.')
        return redirect('invoice_detail', invoice_id=invoice.id)


# ===========================================================================
# CSV Import Pipeline
# ===========================================================================

class CSVUploadView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        templates = CSVColumnTemplate.objects.filter(school=school)
        return render(request, 'invoicing/csv_upload.html', {
            'school': school,
            'templates': templates,
        })

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        csv_file = request.FILES.get('csv_file')
        if not csv_file:
            messages.error(request, 'Please select a CSV file.')
            return redirect('csv_upload')

        if csv_file.size > svc.MAX_CSV_SIZE:
            messages.error(request, 'File exceeds 10MB limit.')
            return redirect('csv_upload')

        file_content = csv_file.read()

        try:
            headers, data_rows = svc.parse_csv_file(file_content)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('csv_upload')

        csv_import = CSVImport.objects.create(
            school=school,
            file_name=csv_file.name,
            uploaded_by=request.user,
            total_rows=len(data_rows),
            status='pending',
        )

        log_event(
            user=request.user, school=school, category='data_change',
            action='csv_uploaded',
            detail={'csv_import_id': csv_import.id,
                    'file_name': csv_file.name,
                    'total_rows': len(data_rows)},
            request=request,
        )

        request.session['csv_import_id'] = csv_import.id
        request.session['csv_headers'] = headers
        request.session['csv_preview'] = data_rows[:5]
        request.session['csv_data'] = data_rows

        templates = CSVColumnTemplate.objects.filter(school=school)
        template_id = request.POST.get('template_id')
        selected_template = None
        if template_id:
            selected_template = CSVColumnTemplate.objects.filter(
                id=template_id, school=school
            ).first()

        return render(request, 'invoicing/csv_mapping.html', {
            'school': school,
            'headers': headers,
            'preview_rows': data_rows[:5],
            'csv_import': csv_import,
            'templates': templates,
            'selected_template': selected_template,
        })


class CSVColumnMappingView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        csv_import_id = request.session.get('csv_import_id')
        csv_import = get_object_or_404(CSVImport, id=csv_import_id, school=school)
        data_rows = request.session.get('csv_data', [])

        try:
            date_col = int(request.POST.get('date_col', 0))
            amount_col = int(request.POST.get('amount_col', 1))
            reference_col = int(request.POST.get('reference_col', 2))
            transaction_id_col = request.POST.get('transaction_id_col')
            if transaction_id_col:
                transaction_id_col = int(transaction_id_col)
            else:
                transaction_id_col = None
        except (ValueError, TypeError):
            messages.error(request, 'Invalid column selection.')
            return redirect('csv_upload')

        amount_type = request.POST.get('amount_type', 'credit')

        column_mapping = {
            'date_col': date_col,
            'amount_col': amount_col,
            'reference_col': reference_col,
            'transaction_id_col': transaction_id_col,
            'amount_type': amount_type,
        }

        template_name = request.POST.get('save_template_name', '').strip()
        if template_name:
            CSVColumnTemplate.objects.update_or_create(
                school=school, name=template_name,
                defaults={
                    'column_mapping': column_mapping,
                    'created_by': request.user,
                },
            )

        csv_import.column_mapping = column_mapping
        csv_import.status = 'processing'
        csv_import.save(update_fields=['column_mapping', 'status'])

        results = svc.process_csv_rows(data_rows, column_mapping, school)

        csv_import.credit_rows = len(results['auto_matched']) + len(results['multi_match']) + len(results['unmatched'])
        csv_import.skipped_rows = len(results['skipped']) + len(results['duplicates'])
        csv_import.matched_count = len(results['auto_matched'])
        csv_import.unmatched_count = len(results['unmatched']) + len(results['multi_match'])
        csv_import.save()

        log_event(
            user=request.user, school=school, category='data_change',
            action='csv_column_mapping_applied',
            detail={'csv_import_id': csv_import.id,
                    'matched': csv_import.matched_count,
                    'unmatched': csv_import.unmatched_count},
            request=request,
        )

        request.session['csv_results'] = {
            'auto_matched': [
                {
                    'row_index': e['row_index'],
                    'reference': e['reference'],
                    'amount': str(e['amount']),
                    'date_str': e['date_str'],
                    'transaction_id': e.get('transaction_id', ''),
                    'student_id': e['student'].id,
                    'student_name': f"{e['student'].first_name} {e['student'].last_name}".strip(),
                    'confidence': e.get('confidence', 100),
                }
                for e in results['auto_matched']
            ],
            'multi_match': [
                {
                    'row_index': e['row_index'],
                    'reference': e['reference'],
                    'amount': str(e['amount']),
                    'date_str': e['date_str'],
                    'transaction_id': e.get('transaction_id', ''),
                    'candidates': [
                        {'id': s.id, 'name': f"{s.first_name} {s.last_name}".strip(), 'score': sc}
                        for s, sc in e.get('candidates', [])
                    ],
                }
                for e in results['multi_match']
            ],
            'unmatched': [
                {
                    'row_index': e['row_index'],
                    'reference': e['reference'],
                    'amount': str(e['amount']),
                    'date_str': e['date_str'],
                    'transaction_id': e.get('transaction_id', ''),
                    'candidates': [
                        {'id': s.id, 'name': f"{s.first_name} {s.last_name}".strip(), 'score': sc}
                        for s, sc in e.get('candidates', [])
                    ],
                }
                for e in results['unmatched']
            ],
            'skipped': len(results['skipped']),
            'duplicates': len(results['duplicates']),
        }

        return redirect('csv_review_matches', import_id=csv_import.id)


class CSVReviewMatchesView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request, import_id):
        school = _get_single_school(request.user)
        csv_import = get_object_or_404(CSVImport, id=import_id, school=school)
        results = request.session.get('csv_results', {})

        students = SchoolStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('student').order_by('student__first_name')

        return render(request, 'invoicing/csv_review.html', {
            'csv_import': csv_import,
            'auto_matched': results.get('auto_matched', []),
            'multi_match': results.get('multi_match', []),
            'unmatched': results.get('unmatched', []),
            'skipped_count': results.get('skipped', 0),
            'duplicate_count': results.get('duplicates', 0),
            'students': students,
        })


class ConfirmCSVPaymentsView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request, import_id):
        school = _get_single_school(request.user)
        csv_import = get_object_or_404(CSVImport, id=import_id, school=school)
        results = request.session.get('csv_results', {})

        from django.contrib.auth import get_user_model
        User = get_user_model()

        confirmed = 0
        ignored = 0

        with transaction.atomic():
            # Process auto-matched
            for entry in results.get('auto_matched', []):
                student = User.objects.filter(id=entry['student_id']).first()
                if not student:
                    continue

                invoice = Invoice.objects.filter(
                    student=student, school=school,
                    status__in=['issued', 'partially_paid'],
                ).order_by('created_at').first()

                payment_date = _parse_date(entry['date_str']) or timezone.now().date()

                svc.record_payment(
                    invoice=invoice,
                    amount=Decimal(entry['amount']),
                    payment_date=payment_date,
                    payment_method='bank_transfer',
                    reference_name=entry['reference'],
                    bank_transaction_id=entry.get('transaction_id', ''),
                    csv_import=csv_import,
                    created_by=request.user,
                )

                normalized = svc.normalize_reference(entry['reference'])
                PaymentReferenceMapping.objects.get_or_create(
                    school=school, reference_name=normalized,
                    defaults={'student': student, 'created_by': request.user},
                )
                confirmed += 1

            # Process manually resolved entries
            for key, value in request.POST.items():
                if key.startswith('resolve_'):
                    row_idx = key.replace('resolve_', '')
                    action = value

                    if action == 'ignore':
                        ref_key = f'reference_{row_idx}'
                        ref = request.POST.get(ref_key, '')
                        if ref:
                            normalized = svc.normalize_reference(ref)
                            PaymentReferenceMapping.objects.get_or_create(
                                school=school, reference_name=normalized,
                                defaults={'is_ignored': True, 'created_by': request.user},
                            )
                        ignored += 1
                    elif action.isdigit():
                        student = User.objects.filter(id=int(action)).first()
                        if not student:
                            continue

                        amount_key = f'amount_{row_idx}'
                        date_key = f'date_{row_idx}'
                        ref_key = f'reference_{row_idx}'
                        txid_key = f'txid_{row_idx}'

                        amount = Decimal(request.POST.get(amount_key, '0'))
                        payment_date = _parse_date(request.POST.get(date_key)) or timezone.now().date()
                        reference = request.POST.get(ref_key, '')
                        txid = request.POST.get(txid_key, '')

                        invoice = Invoice.objects.filter(
                            student=student, school=school,
                            status__in=['issued', 'partially_paid'],
                        ).order_by('created_at').first()

                        svc.record_payment(
                            invoice=invoice,
                            amount=amount,
                            payment_date=payment_date,
                            payment_method='bank_transfer',
                            reference_name=reference,
                            bank_transaction_id=txid,
                            csv_import=csv_import,
                            created_by=request.user,
                        )

                        normalized = svc.normalize_reference(reference)
                        PaymentReferenceMapping.objects.get_or_create(
                            school=school, reference_name=normalized,
                            defaults={'student': student, 'created_by': request.user},
                        )
                        confirmed += 1

            csv_import.confirmed_count = confirmed
            csv_import.ignored_count = ignored
            csv_import.status = 'completed'
            csv_import.save()

        request.session.pop('csv_results', None)
        request.session.pop('csv_data', None)
        request.session.pop('csv_headers', None)
        request.session.pop('csv_preview', None)
        request.session.pop('csv_import_id', None)

        log_event(
            user=request.user, school=school, category='data_change',
            action='payments_imported',
            detail={'csv_import_id': csv_import.id,
                    'confirmed': confirmed, 'ignored': ignored},
            request=request,
        )
        messages.success(request, f'{confirmed} payment(s) confirmed, {ignored} ignored.')
        return redirect('invoice_list')


# ===========================================================================
# Reference Mappings Management
# ===========================================================================

class ReferenceMappingsView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        mappings = PaymentReferenceMapping.objects.filter(
            school=school,
        ).select_related('student').order_by('reference_name')

        search = request.GET.get('q', '').strip()
        if search:
            mappings = mappings.filter(
                models.Q(reference_name__icontains=search) |
                models.Q(student__first_name__icontains=search) |
                models.Q(student__last_name__icontains=search)
            )

        return render(request, 'invoicing/reference_mappings.html', {
            'school': school,
            'mappings': mappings,
            'search': search,
        })

    def post(self, request):
        school = _get_single_school(request.user)
        action = request.POST.get('action')

        if action == 'delete':
            mapping_id = request.POST.get('mapping_id')
            PaymentReferenceMapping.objects.filter(
                id=mapping_id, school=school,
            ).delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='reference_mapping_deleted',
                detail={'mapping_id': mapping_id},
                request=request,
            )
            messages.success(request, 'Mapping deleted.')
        elif action == 'update':
            mapping_id = request.POST.get('mapping_id')
            student_id = request.POST.get('student_id')
            mapping = get_object_or_404(
                PaymentReferenceMapping, id=mapping_id, school=school,
            )
            if student_id:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                mapping.student = User.objects.filter(id=student_id).first()
                mapping.is_ignored = False
            else:
                mapping.student = None
                mapping.is_ignored = True
            mapping.save()
            log_event(
                user=request.user, school=school, category='data_change',
                action='reference_mapping_updated',
                detail={'mapping_id': mapping_id, 'student_id': student_id,
                        'is_ignored': mapping.is_ignored},
                request=request,
            )
            messages.success(request, 'Mapping updated.')

        return redirect('reference_mappings')


# ===========================================================================
# Student Search API (for typeahead)
# ===========================================================================

class StudentSearchAPIView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            return JsonResponse({'results': []})

        q = request.GET.get('q', '').strip()
        if len(q) < 2:
            return JsonResponse({'results': []})

        from django.db.models import Q
        students = SchoolStudent.objects.filter(
            school=school, is_active=True,
        ).filter(
            Q(student__first_name__icontains=q) |
            Q(student__last_name__icontains=q) |
            Q(student__username__icontains=q)
        ).select_related('student')[:15]

        results = [
            {
                'id': ss.student.id,
                'name': f'{ss.student.first_name} {ss.student.last_name}'.strip() or ss.student.username,
                'username': ss.student.username,
            }
            for ss in students
        ]
        return JsonResponse({'results': results})


# ===========================================================================
# Opening Balances
# ===========================================================================

class OpeningBalancesView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        students = SchoolStudent.objects.filter(
            school=school, is_active=True,
        ).select_related('student').order_by(
            'student__first_name', 'student__last_name',
        )

        return render(request, 'invoicing/opening_balances.html', {
            'school': school,
            'students': students,
        })


class SetOpeningBalanceView(RoleRequiredMixin, View):
    required_roles = INVOICING_ROLES

    def post(self, request, student_id):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        ss = get_object_or_404(
            SchoolStudent, school=school, student_id=student_id, is_active=True,
        )

        amount_str = request.POST.get('opening_balance', '').strip()
        if not amount_str:
            messages.error(request, 'Amount is required.')
            return redirect('opening_balances')

        try:
            amount = Decimal(amount_str)
        except (InvalidOperation, ValueError):
            messages.error(request, 'Invalid amount.')
            return redirect('opening_balances')

        name = f'{ss.student.first_name} {ss.student.last_name}'.strip() or ss.student.username
        svc.set_opening_balance(ss, amount)

        log_event(
            user=request.user, school=school, category='data_change',
            action='opening_balance_set',
            detail={'student_id': student_id, 'student': name,
                    'amount': str(amount)},
            request=request,
        )

        if amount < 0:
            messages.success(request, f'Credit of ${abs(amount)} created for {name}.')
        elif amount > 0:
            messages.success(request, f'Opening balance of ${amount} set for {name}.')
        else:
            messages.success(request, f'Opening balance cleared for {name}.')

        return redirect('opening_balances')
