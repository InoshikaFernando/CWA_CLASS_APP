"""
Parent portal views — read-only access to linked children's data.
CPP-67 (invoices & payments), CPP-68 (attendance), CPP-69 (progress).
"""
from django.db.models import Max, Q
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

from accounts.models import Role
from .models import (
    ParentStudent, ClassStudent, ClassSession, StudentAttendance,
    Invoice, InvoicePayment, ProgressRecord, ParentLinkRequest,
    ProgressCriteria,
)
from .views import RoleRequiredMixin


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_parent_children(user):
    """All active parent-student links for this user."""
    return (
        ParentStudent.objects.filter(parent=user, is_active=True)
        .select_related('student', 'school')
    )


def _get_active_child(request):
    """Return (student, school, link) from session or default to first child."""
    children = _get_parent_children(request.user)
    if not children.exists():
        return None, None, None

    active_id = request.session.get('active_child_id')
    if active_id:
        link = children.filter(student_id=active_id).first()
        if link:
            return link.student, link.school, link

    first = children.first()
    request.session['active_child_id'] = first.student_id
    return first.student, first.school, first


def _verify_parent_access(user, student_id):
    """Verify parent has an active link to this student. Returns link or None."""
    return ParentStudent.objects.filter(
        parent=user, student_id=student_id, is_active=True,
    ).select_related('student', 'school').first()


# ---------------------------------------------------------------------------
# Child Switcher
# ---------------------------------------------------------------------------

class ParentChildrenView(RoleRequiredMixin, View):
    """List all linked children (and pending requests) for the parent."""
    required_roles = [Role.PARENT]

    def get(self, request):
        children = _get_parent_children(request.user)
        pending_requests = (
            ParentLinkRequest.objects.filter(
                parent=request.user,
                status=ParentLinkRequest.STATUS_PENDING,
            )
            .select_related('school_student', 'school_student__student', 'school_student__school')
        )
        return render(request, 'parent/children.html', {
            'children': children,
            'pending_requests': pending_requests,
        })


class ParentSwitchChildView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def post(self, request, student_id):
        link = _verify_parent_access(request.user, student_id)
        if link:
            request.session['active_child_id'] = student_id
            from audit.services import log_event
            log_event(
                user=request.user, school=link.school, category='data_change',
                action='parent_switched_child',
                detail={'student_id': student_id, 'student_name': f'{link.student.first_name} {link.student.last_name}'},
                request=request,
            )
        return redirect(request.POST.get('next', 'parent_dashboard'))


# ---------------------------------------------------------------------------
# Dashboard (replaces stub)
# ---------------------------------------------------------------------------

class ParentDashboardView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        children = _get_parent_children(request.user)
        child, school, _ = _get_active_child(request)

        child_summaries = []
        for link in children:
            s = link.student
            sch = link.school

            # Classes count
            class_count = ClassStudent.objects.filter(
                student=s, classroom__school=sch, is_active=True,
            ).count()

            # Attendance %
            completed = ClassSession.objects.filter(
                classroom__students=s, classroom__school=sch, status='completed',
            ).count()
            present_late = StudentAttendance.objects.filter(
                student=s, session__classroom__school=sch,
                status__in=['present', 'late'], session__status='completed',
            ).count()
            att_pct = round(present_late / completed * 100) if completed else 0

            # Outstanding invoices
            outstanding = Invoice.objects.filter(
                student=s, school=sch,
                status__in=['issued', 'partially_paid'],
            ).count()

            child_summaries.append({
                'link': link,
                'class_count': class_count,
                'attendance_pct': att_pct,
                'outstanding_invoices': outstanding,
            })

        pending_requests = (
            ParentLinkRequest.objects.filter(
                parent=request.user,
                status=ParentLinkRequest.STATUS_PENDING,
            )
            .select_related('school_student', 'school_student__student', 'school_student__school')
        )

        return render(request, 'parent/dashboard.html', {
            'children': children,
            'child_summaries': child_summaries,
            'active_child': child,
            'active_school': school,
            'pending_requests': pending_requests,
        })


# ---------------------------------------------------------------------------
# Invoices (CPP-67)
# ---------------------------------------------------------------------------

class ParentInvoicesView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/invoices.html', {
                'invoices': [], 'children': _get_parent_children(request.user),
            })

        invoices = (
            Invoice.objects.filter(
                student=child, school=school,
                status__in=['issued', 'partially_paid', 'paid'],
            )
            .select_related('student')
            .order_by('-billing_period_end', '-created_at')
        )

        return render(request, 'parent/invoices.html', {
            'invoices': invoices,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })


class ParentInvoiceDetailView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request, invoice_id):
        child, school, _ = _get_active_child(request)
        if not child:
            return redirect('parent_invoices')

        invoice = get_object_or_404(
            Invoice, id=invoice_id, student=child, school=school,
            status__in=['issued', 'partially_paid', 'paid'],
        )
        line_items = invoice.line_items.select_related('classroom', 'classroom__department')
        payments = invoice.payments.order_by('-created_at')

        # Get effective settings (with department overrides if applicable)
        primary_dept = None
        for li in line_items:
            if li.classroom and li.classroom.department:
                primary_dept = li.classroom.department
                break
        effective_settings = school.get_effective_settings(primary_dept)

        return render(request, 'parent/invoice_detail.html', {
            'invoice': invoice,
            'line_items': line_items,
            'payments': payments,
            'active_child': child,
            'active_school': school,
            'effective_settings': effective_settings,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Payment History (CPP-67)
# ---------------------------------------------------------------------------

class ParentPaymentHistoryView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/payments.html', {
                'payments': [], 'children': _get_parent_children(request.user),
            })

        payments = (
            InvoicePayment.objects.filter(
                invoice__student=child, invoice__school=school,
                status__in=['confirmed', 'matched'],
            )
            .select_related('invoice')
            .order_by('-payment_date', '-created_at')
        )

        return render(request, 'parent/payments.html', {
            'payments': payments,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Attendance (CPP-68)
# ---------------------------------------------------------------------------

class ParentAttendanceView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/attendance.html', {
                'children': _get_parent_children(request.user),
            })

        enrolled_class_ids = list(
            ClassStudent.objects.filter(
                student=child, classroom__school=school, is_active=True,
            ).values_list('classroom_id', flat=True)
        )

        records = (
            StudentAttendance.objects.filter(
                student=child,
                session__classroom_id__in=enrolled_class_ids,
                session__status='completed',
            )
            .select_related('session', 'session__classroom')
            .order_by('-session__date', '-session__start_time')
        )

        # Overall stats
        total_present = records.filter(status='present').count()
        total_late = records.filter(status='late').count()
        total_absent = records.filter(status='absent').count()
        overall_completed = ClassSession.objects.filter(
            classroom_id__in=enrolled_class_ids, status='completed',
        ).count()
        overall_pct = (
            round((total_present + total_late) / overall_completed * 100)
            if overall_completed else 0
        )

        # Per-class summaries
        from classroom.models import ClassRoom
        class_summaries = []
        for cls in ClassRoom.objects.filter(id__in=enrolled_class_ids):
            cls_records = records.filter(session__classroom=cls)
            completed = ClassSession.objects.filter(
                classroom=cls, status='completed',
            ).count()
            present = cls_records.filter(status='present').count()
            late = cls_records.filter(status='late').count()
            absent = cls_records.filter(status='absent').count()
            pct = round((present + late) / completed * 100) if completed else 0
            class_summaries.append({
                'classroom': cls,
                'completed': completed,
                'present': present,
                'late': late,
                'absent': absent,
                'pct': pct,
            })

        return render(request, 'parent/attendance.html', {
            'attendance_records': records[:50],
            'class_summaries': class_summaries,
            'total_present': total_present,
            'total_late': total_late,
            'total_absent': total_absent,
            'overall_completed': overall_completed,
            'overall_pct': overall_pct,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Progress (CPP-69)
# ---------------------------------------------------------------------------

class ParentProgressView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/progress.html', {
                'children': _get_parent_children(request.user),
            })

        # All approved criteria for this school
        approved_criteria = (
            ProgressCriteria.objects.filter(
                school=school,
                status='approved',
            )
            .select_related('subject', 'level')
            .order_by('subject__name', 'level__level_number', 'order')
        )

        # Latest progress record per criteria for this student at this school
        latest_ids = (
            ProgressRecord.objects.filter(
                student=child,
                criteria__school=school,
                criteria__status='approved',
            )
            .values('criteria_id')
            .annotate(latest_id=Max('id'))
            .values_list('latest_id', flat=True)
        )
        records_by_criteria = {
            rec.criteria_id: rec
            for rec in ProgressRecord.objects.filter(id__in=latest_ids).select_related(
                'criteria', 'recorded_by', 'session', 'session__classroom',
            )
        }

        # Group criteria by (subject, level), merging in student records
        grouped = {}
        for criteria in approved_criteria:
            key = (criteria.subject_id, criteria.level_id)
            if key not in grouped:
                grouped[key] = {
                    'subject': criteria.subject,
                    'level': criteria.level,
                    'entries': [],
                }
            rec = records_by_criteria.get(criteria.id)
            grouped[key]['entries'].append({
                'criteria': criteria,
                'status': rec.status if rec else 'not_assessed',
                'notes': rec.notes if rec else '',
                'recorded_at': rec.recorded_at if rec else None,
                'recorded_by': rec.recorded_by if rec else None,
                'classroom': rec.session.classroom if (rec and rec.session_id) else None,
            })

        # Sort and compute stats
        grouped_progress = []
        overall = {'total': 0, 'achieved': 0, 'in_progress': 0, 'not_started': 0, 'not_assessed': 0}
        for group in sorted(grouped.values(), key=lambda g: (
            g['subject'].name if g['subject'] else '',
            g['level'].level_number if g['level'] else 0,
        )):
            entries = group['entries']
            total = len(entries)
            achieved = sum(1 for e in entries if e['status'] == 'achieved')
            in_progress = sum(1 for e in entries if e['status'] == 'in_progress')
            not_assessed = sum(1 for e in entries if e['status'] == 'not_assessed')
            not_started = total - achieved - in_progress - not_assessed
            group['total'] = total
            group['achieved'] = achieved
            group['in_progress'] = in_progress
            group['not_started'] = not_started
            group['not_assessed'] = not_assessed
            grouped_progress.append(group)
            overall['total'] += total
            overall['achieved'] += achieved
            overall['in_progress'] += in_progress
            overall['not_started'] += not_started
            overall['not_assessed'] += not_assessed

        return render(request, 'parent/progress.html', {
            'grouped_progress': grouped_progress,
            'overall': overall,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })
