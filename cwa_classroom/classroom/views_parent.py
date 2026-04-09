"""
Parent portal views — read-only access to linked children's data.
CPP-67 (invoices & payments), CPP-68 (attendance), CPP-69 (progress).
"""
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.db.models import Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.views import View

from accounts.models import Role
from .models import (
    ParentStudent, ClassStudent, ClassSession, StudentAttendance,
    Invoice, InvoicePayment, ProgressRecord, ParentLinkRequest,
    ProgressCriteria, SchoolStudent, ClassRoom,
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
        children = _get_parent_children(request.user)
        if not children.exists():
            return render(request, 'parent/invoices.html', {
                'invoices': [], 'children': children, 'page': None,
                'total_outstanding': Decimal('0.00'),
            })

        # All children's student IDs for this parent
        child_ids = children.values_list('student_id', flat=True)

        search = request.GET.get('q', '').strip()
        status_filter = request.GET.get('status', '').strip()

        allowed_statuses = ['issued', 'partially_paid', 'paid']
        invoices = (
            Invoice.objects.filter(student_id__in=child_ids, status__in=allowed_statuses)
            .select_related('student', 'school')
            .order_by('due_date', 'created_at')
        )

        if search:
            invoices = invoices.filter(
                Q(invoice_number__icontains=search) |
                Q(student__first_name__icontains=search) |
                Q(student__last_name__icontains=search)
            )
        if status_filter and status_filter in allowed_statuses:
            invoices = invoices.filter(status=status_filter)

        # Compute total outstanding across all children (unpaginated)
        outstanding_invoices = Invoice.objects.filter(
            student_id__in=child_ids, status__in=['issued', 'partially_paid'],
        )
        total_outstanding = Decimal('0.00')
        for inv in outstanding_invoices:
            total_outstanding += inv.amount_due

        paginator = Paginator(invoices, 25)
        page = paginator.get_page(request.GET.get('page'))

        ctx = {
            'invoices': page,
            'page': page,
            'children': children,
            'search': search,
            'status_filter': status_filter,
            'total_outstanding': total_outstanding,
        }
        if request.headers.get('HX-Request'):
            return render(request, 'parent/partials/invoice_table.html', ctx)
        return render(request, 'parent/invoices.html', ctx)


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
            'stripe_payment_link': invoice.get_stripe_payment_link(),
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
# Invoice Stripe Checkout (Option B — dynamic Checkout Session)
# ---------------------------------------------------------------------------

class ParentInvoiceCheckoutView(RoleRequiredMixin, View):
    """
    POST: Create a Stripe Checkout Session for the parent to pay outstanding invoices.
    Accepts optional 'amount' override; defaults to full outstanding balance.
    Allocates oldest invoices first.
    """
    required_roles = [Role.PARENT]

    def post(self, request):
        from billing.stripe_service import create_invoice_checkout_session, calculate_stripe_fee

        children = _get_parent_children(request.user)
        if not children.exists():
            return JsonResponse({'error': 'No linked children found.'}, status=400)

        child_ids = list(children.values_list('student_id', flat=True))

        # Gather all outstanding invoices, oldest first
        outstanding = list(
            Invoice.objects.filter(
                student_id__in=child_ids,
                status__in=['issued', 'partially_paid'],
            ).order_by('due_date', 'created_at')
        )

        if not outstanding:
            return JsonResponse({'error': 'No outstanding invoices.'}, status=400)

        total_outstanding = sum(inv.amount_due for inv in outstanding)

        # Determine amount to apply
        raw_amount = request.POST.get('amount', '').strip()
        try:
            amount_applied = Decimal(raw_amount) if raw_amount else total_outstanding
            amount_applied = amount_applied.quantize(Decimal('0.01'))
        except Exception:
            return JsonResponse({'error': 'Invalid amount.'}, status=400)

        if amount_applied <= Decimal('0'):
            return JsonResponse({'error': 'Amount must be greater than zero.'}, status=400)

        # Build allocation list: oldest invoice first, up to amount_applied
        remaining = amount_applied
        allocations = []
        for inv in outstanding:
            if remaining <= 0:
                break
            alloc = min(inv.amount_due, remaining)
            allocations.append({'invoice_id': inv.pk, 'amount': str(alloc)})
            remaining -= alloc

        try:
            isp, session = create_invoice_checkout_session(
                parent=request.user,
                amount_applied=amount_applied,
                invoice_allocations=allocations,
                request=request,
            )
        except Exception as exc:
            import logging
            logging.getLogger(__name__).error('Invoice checkout session error: %s', exc)
            return JsonResponse({'error': 'Payment could not be initiated. Please try again.'}, status=500)

        return JsonResponse({'checkout_url': session.url})


class ParentInvoicePaymentSuccessView(RoleRequiredMixin, View):
    """
    Success page shown after a parent completes Stripe checkout.
    Stripe webhook will handle the actual InvoicePayment creation asynchronously.
    """
    required_roles = [Role.PARENT]

    def get(self, request):
        from billing.models import InvoiceStripePayment

        isp_id = request.GET.get('isp_id')
        isp = None
        if isp_id:
            isp = InvoiceStripePayment.objects.filter(
                pk=isp_id, parent=request.user,
            ).first()

        return render(request, 'parent/invoice_pay_success.html', {
            'isp': isp,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Parent Billing (subscription info)
# ---------------------------------------------------------------------------

class ParentBillingView(RoleRequiredMixin, View):
    """Show the parent's own subscription details (same as individual student view)."""
    required_roles = [Role.PARENT]

    def get(self, request):
        from billing.models import Subscription

        subscription = None
        try:
            subscription = request.user.subscription
        except Subscription.DoesNotExist:
            pass

        return render(request, 'parent/billing.html', {
            'subscription': subscription,
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

        from django.db.models import Count, Sum, Case, When, IntegerField

        module_activity = []

        # --- Maths: per-topic accuracy from StudentAnswer ---
        from maths.models import StudentAnswer
        maths_rows = (
            StudentAnswer.objects
            .filter(student=child)
            .values('question__topic__name')
            .annotate(
                total=Count('id'),
                correct=Sum(Case(When(is_correct=True, then=1), default=0, output_field=IntegerField())),
            )
            .order_by('question__topic__name')
        )
        if maths_rows.exists():
            module_activity.append({
                'module': 'Maths',
                'rows': [
                    {
                        'label': row['question__topic__name'] or 'Uncategorised',
                        'total': row['total'],
                        'correct': row['correct'] or 0,
                        'pct': round((row['correct'] or 0) / row['total'] * 100) if row['total'] else 0,
                    }
                    for row in maths_rows
                ],
            })

        # --- Number Puzzles: per-level stats from StudentPuzzleProgress ---
        from number_puzzles.models import StudentPuzzleProgress
        puzzle_rows = (
            StudentPuzzleProgress.objects
            .filter(student=child, total_puzzles_attempted__gt=0)
            .select_related('level')
            .order_by('level__order')
        )
        if puzzle_rows.exists():
            module_activity.append({
                'module': 'Number Puzzles',
                'rows': [
                    {
                        'label': str(row.level),
                        'total': row.total_puzzles_attempted,
                        'correct': row.total_puzzles_correct,
                        'pct': round(row.total_puzzles_correct / row.total_puzzles_attempted * 100) if row.total_puzzles_attempted else 0,
                    }
                    for row in puzzle_rows
                ],
            })

        # --- Coding module (future): add here when available ---

        # --- Recent activity: latest 20 across all modules ---
        from maths.models import StudentFinalAnswer, BasicFactsResult
        from classroom.views import _format_seconds

        sfa_entries = list(
            StudentFinalAnswer.objects
            .filter(student=child)
            .select_related('topic', 'level')
            .order_by('-completed_at')[:20]
        )
        bf_entries = list(
            BasicFactsResult.objects
            .filter(student=child)
            .order_by('-completed_at')[:20]
        )
        try:
            from number_puzzles.models import PuzzleSession
            np_entries = list(
                PuzzleSession.objects
                .filter(student=child, status='completed')
                .select_related('level')
                .order_by('-completed_at')[:20]
            )
        except Exception:
            np_entries = []

        # Merge and sort all activity by completed_at, take latest 20
        all_activity = []
        for e in sfa_entries:
            label = str(e.topic) if e.topic else 'Quiz'
            all_activity.append({
                'type': 'maths',
                'label': label,
                'score': e.score,
                'total': e.total_questions,
                'pct': round(e.score / e.total_questions * 100) if e.total_questions else 0,
                'completed_at': e.completed_at,
            })
        for e in bf_entries:
            all_activity.append({
                'type': 'basic_facts',
                'label': 'Basic Facts',
                'score': e.score,
                'total': e.total_questions,
                'pct': round(e.score / e.total_questions * 100) if e.total_questions else 0,
                'completed_at': e.completed_at,
            })
        for e in np_entries:
            all_activity.append({
                'type': 'number_puzzles',
                'label': f'Number Puzzles – {e.level}',
                'score': e.correct_count if hasattr(e, 'correct_count') else None,
                'total': None,
                'pct': None,
                'completed_at': e.completed_at,
            })
        all_activity.sort(key=lambda x: x['completed_at'], reverse=True)
        recent_activity = all_activity[:20]

        # --- Time spent (quiz/task time only, calculated fresh from activity records) ---
        from django.utils import timezone
        from django.utils.timezone import localtime
        from datetime import timedelta as _td
        _now = localtime(timezone.now())
        _today = _now.date()
        _week_start = _today - _td(days=_now.weekday())

        daily_secs = weekly_secs = 0
        for r in StudentFinalAnswer.objects.filter(student=child, time_taken_seconds__gt=0):
            r_date = localtime(r.completed_at).date()
            if r_date == _today:
                daily_secs += r.time_taken_seconds
            if r_date >= _week_start:
                weekly_secs += r.time_taken_seconds
        for r in BasicFactsResult.objects.filter(student=child, time_taken_seconds__gt=0):
            r_date = localtime(r.completed_at).date()
            if r_date == _today:
                daily_secs += r.time_taken_seconds
            if r_date >= _week_start:
                weekly_secs += r.time_taken_seconds

        time_daily = _format_seconds(daily_secs)
        time_weekly = _format_seconds(weekly_secs)

        return render(request, 'parent/progress.html', {
            'grouped_progress': grouped_progress,
            'overall': overall,
            'active_child': child,
            'active_school': school,
            'module_activity': module_activity,
            'recent_activity': recent_activity,
            'time_daily': time_daily,
            'time_weekly': time_weekly,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Parent Homework View — child's homework assignments + submission status
# ---------------------------------------------------------------------------

class ParentHomeworkView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        child, school, _ = _get_active_child(request)
        if not child:
            return render(request, 'parent/homework.html', {
                'children': _get_parent_children(request.user),
            })

        from homework.models import Homework, HomeworkSubmission

        class_ids = ClassStudent.objects.filter(
            student=child, is_active=True,
        ).values_list('classroom_id', flat=True)

        homeworks = (
            Homework.objects
            .filter(classroom_id__in=class_ids)
            .select_related('classroom')
            .order_by('-created_at')
        )

        # Attach submission status for each homework
        homework_list = []
        for hw in homeworks:
            best = HomeworkSubmission.get_best_submission(hw, child)
            attempt_count = HomeworkSubmission.get_attempt_count(hw, child)
            if best:
                if hw.due_date and best.submitted_at and best.submitted_at > hw.due_date:
                    status = 'late'
                else:
                    status = 'submitted'
            else:
                from django.utils import timezone
                if hw.due_date and hw.due_date < timezone.now():
                    status = 'not_submitted'
                else:
                    status = 'pending'
            homework_list.append({
                'homework': hw,
                'status': status,
                'score': best.score if best else None,
                'total_questions': best.total_questions if best else None,
                'submitted_at': best.submitted_at if best else None,
                'attempt_count': attempt_count,
            })

        return render(request, 'parent/homework.html', {
            'child': child,
            'school': school,
            'homework_list': homework_list,
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
            )
            .prefetch_related('classroom__class_teachers__teacher')
            .order_by('classroom__day', 'classroom__start_time', 'classroom__name')
        )

        # Upcoming sessions (next 14 days)
        from django.utils import timezone
        import datetime
        today = timezone.now().date()
        enrolled_ids = list(enrollments.values_list('classroom_id', flat=True))
        upcoming = (
            ClassSession.objects.filter(
                classroom_id__in=enrolled_ids,
                date__gte=today,
                date__lte=today + datetime.timedelta(days=14),
                status__in=['scheduled', 'in_progress'],
            )
            .select_related('classroom')
            .order_by('date', 'start_time')
        )

        return render(request, 'parent/classes.html', {
            'enrollments': enrollments,
            'upcoming_sessions': upcoming,
            'active_child': child,
            'active_school': school,
            'children': _get_parent_children(request.user),
        })


# ---------------------------------------------------------------------------
# Become a Parent (for existing users — teachers, HoI, etc.)
# ---------------------------------------------------------------------------

class BecomeParentView(LoginRequiredMixin, View):
    """
    Allow any authenticated user (e.g. a teacher whose child attends the school)
    to register as a parent without creating a new account.

    Flow:
    1. User fills in their child's Student ID and relationship.
    2. A ParentLinkRequest is created (pending teacher/HoI approval).
    3. The PARENT role is added to their existing account immediately so they can
       see the parent dashboard (with a "pending" state).
    4. active_role in session is set to 'parent' so they land on the parent UI.
    5. The topbar role-switcher automatically appears (multi-role user).
    6. When approved, the ParentStudent link is created by the existing
       ParentLinkApproveView — no further changes needed there.
    """

    RELATIONSHIP_CHOICES = [
        ('mother', 'Mother'),
        ('father', 'Father'),
        ('guardian', 'Guardian'),
        ('other', 'Other'),
    ]

    def get(self, request):
        if request.user.has_role(Role.PARENT):
            return redirect('parent_dashboard')
        return render(request, 'parent/become_parent.html', {
            'relationship_choices': self.RELATIONSHIP_CHOICES,
        })

    def post(self, request):
        if request.user.has_role(Role.PARENT):
            return redirect('parent_dashboard')

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
                errors['student_id'] = (
                    f'Student ID "{student_id_code}" was not found. '
                    'Please check the ID and try again.'
                )
            else:
                # Already have a pending or approved request?
                if ParentLinkRequest.objects.filter(
                    parent=request.user,
                    school_student=school_student,
                    status__in=[ParentLinkRequest.STATUS_PENDING,
                                 ParentLinkRequest.STATUS_APPROVED],
                ).exists():
                    errors['student_id'] = 'You already have an active request for this student.'
                # Already directly linked?
                elif ParentStudent.objects.filter(
                    parent=request.user,
                    student=school_student.student,
                ).exists():
                    errors['student_id'] = 'You are already linked to this student.'
                # Max 2 parents per student
                else:
                    parent_count = ParentStudent.objects.filter(
                        student=school_student.student,
                        school=school_student.school,
                        is_active=True,
                    ).count()
                    if parent_count >= 2:
                        errors['student_id'] = (
                            f'{school_student.student.first_name} already has the '
                            'maximum number of parent accounts linked.'
                        )

        if errors:
            return render(request, 'parent/become_parent.html', {
                'errors': errors,
                'relationship_choices': self.RELATIONSHIP_CHOICES,
                'form_data': {'student_id': student_id_code, 'relationship': relationship},
            })

        from accounts.models import UserRole
        from django.db import transaction

        with transaction.atomic():
            # Add PARENT role to the existing account if not already there
            parent_role, _ = Role.objects.get_or_create(
                name=Role.PARENT,
                defaults={'display_name': 'Parent'},
            )
            UserRole.objects.get_or_create(user=request.user, role=parent_role)

            # Create the pending link request (requires teacher/HoI approval)
            ParentLinkRequest.objects.create(
                parent=request.user,
                school_student=school_student,
                relationship=relationship,
                status=ParentLinkRequest.STATUS_PENDING,
            )

        # Switch active role so they land on the parent dashboard
        request.session['active_role'] = Role.PARENT

        try:
            from audit.services import log_event
            log_event(
                user=request.user, school=school_student.school,
                category='data_change', action='user_added_parent_role',
                detail={
                    'student_id_code': student_id_code,
                    'relationship': relationship,
                },
                request=request,
            )
        except Exception:
            pass

        messages.success(
            request,
            f'Your request to link with '
            f'{school_student.student.first_name} {school_student.student.last_name} '
            f'has been submitted. You will be notified once a teacher approves it.'
        )
        return redirect('parent_dashboard')
