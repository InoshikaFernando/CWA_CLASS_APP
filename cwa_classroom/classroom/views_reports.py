import csv
import logging
from decimal import Decimal

from django import forms
from django.core.paginator import Paginator
from django.db.models import Count, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from accounts.models import Role
from classroom.models import (
    ClassRoom, ClassStudent, ClassTeacher, Department, DepartmentTeacher,
    Expense, Invoice, InvoiceLineItem, InvoicePayment,
    ParentStudent, School, SchoolStudent, SchoolTeacher, StudentGuardian,
    Subject,
)
from classroom.views import RoleRequiredMixin, _get_user_school_ids

from django.views import View

logger = logging.getLogger(__name__)

PAGE_SIZE = 50


class ReportFilterForm(forms.Form):
    class_id = forms.IntegerField(required=False)
    status = forms.ChoiceField(
        choices=[('all', 'All'), ('active', 'Active'), ('inactive', 'Inactive')],
        required=False,
        initial='all',
    )
    payment = forms.ChoiceField(
        choices=[('all', 'All'), ('blocked', 'Payment blocked'), ('ok', 'OK')],
        required=False,
        initial='all',
    )
    no_class = forms.BooleanField(required=False)


def _get_all_school_ids(user):
    """School IDs accessible to any admin role — HoI, Owner, HoD, or school admin."""
    if user.is_superuser:
        return list(School.objects.filter(is_active=True).values_list('id', flat=True))
    via_school_teacher = set(
        SchoolTeacher.objects.filter(teacher=user, is_active=True).values_list('school_id', flat=True)
    )
    via_admin = set(School.objects.filter(admin=user, is_active=True).values_list('id', flat=True))
    via_dept = set(Department.objects.filter(head=user, is_active=True).values_list('school_id', flat=True))
    via_class = set(ClassRoom.objects.filter(teachers=user, is_active=True).values_list('school_id', flat=True))
    return list(via_school_teacher | via_admin | via_dept | via_class)


def _get_hod_dept_ids(user):
    """Return department IDs accessible to a HoD-only user."""
    headed = list(Department.objects.filter(head=user, is_active=True).values_list('id', flat=True))
    teaching = list(
        ClassRoom.objects.filter(teachers=user, is_active=True, department__isnull=False)
        .values_list('department_id', flat=True)
        .distinct()
    )
    return list(set(headed) | set(teaching))


def _is_hod_only(user):
    return (
        user.has_role(Role.HEAD_OF_DEPARTMENT)
        and not user.has_role(Role.HEAD_OF_INSTITUTE)
        and not user.has_role(Role.INSTITUTE_OWNER)
        and not user.is_superuser
    )


class StudentReportView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        hod_only = _is_hod_only(request.user)
        dept_ids = _get_hod_dept_ids(request.user) if hod_only else []

        # Classes available for filter dropdown — scoped to accessible dept/school
        if hod_only:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                department_id__in=dept_ids,
                is_active=True,
            ).order_by('name')
        else:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                is_active=True,
            ).order_by('name')

        form = ReportFilterForm(request.GET or None)
        filters = {}
        if form.is_valid():
            filters = form.cleaned_data

        qs = self._build_queryset(school_ids, hod_only, dept_ids, filters)

        # CSV export — same filters, no pagination, with parent contact details
        if request.GET.get('export') == 'csv':
            return self._export_csv(qs, school_ids)

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        context = {
            'page_obj': page_obj,
            'form': form,
            'available_classes': available_classes,
            'total_count': paginator.count,
            'filters': filters,
            'is_hod_only': hod_only,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'reports/_partials/student_report_table.html', context)

        return render(request, 'reports/students.html', context)

    @staticmethod
    def _build_queryset(school_ids, hod_only, dept_ids, filters):
        # Base queryset — school-scoped
        qs = SchoolStudent.objects.filter(
            school_id__in=school_ids,
        ).select_related('student').annotate(
            active_class_count=Count(
                'student__class_student_entries',
                filter=Q(
                    student__class_student_entries__is_active=True,
                    student__class_student_entries__classroom__school_id__in=school_ids,
                ),
                distinct=True,
            )
        )

        # HoD: restrict to students in their departments' classes
        if hod_only and dept_ids:
            dept_student_ids = ClassStudent.objects.filter(
                classroom__department_id__in=dept_ids,
                classroom__school_id__in=school_ids,
                is_active=True,
            ).values_list('student_id', flat=True).distinct()
            qs = qs.filter(student_id__in=dept_student_ids)
        elif hod_only and not dept_ids:
            return qs.none()

        # Apply filters
        class_id = filters.get('class_id')
        if class_id:
            class_student_ids = ClassStudent.objects.filter(
                classroom_id=class_id,
                classroom__school_id__in=school_ids,
                is_active=True,
            ).values_list('student_id', flat=True)
            qs = qs.filter(student_id__in=class_student_ids)

        status = filters.get('status') or 'all'
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        payment = filters.get('payment') or 'all'
        if payment == 'blocked':
            qs = qs.filter(student__is_blocked=True)
        elif payment == 'ok':
            qs = qs.filter(student__is_blocked=False)

        if filters.get('no_class'):
            qs = qs.filter(active_class_count=0)

        return qs.order_by('student__first_name', 'student__last_name')

    # How many parent/guardian contacts to export per student.
    MAX_PARENTS = 2

    @staticmethod
    def _parents_by_student(student_ids, school_ids):
        """Map student_id -> list of parent dicts (name/email/phone/relationship).

        Combines linked parent users (ParentStudent) and guardian records
        (StudentGuardian), primary contacts first, de-duplicated by email.
        """
        contacts = {sid: [] for sid in student_ids}

        # Linked parent users — scoped to the accessible schools, plus
        # individual (no-school) links which apply regardless of school.
        parent_links = ParentStudent.objects.filter(
            Q(school_id__in=school_ids) | Q(school__isnull=True),
            student_id__in=student_ids,
            is_active=True,
        ).select_related('parent')
        for link in parent_links:
            p = link.parent
            contacts.setdefault(link.student_id, []).append({
                'primary': link.is_primary_contact,
                'name': p.get_full_name() or p.username,
                'email': p.email or '',
                'phone': p.phone or '',
                'relationship': link.get_relationship_display() if link.relationship else '',
            })

        # Guardian records — scoped to the accessible schools so a student
        # enrolled in more than one school never leaks another school's contacts.
        guardian_links = StudentGuardian.objects.filter(
            student_id__in=student_ids,
            guardian__school_id__in=school_ids,
        ).select_related('guardian')
        for sg in guardian_links:
            g = sg.guardian
            contacts.setdefault(sg.student_id, []).append({
                'primary': sg.is_primary,
                'name': f'{g.first_name} {g.last_name}'.strip(),
                'email': g.email or '',
                'phone': g.phone or '',
                'relationship': g.get_relationship_display() if g.relationship else '',
            })

        result = {}
        for sid, parents in contacts.items():
            # Primary contacts first (stable sort keeps source order otherwise),
            # then de-duplicate by email (falling back to name).
            parents.sort(key=lambda p: not p['primary'])
            seen = set()
            unique = []
            for p in parents:
                key = p['email'].lower() if p['email'] else p['name'].lower()
                if key in seen:
                    continue
                seen.add(key)
                unique.append(p)
            result[sid] = unique
        return result

    @staticmethod
    def _csv_safe(value):
        """Neutralise CSV formula injection.

        Spreadsheet apps treat a leading =, +, -, @ (or tab/CR) as a formula.
        Prefix such values with a single quote so they render as plain text.
        """
        text = '' if value is None else str(value)
        if text and text[0] in ('=', '+', '-', '@', '\t', '\r'):
            return "'" + text
        return text

    @staticmethod
    def _subscribed_student_ids(student_ids):
        """Set of student ids with an active or trialing subscription."""
        from billing.models import Subscription
        return set(
            Subscription.objects.filter(
                user_id__in=student_ids,
                status__in=(Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING),
            ).values_list('user_id', flat=True)
        )

    def _export_csv(self, qs, school_ids):
        rows = list(qs)
        student_ids = [ss.student_id for ss in rows]
        parent_map = self._parents_by_student(student_ids, school_ids)
        subscribed_ids = self._subscribed_student_ids(student_ids)

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="student_report.csv"'
        writer = csv.writer(response)

        header = [
            'Student Name', 'Username', 'Student Email', 'Student ID',
            'Active Classes', 'Enrollment', 'Payment', 'Is Subscribed',
        ]
        for i in range(1, self.MAX_PARENTS + 1):
            header += [f'Parent {i} Name', f'Parent {i} Email',
                       f'Parent {i} Phone', f'Parent {i} Relationship']
        writer.writerow(header)

        for ss in rows:
            student = ss.student
            parents = parent_map.get(ss.student_id, [])
            row = [
                student.get_full_name() or student.username,
                student.username,
                student.email or '',
                ss.student_id_code or '',
                ss.active_class_count,
                'Active' if ss.is_active else 'Inactive',
                'Blocked' if student.is_blocked else 'OK',
                'Yes' if ss.student_id in subscribed_ids else 'No',
            ]
            for i in range(self.MAX_PARENTS):
                p = parents[i] if i < len(parents) else {}
                row += [p.get('name', ''), p.get('email', ''),
                        p.get('phone', ''), p.get('relationship', '')]
            writer.writerow([self._csv_safe(v) for v in row])
        return response


class TeacherReportFilterForm(forms.Form):
    class_id = forms.IntegerField(required=False)
    subject_id = forms.IntegerField(required=False)
    department_id = forms.IntegerField(required=False)
    status = forms.ChoiceField(
        choices=[('all', 'All'), ('active', 'Active'), ('inactive', 'Inactive')],
        required=False,
        initial='all',
    )
    role = forms.ChoiceField(
        choices=[('all', 'All')] + SchoolTeacher.ROLE_CHOICES,
        required=False,
        initial='all',
    )
    no_class = forms.BooleanField(required=False)


class TeacherReportView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        hod_only = _is_hod_only(request.user)
        dept_ids = _get_hod_dept_ids(request.user) if hod_only else []

        if hod_only:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                department_id__in=dept_ids,
                is_active=True,
            ).order_by('name')
            available_departments = Department.objects.filter(
                id__in=dept_ids, is_active=True,
            ).order_by('name')
            available_subjects = Subject.objects.filter(
                classrooms__school_id__in=school_ids,
                classrooms__department_id__in=dept_ids,
                classrooms__is_active=True,
            ).distinct().order_by('name')
        else:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids,
                is_active=True,
            ).order_by('name')
            available_departments = Department.objects.filter(
                school_id__in=school_ids, is_active=True,
            ).order_by('name')
            available_subjects = Subject.objects.filter(
                classrooms__school_id__in=school_ids,
                classrooms__is_active=True,
            ).distinct().order_by('name')

        form = TeacherReportFilterForm(request.GET or None)
        filters = {}
        if form.is_valid():
            filters = form.cleaned_data

        qs = SchoolTeacher.objects.filter(
            school_id__in=school_ids,
        ).select_related('teacher').annotate(
            active_class_count=Count(
                'teacher__class_teacher_entries',
                filter=Q(
                    teacher__class_teacher_entries__classroom__school_id__in=school_ids,
                    teacher__class_teacher_entries__classroom__is_active=True,
                ),
                distinct=True,
            ),
        )

        if hod_only and dept_ids:
            dept_teacher_ids = DepartmentTeacher.objects.filter(
                department_id__in=dept_ids,
                department__school_id__in=school_ids,
            ).values_list('teacher_id', flat=True).distinct()
            class_teacher_ids = ClassTeacher.objects.filter(
                classroom__department_id__in=dept_ids,
                classroom__school_id__in=school_ids,
                classroom__is_active=True,
            ).values_list('teacher_id', flat=True).distinct()
            visible_ids = set(dept_teacher_ids) | set(class_teacher_ids)
            qs = qs.filter(teacher_id__in=visible_ids)
        elif hod_only and not dept_ids:
            qs = qs.none()

        class_id = filters.get('class_id')
        if class_id:
            teacher_ids = ClassTeacher.objects.filter(
                classroom_id=class_id,
                classroom__school_id__in=school_ids,
            ).values_list('teacher_id', flat=True)
            qs = qs.filter(teacher_id__in=teacher_ids)

        subject_id = filters.get('subject_id')
        if subject_id:
            teacher_ids = ClassTeacher.objects.filter(
                classroom__subject_id=subject_id,
                classroom__school_id__in=school_ids,
                classroom__is_active=True,
            ).values_list('teacher_id', flat=True).distinct()
            qs = qs.filter(teacher_id__in=teacher_ids)

        department_id = filters.get('department_id')
        if department_id:
            teacher_ids = DepartmentTeacher.objects.filter(
                department_id=department_id,
                department__school_id__in=school_ids,
            ).values_list('teacher_id', flat=True)
            qs = qs.filter(teacher_id__in=teacher_ids)

        status = filters.get('status') or 'all'
        if status == 'active':
            qs = qs.filter(is_active=True)
        elif status == 'inactive':
            qs = qs.filter(is_active=False)

        role = filters.get('role') or 'all'
        if role != 'all':
            qs = qs.filter(role=role)

        if filters.get('no_class'):
            qs = qs.filter(active_class_count=0)

        qs = qs.order_by('teacher__first_name', 'teacher__last_name')

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        teacher_ids_on_page = [st.teacher_id for st in page_obj]
        dept_map = {}
        for dt in DepartmentTeacher.objects.filter(
            teacher_id__in=teacher_ids_on_page,
            department__school_id__in=school_ids,
        ).select_related('department'):
            dept_map.setdefault(dt.teacher_id, []).append(dt.department.name)

        class_subject_map = {}
        for ct in ClassTeacher.objects.filter(
            teacher_id__in=teacher_ids_on_page,
            classroom__school_id__in=school_ids,
            classroom__is_active=True,
        ).select_related('classroom__subject'):
            subj = ct.classroom.subject
            if subj:
                class_subject_map.setdefault(ct.teacher_id, set()).add(subj.name)
        class_subject_map = {k: sorted(v) for k, v in class_subject_map.items()}

        for st in page_obj:
            st.departments_list = dept_map.get(st.teacher_id, [])
            st.subjects_list = class_subject_map.get(st.teacher_id, [])

        context = {
            'page_obj': page_obj,
            'form': form,
            'available_classes': available_classes,
            'available_departments': available_departments,
            'available_subjects': available_subjects,
            'total_count': paginator.count,
            'filters': filters,
            'is_hod_only': hod_only,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'reports/_partials/teacher_report_table.html', context)

        return render(request, 'reports/teachers.html', context)


# ===========================================================================
# Revenue Report (CPP-296)
# ===========================================================================

class RevenueReportFilterForm(forms.Form):
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    student_id = forms.IntegerField(required=False)
    class_id = forms.IntegerField(required=False)
    payment_method = forms.ChoiceField(
        choices=[
            ('all', 'All'),
            ('bank_transfer', 'Bank Transfer'),
            ('cash', 'Cash'),
            ('cheque', 'Cheque'),
            ('stripe', 'Stripe'),
            ('other', 'Other'),
        ],
        required=False,
        initial='all',
    )
    status = forms.ChoiceField(
        choices=[
            ('all', 'All'),
            ('draft', 'Draft'),
            ('issued', 'Issued'),
            ('partially_paid', 'Partially Paid'),
            ('paid', 'Paid'),
            ('cancelled', 'Cancelled'),
        ],
        required=False,
        initial='all',
    )


class RevenueReportView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        hod_only = _is_hod_only(request.user)
        dept_ids = _get_hod_dept_ids(request.user) if hod_only else []

        if hod_only:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids, department_id__in=dept_ids, is_active=True,
            ).order_by('name')
            dept_student_ids = ClassStudent.objects.filter(
                classroom__department_id__in=dept_ids,
                classroom__school_id__in=school_ids,
                is_active=True,
            ).values_list('student_id', flat=True).distinct()
            available_students = SchoolStudent.objects.filter(
                school_id__in=school_ids, is_active=True,
                student_id__in=dept_student_ids,
            ).select_related('student').order_by('student__first_name', 'student__last_name')
        else:
            available_classes = ClassRoom.objects.filter(
                school_id__in=school_ids, is_active=True,
            ).order_by('name')
            available_students = SchoolStudent.objects.filter(
                school_id__in=school_ids, is_active=True,
            ).select_related('student').order_by('student__first_name', 'student__last_name')

        form = RevenueReportFilterForm(request.GET or None)
        filters = {}
        if form.is_valid():
            filters = form.cleaned_data

        qs = Invoice.objects.filter(
            school_id__in=school_ids,
        ).select_related('student').annotate(
            manual_paid=Sum(
                'payments__amount',
                filter=Q(payments__status='confirmed'),
                default=Decimal('0.00'),
            ),
        )

        if hod_only and dept_ids:
            dept_invoice_ids = InvoiceLineItem.objects.filter(
                department_id__in=dept_ids,
                invoice__school_id__in=school_ids,
            ).values_list('invoice_id', flat=True).distinct()
            qs = qs.filter(id__in=dept_invoice_ids)
        elif hod_only and not dept_ids:
            qs = qs.none()

        date_from = filters.get('date_from')
        if date_from:
            qs = qs.filter(billing_period_start__gte=date_from)

        date_to = filters.get('date_to')
        if date_to:
            qs = qs.filter(billing_period_end__lte=date_to)

        student_id = filters.get('student_id')
        if student_id:
            qs = qs.filter(student_id=student_id)

        class_id = filters.get('class_id')
        if class_id:
            invoice_ids = InvoiceLineItem.objects.filter(
                classroom_id=class_id,
                invoice__school_id__in=school_ids,
            ).values_list('invoice_id', flat=True).distinct()
            qs = qs.filter(id__in=invoice_ids)

        payment_method = filters.get('payment_method') or 'all'
        if payment_method == 'stripe':
            candidate_ids = set(qs.values_list('id', flat=True))
            stripe_invoice_ids = self._get_stripe_invoice_ids(candidate_ids)
            qs = qs.filter(id__in=stripe_invoice_ids)
        elif payment_method != 'all':
            has_method_ids = InvoicePayment.objects.filter(
                invoice__school_id__in=school_ids,
                payment_method=payment_method,
                status='confirmed',
            ).values_list('invoice_id', flat=True).distinct()
            qs = qs.filter(id__in=has_method_ids)

        status = filters.get('status') or 'all'
        if status != 'all':
            qs = qs.filter(status=status)

        qs = qs.order_by('-billing_period_start', '-created_at')

        totals = qs.aggregate(
            total_invoiced=Sum('amount', default=Decimal('0.00')),
            total_manual_paid=Sum('manual_paid', default=Decimal('0.00')),
        )

        invoice_ids_all = list(qs.values_list('id', flat=True))
        stripe_paid_map = self._get_stripe_paid_map(invoice_ids_all)
        total_stripe_paid = sum(stripe_paid_map.values())

        total_invoiced = totals['total_invoiced']
        total_paid = totals['total_manual_paid'] + total_stripe_paid
        total_outstanding = total_invoiced - total_paid

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        page_invoice_ids = [inv.id for inv in page_obj]
        page_stripe_map = {iid: stripe_paid_map.get(iid, Decimal('0.00')) for iid in page_invoice_ids}

        class_map = {}
        for li in InvoiceLineItem.objects.filter(
            invoice_id__in=page_invoice_ids,
            classroom__isnull=False,
        ).select_related('classroom'):
            class_map.setdefault(li.invoice_id, set()).add(li.classroom.name)
        class_map = {k: sorted(v) for k, v in class_map.items()}

        payment_methods_map = {}
        for ip in InvoicePayment.objects.filter(
            invoice_id__in=page_invoice_ids,
            status='confirmed',
        ).values('invoice_id', 'payment_method').distinct():
            payment_methods_map.setdefault(ip['invoice_id'], set()).add(
                dict(InvoicePayment.PAYMENT_METHOD_CHOICES).get(ip['payment_method'], ip['payment_method'])
            )

        for iid in page_invoice_ids:
            if page_stripe_map.get(iid, Decimal('0.00')) > 0:
                payment_methods_map.setdefault(iid, set()).add('Stripe')
        payment_methods_map = {k: sorted(v) for k, v in payment_methods_map.items()}

        for inv in page_obj:
            stripe_amount = page_stripe_map.get(inv.id, Decimal('0.00'))
            inv.total_paid = inv.manual_paid + stripe_amount
            inv.total_due = inv.amount - inv.total_paid
            inv.classes_list = class_map.get(inv.id, [])
            inv.payment_methods_list = payment_methods_map.get(inv.id, [])

        context = {
            'page_obj': page_obj,
            'form': form,
            'available_classes': available_classes,
            'available_students': available_students,
            'total_count': paginator.count,
            'filters': filters,
            'is_hod_only': hod_only,
            'total_invoiced': total_invoiced,
            'total_paid': total_paid,
            'total_outstanding': total_outstanding,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'reports/_partials/revenue_report_table.html', context)

        return render(request, 'reports/revenue.html', context)

    @staticmethod
    def _get_stripe_paid_map(invoice_ids):
        from billing.models import InvoiceStripePayment
        stripe_map = {}
        if not invoice_ids:
            return stripe_map
        invoice_id_set = set(invoice_ids)
        for sp in InvoiceStripePayment.objects.filter(status='succeeded'):
            for alloc in sp.invoice_allocations:
                inv_id = alloc.get('invoice_id')
                if inv_id in invoice_id_set:
                    stripe_map[inv_id] = stripe_map.get(inv_id, Decimal('0.00')) + Decimal(str(alloc.get('amount', 0)))
        return stripe_map

    @staticmethod
    def _get_stripe_invoice_ids(candidate_ids):
        from billing.models import InvoiceStripePayment
        result = set()
        if not candidate_ids:
            return result
        for sp in InvoiceStripePayment.objects.filter(status='succeeded'):
            for alloc in sp.invoice_allocations:
                inv_id = alloc.get('invoice_id')
                if inv_id in candidate_ids:
                    result.add(inv_id)
        return result


# ---------------------------------------------------------------------------
# Expense Report
# ---------------------------------------------------------------------------

class ExpenseReportFilterForm(forms.Form):
    category = forms.ChoiceField(
        choices=[('all', 'All')] + Expense.CATEGORY_CHOICES,
        required=False,
        initial='all',
    )
    department_id = forms.IntegerField(required=False)
    date_from = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))
    date_to = forms.DateField(required=False, widget=forms.DateInput(attrs={'type': 'date'}))


class ExpenseReportView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        hod_only = _is_hod_only(request.user)
        dept_ids = _get_hod_dept_ids(request.user) if hod_only else []

        if hod_only:
            available_departments = Department.objects.filter(
                id__in=dept_ids, is_active=True,
            ).order_by('name')
        else:
            available_departments = Department.objects.filter(
                school_id__in=school_ids, is_active=True,
            ).order_by('name')

        form = ExpenseReportFilterForm(request.GET or None)
        filters = {}
        if form.is_valid():
            filters = form.cleaned_data

        qs = Expense.objects.filter(
            school_id__in=school_ids,
        ).select_related('department', 'created_by')

        if hod_only and dept_ids:
            qs = qs.filter(department_id__in=dept_ids)
        elif hod_only and not dept_ids:
            qs = qs.none()

        category = filters.get('category') or 'all'
        if category != 'all':
            qs = qs.filter(category=category)

        department_id = filters.get('department_id')
        if department_id:
            qs = qs.filter(department_id=department_id)

        date_from = filters.get('date_from')
        if date_from:
            qs = qs.filter(date__gte=date_from)

        date_to = filters.get('date_to')
        if date_to:
            qs = qs.filter(date__lte=date_to)

        total_amount = qs.aggregate(total=Sum('amount'))['total'] or 0

        paginator = Paginator(qs, PAGE_SIZE)
        page_obj = paginator.get_page(request.GET.get('page', 1))

        can_manage = (
            request.user.is_superuser
            or request.user.has_role(Role.INSTITUTE_OWNER)
            or request.user.has_role(Role.HEAD_OF_INSTITUTE)
        )

        context = {
            'page_obj': page_obj,
            'form': form,
            'available_departments': available_departments,
            'category_choices': Expense.CATEGORY_CHOICES,
            'total_count': paginator.count,
            'total_amount': total_amount,
            'filters': filters,
            'is_hod_only': hod_only,
            'can_manage': can_manage,
        }

        if request.headers.get('HX-Request'):
            return render(request, 'reports/_partials/expense_report_table.html', context)

        return render(request, 'reports/expenses.html', context)


# ---------------------------------------------------------------------------
# Expense CRUD
# ---------------------------------------------------------------------------

class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['category', 'description', 'amount', 'date', 'department']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.TextInput(attrs={'placeholder': 'e.g. Monthly rent payment'}),
            'amount': forms.NumberInput(attrs={'step': '0.01', 'min': '0.01'}),
        }

    def __init__(self, *args, school_ids=None, **kwargs):
        super().__init__(*args, **kwargs)
        if school_ids:
            self.fields['department'].queryset = Department.objects.filter(
                school_id__in=school_ids, is_active=True,
            ).order_by('name')
        self.fields['department'].required = False
        self.fields['department'].empty_label = 'No department'


class ExpenseCreateView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school_ids = _get_all_school_ids(request.user)
        form = ExpenseForm(school_ids=school_ids)
        return render(request, 'reports/expense_form.html', {'form': form, 'editing': False})

    def post(self, request):
        school_ids = _get_all_school_ids(request.user)
        form = ExpenseForm(request.POST, school_ids=school_ids)
        if form.is_valid():
            expense = form.save(commit=False)
            expense.school_id = school_ids[0]
            expense.created_by = request.user
            expense.save()
            return redirect('reports_expenses')
        return render(request, 'reports/expense_form.html', {'form': form, 'editing': False})


class ExpenseEditView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, pk):
        school_ids = _get_all_school_ids(request.user)
        expense = get_object_or_404(Expense, pk=pk, school_id__in=school_ids)
        form = ExpenseForm(instance=expense, school_ids=school_ids)
        return render(request, 'reports/expense_form.html', {'form': form, 'editing': True, 'expense': expense})

    def post(self, request, pk):
        school_ids = _get_all_school_ids(request.user)
        expense = get_object_or_404(Expense, pk=pk, school_id__in=school_ids)
        form = ExpenseForm(request.POST, instance=expense, school_ids=school_ids)
        if form.is_valid():
            form.save()
            return redirect('reports_expenses')
        return render(request, 'reports/expense_form.html', {'form': form, 'editing': True, 'expense': expense})


class ExpenseDeleteView(RoleRequiredMixin, View):
    required_roles = [Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, pk):
        school_ids = _get_all_school_ids(request.user)
        expense = get_object_or_404(Expense, pk=pk, school_id__in=school_ids)
        expense.delete()
        return redirect('reports_expenses')
