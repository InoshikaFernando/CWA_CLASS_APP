"""
Salary views — rate configuration, salary slip generation, list/detail,
payment recording, and cancellation.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.db import models, transaction
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from audit.services import log_event
from .models import (
    School, Department, ClassRoom, SchoolTeacher,
    TeacherHourlyRate, TeacherRateOverride,
    SalarySlip, SalarySlipLineItem, SalaryPayment,
)
from .views import RoleRequiredMixin
from .views_invoicing import _get_invoicing_schools, _get_single_school, _parse_date
from . import salary_services as svc


SALARY_ROLES = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.ACCOUNTANT]


# ===========================================================================
# Rate Configuration
# ===========================================================================

class SalaryRateConfigurationView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        current_rate = TeacherHourlyRate.objects.filter(
            school=school,
        ).order_by('-effective_from').first()

        teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).select_related('teacher').order_by('teacher__first_name', 'teacher__last_name')

        teacher_overrides = TeacherRateOverride.objects.filter(
            school=school,
        ).select_related('teacher').order_by('-effective_from')

        seen = set()
        unique_overrides = []
        for override in teacher_overrides:
            if override.teacher_id not in seen:
                seen.add(override.teacher_id)
                unique_overrides.append(override)

        return render(request, 'salaries/rate_configuration.html', {
            'school': school,
            'current_rate': current_rate,
            'teachers': teachers,
            'teacher_overrides': unique_overrides,
        })


class SetSchoolDefaultRateView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('salary_rate_configuration')

        rate_str = request.POST.get('hourly_rate', '').strip()
        date_str = request.POST.get('effective_from', '').strip()

        try:
            hourly_rate = Decimal(rate_str)
            if hourly_rate < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Hourly rate must be a number >= 0.')
            return redirect('salary_rate_configuration')

        effective_from = _parse_date(date_str)
        if not effective_from:
            messages.error(request, 'Valid effective date is required.')
            return redirect('salary_rate_configuration')

        TeacherHourlyRate.objects.create(
            school=school,
            hourly_rate=hourly_rate,
            effective_from=effective_from,
            created_by=request.user,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='salary_config_created',
            detail={'hourly_rate': str(hourly_rate), 'effective_from': str(effective_from)},
            request=request,
        )
        messages.success(request, f'Default hourly rate set: ${hourly_rate}/hr.')
        return redirect('salary_rate_configuration')


class AddTeacherRateOverrideView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('salary_rate_configuration')

        teacher_id = request.POST.get('teacher_id')
        rate_str = request.POST.get('hourly_rate', '').strip()
        reason = request.POST.get('reason', '').strip()
        date_str = request.POST.get('effective_from', '').strip()

        st = SchoolTeacher.objects.filter(
            school=school, teacher_id=teacher_id, is_active=True,
        ).first()
        if not st:
            messages.error(request, 'Teacher not found in this school.')
            return redirect('salary_rate_configuration')

        try:
            hourly_rate = Decimal(rate_str)
            if hourly_rate < 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Hourly rate must be a number >= 0.')
            return redirect('salary_rate_configuration')

        effective_from = _parse_date(date_str)
        if not effective_from:
            messages.error(request, 'Valid effective date is required.')
            return redirect('salary_rate_configuration')

        TeacherRateOverride.objects.create(
            teacher=st.teacher,
            school=school,
            hourly_rate=hourly_rate,
            reason=reason,
            effective_from=effective_from,
            created_by=request.user,
        )
        name = f'{st.teacher.first_name} {st.teacher.last_name}'.strip() or st.teacher.username
        log_event(
            user=request.user, school=school, category='data_change',
            action='teacher_rate_override_created',
            detail={'teacher_id': st.teacher.id, 'teacher_name': name,
                    'hourly_rate': str(hourly_rate), 'reason': reason,
                    'effective_from': str(effective_from)},
            request=request,
        )
        messages.success(request, f'Rate override set for {name}: ${hourly_rate}/hr.')
        return redirect('salary_rate_configuration')


class BatchTeacherRateView(RoleRequiredMixin, View):
    """Batch update hourly rates for multiple teachers in one POST."""
    required_roles = SALARY_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            return redirect('salary_rate_configuration')

        teacher_ids_str = request.POST.get('teacher_ids', '')
        if not teacher_ids_str:
            return redirect('salary_rate_configuration')

        teacher_ids = [int(x) for x in teacher_ids_str.split(',') if x.strip().isdigit()]
        date_str = request.POST.get('effective_from', '').strip()
        effective_from = _parse_date(date_str)
        if not effective_from:
            messages.error(request, 'Valid effective date is required.')
            return redirect('salary_rate_configuration')

        updated = 0
        with transaction.atomic():
            for tid in teacher_ids:
                st = SchoolTeacher.objects.filter(school=school, teacher_id=tid, is_active=True).first()
                if not st:
                    continue
                rate_str = request.POST.get(f'rate_{tid}', '').strip()
                if not rate_str:
                    continue
                try:
                    hourly_rate = Decimal(rate_str)
                    if hourly_rate < 0:
                        continue
                except (InvalidOperation, ValueError):
                    continue
                TeacherRateOverride.objects.create(
                    teacher=st.teacher,
                    school=school,
                    hourly_rate=hourly_rate,
                    effective_from=effective_from,
                    created_by=request.user,
                )
                updated += 1

        if updated:
            log_event(
                user=request.user, school=school, category='data_change',
                action='batch_teacher_rates_updated',
                detail={'teachers_updated': updated, 'effective_from': str(effective_from)},
                request=request,
            )
            messages.success(request, f'{updated} teacher rate{"s" if updated != 1 else ""} updated.')
        return redirect('salary_rate_configuration')


# ===========================================================================
# Salary Slip Generation
# ===========================================================================

class GenerateSalarySlipsView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        departments = Department.objects.filter(school=school, is_active=True)
        return render(request, 'salaries/generate_salary_slips.html', {
            'school': school,
            'departments': departments,
        })

    def post(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        start = _parse_date(request.POST.get('billing_period_start'))
        end = _parse_date(request.POST.get('billing_period_end'))
        dept_id = request.POST.get('department_id')

        if not start or not end:
            messages.error(request, 'Both start and end dates are required.')
            return redirect('generate_salary_slips')

        if start > end:
            messages.error(request, 'Start date must be before end date.')
            return redirect('generate_salary_slips')

        department = None
        if dept_id:
            department = Department.objects.filter(id=dept_id, school=school).first()

        # Validate teacher attendance completeness
        unmarked = svc.validate_teacher_attendance_complete(school, start, end, department)
        if unmarked:
            departments = Department.objects.filter(school=school, is_active=True)
            return render(request, 'salaries/generate_salary_slips.html', {
                'school': school,
                'departments': departments,
                'unmarked_sessions': unmarked,
                'form_data': {
                    'billing_period_start': str(start),
                    'billing_period_end': str(end),
                    'department_id': dept_id,
                },
            })

        # Get teachers in scope
        teachers_qs = SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).select_related('teacher')

        if department:
            from .models import DepartmentTeacher
            dept_teacher_ids = DepartmentTeacher.objects.filter(
                department=department,
            ).values_list('teacher_id', flat=True)
            teachers_qs = teachers_qs.filter(teacher_id__in=dept_teacher_ids)

        teacher_data = []
        all_warnings = []

        for st in teachers_qs:
            teacher = st.teacher

            overlaps = svc.check_overlapping_salary_slips(teacher, school, start, end)
            if overlaps.exists():
                continue

            lines, warnings = svc.calculate_salary_lines(
                teacher, school, start, end
            )
            all_warnings.extend(warnings)

            if lines:
                teacher_data.append({
                    'teacher': teacher,
                    'lines': lines,
                })

        if not teacher_data:
            messages.warning(request, 'No salary slips to generate for the selected period.')
            return redirect('generate_salary_slips')

        # Create drafts
        with transaction.atomic():
            slips = svc.create_draft_salary_slips(
                school, teacher_data, start, end, request.user
            )

        slip_ids = [s.id for s in slips]
        request.session['draft_salary_slip_ids'] = slip_ids

        log_event(
            user=request.user, school=school, category='data_change',
            action='salary_slips_generated',
            detail={'slip_count': len(slips), 'period_start': str(start),
                    'period_end': str(end),
                    'department': department.name if department else 'All'},
            request=request,
        )

        return redirect('salary_slip_preview')


class SalarySlipPreviewView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request):
        slip_ids = request.session.get('draft_salary_slip_ids', [])
        slips = SalarySlip.objects.filter(
            id__in=slip_ids, status='draft',
        ).select_related('teacher').prefetch_related(
            'line_items', 'line_items__classroom', 'line_items__department'
        )

        if not slips:
            messages.info(request, 'No draft salary slips to review.')
            return redirect('generate_salary_slips')

        total = sum(s.amount for s in slips)

        return render(request, 'salaries/salary_slip_preview.html', {
            'slips': slips,
            'total': total,
        })

    def post(self, request):
        """Handle inline edits to amount and notes on draft salary slips."""
        slip_id = request.POST.get('slip_id')
        slip = get_object_or_404(SalarySlip, id=slip_id, status='draft')

        amount_str = request.POST.get('amount', '').strip()
        notes = request.POST.get('notes', '')

        if amount_str:
            try:
                slip.amount = Decimal(amount_str)
            except InvalidOperation:
                messages.error(request, 'Invalid amount.')
                return redirect('salary_slip_preview')

        slip.notes = notes
        slip.save(update_fields=['amount', 'notes', 'updated_at'])
        log_event(
            user=request.user, school=slip.school, category='data_change',
            action='salary_slip_edited',
            detail={'slip_id': slip.id, 'slip_number': slip.slip_number,
                    'amount': str(slip.amount)},
            request=request,
        )
        messages.success(request, f'Salary slip {slip.slip_number} updated.')
        return redirect('salary_slip_preview')


class IssueSalarySlipsView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request):
        school = _get_single_school(request.user)

        post_ids = request.POST.getlist('slip_ids')
        if post_ids:
            slip_ids = [int(i) for i in post_ids if i.isdigit()]
        else:
            slip_ids = request.session.get('draft_salary_slip_ids', [])

        if not slip_ids:
            messages.error(request, 'No draft salary slips to issue.')
            return redirect('salary_slip_list')

        slip_ids = list(SalarySlip.objects.filter(
            id__in=slip_ids, school=school, status='draft',
        ).values_list('id', flat=True))

        if not slip_ids:
            messages.error(request, 'No draft salary slips found.')
            return redirect('salary_slip_list')

        issued = svc.issue_salary_slips(slip_ids, request.user)
        request.session.pop('draft_salary_slip_ids', None)

        log_event(
            user=request.user, school=school, category='data_change',
            action='salary_slips_issued',
            detail={'slip_count': len(issued),
                    'slip_ids': [s.id for s in issued]},
            request=request,
        )
        messages.success(request, f'{len(issued)} salary slip(s) issued successfully.')
        return redirect('salary_slip_list')


class DeleteDraftSalarySlipsView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request):
        school = _get_single_school(request.user)
        slip_ids = request.session.get('draft_salary_slip_ids', [])
        count = SalarySlip.objects.filter(id__in=slip_ids, status='draft').delete()[0]
        request.session.pop('draft_salary_slip_ids', None)
        if school:
            log_event(
                user=request.user, school=school, category='data_change',
                action='draft_salary_slips_deleted',
                detail={'deleted_count': count, 'slip_ids': slip_ids},
                request=request,
            )
        messages.success(request, f'{count} draft salary slip(s) deleted.')
        return redirect('generate_salary_slips')


# ===========================================================================
# Salary Slip List & Detail
# ===========================================================================

class SalarySlipListView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            messages.error(request, 'No school found.')
            return redirect('subjects_hub')

        slips = SalarySlip.objects.filter(school=school).select_related('teacher')

        status_filter = request.GET.get('status')
        if status_filter:
            slips = slips.filter(status=status_filter)

        search = request.GET.get('q', '').strip()
        if search:
            slips = slips.filter(
                models.Q(teacher__first_name__icontains=search) |
                models.Q(teacher__last_name__icontains=search) |
                models.Q(slip_number__icontains=search)
            )

        dept_filter = request.GET.get('department')
        if dept_filter:
            slips = slips.filter(
                line_items__department_id=dept_filter,
            ).distinct()

        paginator = Paginator(slips, 25)
        page = paginator.get_page(request.GET.get('page'))

        departments = Department.objects.filter(school=school, is_active=True)
        draft_slips = SalarySlip.objects.filter(school=school, status='draft')
        draft_count = draft_slips.count()
        draft_ids = list(draft_slips.values_list('id', flat=True))

        return render(request, 'salaries/salary_slip_list.html', {
            'school': school,
            'page': page,
            'departments': departments,
            'status_filter': status_filter or '',
            'search': search,
            'dept_filter': dept_filter or '',
            'draft_count': draft_count,
            'draft_ids': draft_ids,
        })


class SalarySlipDetailView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request, slip_id):
        school = _get_single_school(request.user)
        slip = get_object_or_404(SalarySlip, id=slip_id, school=school)
        line_items = slip.line_items.select_related('classroom', 'department')
        payments = slip.payments.order_by('-created_at')

        return render(request, 'salaries/salary_slip_detail.html', {
            'slip': slip,
            'line_items': line_items,
            'payments': payments,
        })


class CancelSalarySlipView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request, slip_id):
        school = _get_single_school(request.user)
        slip = get_object_or_404(SalarySlip, id=slip_id, school=school)

        if slip.status == 'cancelled':
            messages.error(request, 'Salary slip is already cancelled.')
            return redirect('salary_slip_detail', slip_id=slip.id)

        if slip.status == 'draft':
            slip_number = slip.slip_number
            slip_id_val = slip.id
            slip.delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='salary_slip_deleted',
                detail={'slip_id': slip_id_val, 'slip_number': slip_number,
                        'status': 'draft'},
                request=request,
            )
            messages.success(request, 'Draft salary slip deleted.')
            return redirect('salary_slip_list')

        reason = request.POST.get('cancellation_reason', '').strip()
        if not reason:
            messages.error(request, 'Cancellation reason is required.')
            return redirect('salary_slip_detail', slip_id=slip.id)

        svc.cancel_salary_slip(slip, reason, request.user)
        log_event(
            user=request.user, school=school, category='data_change',
            action='salary_slip_cancelled',
            detail={'slip_id': slip.id, 'slip_number': slip.slip_number,
                    'reason': reason},
            request=request,
        )
        messages.success(request, f'Salary slip {slip.slip_number} cancelled.')
        return redirect('salary_slip_detail', slip_id=slip.id)


class RecordSalaryPaymentView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def post(self, request, slip_id):
        school = _get_single_school(request.user)
        slip = get_object_or_404(SalarySlip, id=slip_id, school=school)

        if slip.status in ('cancelled', 'draft'):
            messages.error(request, 'Cannot record payment on this salary slip.')
            return redirect('salary_slip_detail', slip_id=slip.id)

        amount_str = request.POST.get('amount', '').strip()
        date_str = request.POST.get('payment_date', '').strip()
        method = request.POST.get('payment_method', 'bank_transfer')
        notes = request.POST.get('notes', '').strip()

        try:
            amount = Decimal(amount_str)
            if amount <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            messages.error(request, 'Amount must be a positive number.')
            return redirect('salary_slip_detail', slip_id=slip.id)

        payment_date = _parse_date(date_str)
        if not payment_date:
            messages.error(request, 'Valid payment date is required.')
            return redirect('salary_slip_detail', slip_id=slip.id)

        svc.record_salary_payment(
            salary_slip=slip,
            amount=amount,
            payment_date=payment_date,
            payment_method=method,
            notes=notes,
            created_by=request.user,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='salary_paid',
            detail={'slip_id': slip.id, 'slip_number': slip.slip_number,
                    'amount': str(amount), 'payment_method': method,
                    'payment_date': str(payment_date),
                    'teacher_id': slip.teacher_id},
            request=request,
        )
        messages.success(request, f'Payment of ${amount} recorded.')
        return redirect('salary_slip_detail', slip_id=slip.id)


# ===========================================================================
# Teacher Search API
# ===========================================================================

class TeacherSearchAPIView(RoleRequiredMixin, View):
    required_roles = SALARY_ROLES

    def get(self, request):
        school = _get_single_school(request.user)
        if not school:
            return JsonResponse({'results': []})

        q = request.GET.get('q', '').strip()
        if len(q) < 2:
            return JsonResponse({'results': []})

        teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).filter(
            models.Q(teacher__first_name__icontains=q) |
            models.Q(teacher__last_name__icontains=q) |
            models.Q(teacher__username__icontains=q)
        ).select_related('teacher')[:10]

        results = [
            {
                'id': st.teacher.id,
                'text': f'{st.teacher.first_name} {st.teacher.last_name}'.strip() or st.teacher.username,
                'username': st.teacher.username,
            }
            for st in teachers
        ]
        return JsonResponse({'results': results})
