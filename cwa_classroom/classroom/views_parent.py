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
    Invoice, InvoicePayment, ProgressRecord, SchoolStudent, ClassRoom,
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

        return render(request, 'parent/dashboard.html', {
            'children': children,
            'child_summaries': child_summaries,
            'active_child': child,
            'active_school': school,
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

        # Get latest progress record per criteria for this student
        latest_ids = (
            ProgressRecord.objects.filter(student=child)
            .values('criteria_id')
            .annotate(latest_id=Max('id'))
            .values_list('latest_id', flat=True)
        )

        records = (
            ProgressRecord.objects.filter(id__in=latest_ids)
            .select_related(
                'criteria', 'criteria__subject', 'criteria__level',
                'recorded_by',
            )
            .order_by(
                'criteria__subject__name',
                'criteria__level__level_number',
                'criteria__order',
            )
        )

        # Group by (subject, level)
        grouped = {}
        for rec in records:
            key = (rec.criteria.subject_id, rec.criteria.level_id)
            if key not in grouped:
                grouped[key] = {
                    'subject': rec.criteria.subject,
                    'level': rec.criteria.level,
                    'records': [],
                }
            grouped[key]['records'].append(rec)

        # Calculate stats per group
        grouped_progress = []
        overall = {'total': 0, 'achieved': 0, 'in_progress': 0, 'not_started': 0}
        for group in sorted(grouped.values(), key=lambda g: (
            g['subject'].name if g['subject'] else '',
            g['level'].level_number if g['level'] else 0,
        )):
            recs = group['records']
            total = len(recs)
            achieved = sum(1 for r in recs if r.status == 'achieved')
            in_progress = sum(1 for r in recs if r.status == 'in_progress')
            not_started = total - achieved - in_progress
            group['total'] = total
            group['achieved'] = achieved
            group['in_progress'] = in_progress
            group['not_started'] = not_started
            grouped_progress.append(group)
            overall['total'] += total
            overall['achieved'] += achieved
            overall['in_progress'] += in_progress
            overall['not_started'] += not_started

        return render(request, 'parent/progress.html', {
            'grouped_progress': grouped_progress,
            'overall': overall,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Add Child (logged-in parent links another student via Student ID)
# ---------------------------------------------------------------------------

class ParentAddChildView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]
    RELATIONSHIP_CHOICES = [
        ('mother', 'Mother'),
        ('father', 'Father'),
        ('guardian', 'Guardian'),
        ('other', 'Other'),
    ]

    def get(self, request):
        return render(request, 'parent/add_child.html', {
            'children': _get_parent_children(request.user),
            'relationship_choices': self.RELATIONSHIP_CHOICES,
        })

    def post(self, request):
        student_id_code = request.POST.get('student_id', '').strip().upper()
        relationship = request.POST.get('relationship', 'guardian').strip()
        errors = {}

        if not student_id_code:
            errors['student_id'] = 'Student ID is required.'
        else:
            school_student = SchoolStudent.objects.filter(
                student_id_code=student_id_code, is_active=True,
            ).select_related('school', 'student').first()

            if not school_student:
                errors['student_id'] = f'Student ID "{student_id_code}" was not found. Please check and try again.'
            else:
                # Already linked?
                if ParentStudent.objects.filter(
                    parent=request.user,
                    student=school_student.student,
                    school=school_student.school,
                ).exists():
                    errors['student_id'] = 'You are already linked to this student.'
                else:
                    # Max 2 parents per student
                    parent_count = ParentStudent.objects.filter(
                        student=school_student.student,
                        school=school_student.school,
                        is_active=True,
                    ).count()
                    if parent_count >= 2:
                        errors['student_id'] = (
                            f'{school_student.student.first_name} already has the '
                            f'maximum number of parent accounts linked.'
                        )

        if errors:
            return render(request, 'parent/add_child.html', {
                'errors': errors,
                'children': _get_parent_children(request.user),
                'relationship_choices': self.RELATIONSHIP_CHOICES,
                'form_data': {'student_id': student_id_code, 'relationship': relationship},
            })

        existing_count = ParentStudent.objects.filter(
            student=school_student.student,
            school=school_student.school,
            is_active=True,
        ).count()
        link = ParentStudent.objects.create(
            parent=request.user,
            student=school_student.student,
            school=school_student.school,
            relationship=relationship,
            is_primary_contact=(existing_count == 0),
            created_by=request.user,
        )

        # Switch to newly added child
        request.session['active_child_id'] = school_student.student_id

        from audit.services import log_event
        log_event(
            user=request.user, school=school_student.school,
            category='data_change', action='parent_linked_child',
            detail={'student_id_code': student_id_code, 'relationship': relationship},
            request=request,
        )

        from django.contrib import messages
        messages.success(
            request,
            f'{school_student.student.first_name} {school_student.student.last_name} '
            f'has been linked to your account.'
        )
        return redirect('parent_dashboard')


# ---------------------------------------------------------------------------
# Classes / Schedule
# ---------------------------------------------------------------------------

class ParentClassesView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/classes.html', {
                'children': _get_parent_children(request.user),
                'enrollments': [],
            })

        enrollments = (
            ClassStudent.objects.filter(
                student=child, classroom__school=school, is_active=True,
            )
            .select_related(
                'classroom', 'classroom__department',
                'classroom__teacher', 'classroom__teacher__teacher',
            )
            .order_by('classroom__day', 'classroom__start_time', 'classroom__name')
        )

        # Upcoming sessions (next 14 days)
        from django.utils import timezone
        import datetime
        today = timezone.now().date()
        upcoming = (
            ClassSession.objects.filter(
                classroom__classstudent__student=child,
                classroom__school=school,
                date__gte=today,
                date__lte=today + datetime.timedelta(days=14),
                status__in=['scheduled', 'in_progress'],
            )
            .select_related('classroom')
            .order_by('date', 'start_time')
            .distinct()
        )

        return render(request, 'parent/classes.html', {
            'enrollments': enrollments,
            'upcoming_sessions': upcoming,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })
