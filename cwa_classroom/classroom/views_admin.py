from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone

from django.core.paginator import Paginator
from django.db.models import Count, Q

from accounts.models import CustomUser, Role, UserRole
from accounts.views import _validate_username, _generate_username_suggestion
from .models import (
    School, SchoolTeacher, AcademicYear, ClassRoom, ClassSession, Department,
    DepartmentTeacher, SchoolStudent, Level, Subject, Term, ClassStudent,
    SchoolHoliday, PublicHoliday,
)
from .views import RoleRequiredMixin
from .email_utils import send_staff_welcome_email
from audit.services import log_event


def _get_user_school(user, school_id=None):
    """Get a school the user has access to (as admin or HoI via SchoolTeacher).

    If school_id is given, returns that specific school or None.
    If school_id is None, returns the user's first accessible school or None.
    """
    # Superusers can access any school
    if user.is_superuser:
        if school_id:
            return School.objects.filter(id=school_id).first()
        return School.objects.first()

    # Schools where user is admin
    admin_schools = School.objects.filter(admin=user, is_active=True)

    # Schools where user is HoI via SchoolTeacher
    hoi_school_ids = SchoolTeacher.objects.filter(
        teacher=user, role='head_of_institute', is_active=True,
    ).values_list('school_id', flat=True)
    hoi_schools = School.objects.filter(id__in=hoi_school_ids, is_active=True)

    all_schools = (admin_schools | hoi_schools).distinct()

    if school_id:
        return all_schools.filter(id=school_id).first()
    return all_schools.first()


def _get_user_schools(user):
    """Get all schools the user can manage."""
    if user.is_superuser:
        return School.objects.filter(is_active=True)

    admin_schools = School.objects.filter(admin=user, is_active=True)
    hoi_school_ids = SchoolTeacher.objects.filter(
        teacher=user, role='head_of_institute', is_active=True,
    ).values_list('school_id', flat=True)
    hoi_schools = School.objects.filter(id__in=hoi_school_ids, is_active=True)
    return (admin_schools | hoi_schools).distinct()


def _get_user_school_or_404(user, school_id):
    """Like get_object_or_404 but checks both admin and SchoolTeacher."""
    from django.http import Http404
    school = _get_user_school(user, school_id)
    if not school:
        raise Http404('No School matches the given query.')
    return school


class AdminDashboardView(RoleRequiredMixin, View):
    """Admin dashboard showing all schools belonging to the current admin/HoD/Institute Owner."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        schools = _get_user_schools(request.user).annotate(
            teacher_count=Count(
                'school_teachers',
                filter=Q(school_teachers__is_active=True),
                distinct=True,
            ),
            student_count=Count(
                'school_students',
                filter=Q(school_students__is_active=True),
                distinct=True,
            ),
        )
        school_data = [{
            'school': s,
            'teacher_count': s.teacher_count,
            'student_count': s.student_count,
        } for s in schools]
        total_teachers = sum(s.teacher_count for s in schools)
        total_students = sum(s.student_count for s in schools)
        return render(request, 'admin_dashboard/dashboard.html', {
            'school_data': school_data,
            'total_schools': len(school_data),
            'total_teachers': total_teachers,
            'total_students': total_students,
        })


class SchoolCreateView(RoleRequiredMixin, View):
    """Create a new school owned by the current admin/HoD."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        return render(request, 'admin_dashboard/school_form.html')

    def post(self, request):
        name = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()

        if not name:
            messages.error(request, 'School name is required.')
            return render(request, 'admin_dashboard/school_form.html', {
                'form_data': {
                    'name': name,
                    'address': address,
                    'phone': phone,
                    'email': email,
                },
            })

        slug = slugify(name)
        # Ensure unique slug
        base_slug = slug
        counter = 1
        while School.objects.filter(slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        school = School.objects.create(
            name=name,
            slug=slug,
            address=address,
            phone=phone,
            email=email,
            admin=request.user,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='school_created', detail={'school_name': name},
            request=request,
        )
        messages.success(request, f'School "{name}" created successfully.')
        return redirect('admin_school_detail', school_id=school.id)


class SchoolEditView(RoleRequiredMixin, View):
    """Edit an existing school's details."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_context(self, school, form_data):
        teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).select_related('teacher').order_by('role', 'teacher__first_name')
        return {
            'school': school,
            'form_data': form_data,
            'teachers': teachers,
            'current_hoi_id': school.admin_id,
        }

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        return render(request, 'admin_dashboard/school_form.html', self._get_context(school, {
            'name': school.name,
            'address': school.address,
            'phone': school.phone,
            'email': school.email,
        }))

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        name = request.POST.get('name', '').strip()
        address = request.POST.get('address', '').strip()
        phone = request.POST.get('phone', '').strip()
        email = request.POST.get('email', '').strip()

        if not name:
            messages.error(request, 'School name is required.')
            return render(request, 'admin_dashboard/school_form.html', self._get_context(
                school, {'name': name, 'address': address, 'phone': phone, 'email': email},
            ))

        if name != school.name:
            slug = slugify(name)
            base_slug = slug
            counter = 1
            while School.objects.filter(slug=slug).exclude(id=school.id).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            school.slug = slug

        school.name = name
        school.address = address
        school.phone = phone
        school.email = email

        # Handle HoI change
        new_hoi_id = request.POST.get('new_hoi', '')
        old_hoi_role = request.POST.get('old_hoi_role', 'teacher')
        hoi_changed = new_hoi_id and int(new_hoi_id) != school.admin_id
        old_admin_id = school.admin_id

        if hoi_changed:
            school.admin_id = int(new_hoi_id)

        school.save()
        # school.save() auto-promotes new admin to HoI via _ensure_admin_is_hoi

        if hoi_changed and old_admin_id:
            from accounts.models import UserRole

            if old_hoi_role == 'remove':
                # Remove old HoI from this school entirely
                SchoolTeacher.objects.filter(
                    school=school, teacher_id=old_admin_id,
                ).delete()
            else:
                # Demote old HoI to the chosen role
                SchoolTeacher.objects.filter(
                    school=school, teacher_id=old_admin_id,
                ).update(role=old_hoi_role)

            # Clean up HoI UserRole if not HoI at any other school
            still_hoi = SchoolTeacher.objects.filter(
                teacher_id=old_admin_id, role='head_of_institute',
            ).exists()
            if not still_hoi:
                hoi_role = Role.objects.filter(name=Role.HEAD_OF_INSTITUTE).first()
                if hoi_role:
                    UserRole.objects.filter(user_id=old_admin_id, role=hoi_role).delete()

            # If old HoI has no other schools, deactivate their account
            old_user = CustomUser.objects.filter(id=old_admin_id).first()
            if old_user:
                has_other_schools = (
                    SchoolTeacher.objects.filter(teacher_id=old_admin_id, is_active=True).exists()
                    or School.objects.filter(admin_id=old_admin_id, is_active=True).exists()
                )
                if not has_other_schools:
                    old_user.is_active = False
                    old_user.save(update_fields=['is_active'])

            # If the current user was the old HoI, log them out
            if request.user.id == old_admin_id:
                from django.contrib.auth import logout
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='school_edited', detail={'school_name': name, 'hoi_changed': True},
                    request=request,
                )
                logout(request)
                return redirect('login')

        log_event(
            user=request.user, school=school, category='data_change',
            action='school_edited', detail={'school_name': name, 'hoi_changed': hoi_changed},
            request=request,
        )
        messages.success(request, f'School "{name}" updated successfully.')
        return redirect('admin_school_detail', school_id=school.id)


class SchoolToggleActiveView(RoleRequiredMixin, View):
    """Toggle the is_active status of a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        return redirect('admin_school_detail', school_id=school_id)

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        school.is_active = not school.is_active
        school.save(update_fields=['is_active'])
        status = 'activated' if school.is_active else 'deactivated'
        log_event(
            user=request.user, school=school, category='data_change',
            action='school_toggled_active', detail={'school_name': school.name, 'is_active': school.is_active},
            request=request,
        )
        messages.success(request, f'School "{school.name}" has been {status}.')
        return redirect('admin_school_detail', school_id=school.id)


class SchoolDeleteView(RoleRequiredMixin, View):
    """Deactivate a school (soft-delete). Redirects to toggle-active for consistency."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        log_event(
            user=request.user, school=school, category='data_change',
            action='school_deleted', detail={'school_name': school.name},
            request=request,
        )
        # Redirect to toggle-active — we never hard-delete schools
        return redirect('admin_school_toggle_active', school_id=school_id)


class SchoolPublishView(RoleRequiredMixin, View):
    """Publish a school — sends notification emails to all students and teachers."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id):
        from .email_service import send_school_publish_notifications

        school = _get_user_school_or_404(request.user, school_id)

        if school.is_published:
            messages.info(request, f'"{school.name}" is already published.')
            return redirect('admin_school_detail', school_id=school.id)

        # Publish the school
        school.is_published = True
        school.published_at = timezone.now()
        school.save(update_fields=['is_published', 'published_at'])

        # Send notifications to all students and teachers
        result = send_school_publish_notifications(school)

        messages.success(
            request,
            f'School "{school.name}" has been published! '
            f'{result["sent"]} notification(s) sent.'
        )
        if result['failed']:
            messages.warning(
                request,
                f'{result["failed"]} notification(s) failed to send.'
            )

        return redirect('admin_school_detail', school_id=school.id)


class SchoolDetailView(RoleRequiredMixin, View):
    """Show detailed information about a school the admin/HoD owns."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        teachers = SchoolTeacher.objects.filter(school=school, is_active=True).select_related('teacher')
        classes = ClassRoom.objects.filter(school=school, is_active=True).prefetch_related(
            'teachers', 'students', 'levels'
        )
        academic_years = AcademicYear.objects.filter(school=school)
        departments = Department.objects.filter(school=school, is_active=True).select_related('head')
        school_students = SchoolStudent.objects.filter(school=school, is_active=True).select_related('student')
        custom_levels = Level.objects.filter(school=school).order_by('level_number')
        terms = Term.objects.filter(school=school).select_related('academic_year')
        holidays = SchoolHoliday.objects.filter(school=school).select_related('academic_year')
        return render(request, 'admin_dashboard/school_detail.html', {
            'school': school,
            'teachers': teachers,
            'classes': classes,
            'academic_years': academic_years,
            'departments': departments,
            'school_students': school_students,
            'student_count': school_students.count(),
            'custom_levels': custom_levels,
            'terms': terms,
            'holidays': holidays,
        })


class SchoolSettingsView(RoleRequiredMixin, View):
    """Manage institute settings: company details, banking, invoice config."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.ACCOUNTANT]

    SETTINGS_FIELDS = [
        # Company details
        'abn', 'gst_number', 'street_address', 'city', 'state_region',
        'postal_code', 'country',
        # Contact & email
        'outgoing_email',
        # Banking & invoice
        'bank_name', 'bank_bsb', 'bank_account_number', 'bank_account_name',
        'invoice_terms', 'invoice_due_days',
    ]

    def _build_form_data(self, school):
        data = {}
        for field in self.SETTINGS_FIELDS:
            data[field] = getattr(school, field, '')
        return data

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        tab = request.GET.get('tab', 'company')
        return render(request, 'admin_dashboard/school_settings.html', {
            'school': school,
            'form_data': self._build_form_data(school),
            'active_tab': tab,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        tab = request.POST.get('active_tab', 'company')

        # Save text fields
        for field in self.SETTINGS_FIELDS:
            if field == 'invoice_due_days':
                val = request.POST.get(field, '').strip()
                if val:
                    try:
                        setattr(school, field, int(val))
                    except ValueError:
                        pass
            else:
                setattr(school, field, request.POST.get(field, '').strip())

        # Validate outgoing_email if provided
        outgoing_email = request.POST.get('outgoing_email', '').strip()
        if outgoing_email:
            from django.core.validators import validate_email
            from django.core.exceptions import ValidationError as DjangoValidationError
            try:
                validate_email(outgoing_email)
            except DjangoValidationError:
                messages.error(request, 'Please enter a valid outgoing email address.')
                return redirect(f"{reverse('admin_school_settings', kwargs={'school_id': school.id})}?tab={tab}")

        # Handle logo upload
        if 'logo' in request.FILES:
            school.logo = request.FILES['logo']
        if request.POST.get('remove_logo') == '1':
            school.logo = ''

        school.save()
        log_event(
            user=request.user, school=school, category='data_change',
            action='school_settings_updated', detail={'tab': tab},
            request=request,
        )
        messages.success(request, 'Settings saved successfully.')
        return redirect(f"{reverse('admin_school_settings', kwargs={'school_id': school.id})}?tab={tab}")


class ManageSettingsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's settings page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.ACCOUNTANT]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_settings', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class ManageTeachersRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's teacher management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_teachers', school_id=school.id)
        messages.info(request, 'Create a school first before managing staff.')
        return redirect('admin_school_create')


class ManageStudentsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's student management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
                      Role.HEAD_OF_DEPARTMENT, Role.TEACHER]

    def get(self, request):
        school = _get_user_school(request.user)
        if not school:
            # HoD/teacher: find school via department or teaching assignment
            dept = Department.objects.filter(head=request.user, is_active=True).first()
            if dept:
                school = dept.school
            else:
                st = SchoolTeacher.objects.filter(teacher=request.user, is_active=True).first()
                if st:
                    school = st.school
        if school:
            return redirect('admin_school_students', school_id=school.id)
        messages.info(request, 'Create a school first before managing students.')
        return redirect('admin_school_create')


class ManageDepartmentsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's departments page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_departments', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class ManageSubjectsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's first department's subject-levels page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            dept = Department.objects.filter(school=school, is_active=True).first()
            if dept:
                return redirect('admin_department_subject_levels', school_id=school.id, dept_id=dept.id)
            return redirect('admin_school_departments', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class SchoolTeacherManageView(RoleRequiredMixin, View):
    """Manage teachers assigned to a school: list and create new teachers."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_role_choices(self, user):
        """Institute Owner / Admin can assign HoI; HoI cannot."""
        if user.is_institute_owner or user.is_admin_user:
            return SchoolTeacher.ROLE_CHOICES
        return [c for c in SchoolTeacher.ROLE_CHOICES if c[0] != 'head_of_institute']

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        show_inactive = request.GET.get('show_inactive') == '1'
        if show_inactive:
            qs = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        else:
            qs = SchoolTeacher.objects.filter(school=school, is_active=True).select_related('teacher')

        # Server-side search
        q = request.GET.get('q', '').strip()
        if q:
            from django.db.models import Q
            qs = qs.filter(
                Q(teacher__first_name__icontains=q)
                | Q(teacher__last_name__icontains=q)
                | Q(teacher__email__icontains=q)
                | Q(teacher__username__icontains=q)
            )

        # Server-side ordering
        order_by = request.GET.get('order_by', 'name')
        order_map = {
            'name': ('teacher__first_name', 'teacher__last_name'),
            '-name': ('-teacher__first_name', '-teacher__last_name'),
            'email': ('teacher__email',),
            '-email': ('-teacher__email',),
            'role': ('role',),
            '-role': ('-role',),
            'joined': ('joined_at',),
            '-joined': ('-joined_at',),
        }
        qs = qs.order_by(*order_map.get(order_by, ('teacher__first_name', 'teacher__last_name')))

        paginator = Paginator(qs, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'admin_dashboard/school_teachers.html', {
            'school': school,
            'school_teachers': page,
            'page': page,
            'role_choices': self._get_role_choices(request.user),
            'show_inactive': show_inactive,
            'q': q,
            'order_by': order_by,
            'total_count': paginator.count,
        })

    def post(self, request, school_id):
        """Create a new teacher account and assign to this school."""
        school = _get_user_school_or_404(request.user, school_id)

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        username = request.POST.get('username', '').strip()
        role = request.POST.get('role', 'teacher')
        specialty = request.POST.get('specialty', '').strip()

        # Validate
        errors = []
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email or '@' not in email:
            errors.append('A valid email address is required.')
        elif CustomUser.objects.filter(email=email).exists():
            errors.append('A user with this email already exists.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')

        # Username: use provided or auto-generate from email
        if username:
            errors.extend(_validate_username(username))
        elif email and '@' in email:
            username = _generate_username_suggestion(email)

        allowed_choices = self._get_role_choices(request.user)
        valid_roles = [choice[0] for choice in allowed_choices]
        if role not in valid_roles:
            role = 'teacher'

        if errors:
            for err in errors:
                messages.error(request, err)
            school_teachers = SchoolTeacher.objects.filter(school=school, is_active=True).select_related('teacher')
            paginator = Paginator(school_teachers, 25)
            page = paginator.get_page(request.GET.get('page'))
            return render(request, 'admin_dashboard/school_teachers.html', {
                'school': school,
                'school_teachers': page,
                'page': page,
                'role_choices': allowed_choices,
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'username': username,
                    'role': role,
                    'specialty': specialty,
                },
            })

        try:
            with transaction.atomic():
                # Create user account
                user = CustomUser.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                )
                user.must_change_password = True
                user.profile_completed = False
                user.save(update_fields=['must_change_password', 'profile_completed'])
                # Assign system-wide role based on school role
                if role == 'head_of_institute':
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'}
                    )
                elif role == 'head_of_department':
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.HEAD_OF_DEPARTMENT, defaults={'display_name': 'Head of Department'}
                    )
                elif role == 'accountant':
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.ACCOUNTANT, defaults={'display_name': 'Accountant'}
                    )
                else:
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.TEACHER, defaults={'display_name': 'Teacher'}
                    )
                UserRole.objects.create(user=user, role=system_role)

                # Assign additional roles (multi-role support)
                additional_roles = request.POST.getlist('additional_roles')
                for extra_role_name in additional_roles:
                    if extra_role_name == 'accountant' and role != 'accountant':
                        extra_role, _ = Role.objects.get_or_create(
                            name=Role.ACCOUNTANT, defaults={'display_name': 'Accountant'}
                        )
                        UserRole.objects.get_or_create(user=user, role=extra_role)
                # Link to school with chosen seniority role
                SchoolTeacher.objects.create(
                    school=school, teacher=user, role=role,
                    specialty=specialty,
                )

            log_event(
                user=request.user, school=school, category='data_change',
                action='teacher_added', detail={
                    'teacher_username': username, 'teacher_name': f'{first_name} {last_name}',
                    'role': role,
                },
                request=request,
            )
            messages.success(
                request,
                f'{first_name} {last_name} added as {dict(SchoolTeacher.ROLE_CHOICES).get(role, role)}. Login username: {username}'
            )
            # Send welcome email with login credentials
            send_staff_welcome_email(
                user=user,
                plain_password=password,
                role_display=dict(SchoolTeacher.ROLE_CHOICES).get(role, role),
                school=school,
            )
        except Exception as e:
            messages.error(request, f'Error creating staff member: {e}')

        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherEditView(RoleRequiredMixin, View):
    """Edit a teacher's details and role within a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = _get_user_school_or_404(request.user, school_id)
        school_teacher = get_object_or_404(
            SchoolTeacher, school=school, teacher_id=teacher_id
        )
        teacher = school_teacher.teacher
        new_role = request.POST.get('role', 'teacher')
        specialty = request.POST.get('specialty', '').strip()
        username = request.POST.get('username', '').strip()
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()

        valid_roles = [choice[0] for choice in SchoolTeacher.ROLE_CHOICES]
        if new_role not in valid_roles:
            messages.error(request, 'Invalid role selected.')
            return redirect('admin_school_teachers', school_id=school.id)

        # Update username if changed
        if username and username != teacher.username:
            errors = _validate_username(username, exclude_user_id=teacher.id)
            if errors:
                for err in errors:
                    messages.error(request, err)
                return redirect('admin_school_teachers', school_id=school.id)
            teacher.username = username

        if first_name:
            teacher.first_name = first_name
        if last_name:
            teacher.last_name = last_name
        if email and '@' in email:
            if not CustomUser.objects.filter(email=email).exclude(id=teacher.id).exists():
                teacher.email = email
        teacher.save()

        school_teacher.role = new_role
        school_teacher.specialty = specialty
        school_teacher.save()
        log_event(
            user=request.user, school=school, category='data_change',
            action='teacher_edited', detail={
                'teacher_id': teacher_id, 'teacher_name': teacher.get_full_name(),
                'role': new_role,
            },
            request=request,
        )
        messages.success(
            request,
            f'{teacher.get_full_name()} updated.'
        )
        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherBatchUpdateView(RoleRequiredMixin, View):
    """Batch update multiple teachers in one POST."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        teacher_ids_str = request.POST.get('teacher_ids', '')
        if not teacher_ids_str:
            return redirect('admin_school_teachers', school_id=school.id)

        teacher_ids = [int(x) for x in teacher_ids_str.split(',') if x.strip().isdigit()]
        valid_roles = [c[0] for c in SchoolTeacher.ROLE_CHOICES]
        updated = 0
        errors = []

        with transaction.atomic():
            for tid in teacher_ids:
                st = SchoolTeacher.objects.filter(
                    school=school, teacher_id=tid, is_active=True
                ).select_related('teacher').first()
                if not st:
                    continue

                teacher = st.teacher
                name = teacher.get_full_name() or teacher.username
                username = request.POST.get(f'username_{tid}', '').strip()
                first_name = request.POST.get(f'first_name_{tid}', '').strip()
                last_name = request.POST.get(f'last_name_{tid}', '').strip()
                email = request.POST.get(f'email_{tid}', '').strip()
                role = request.POST.get(f'role_{tid}', '').strip()
                specialty = request.POST.get(f'specialty_{tid}', '').strip()

                # Validate username
                if username and username != teacher.username:
                    uname_errors = _validate_username(username, exclude_user_id=teacher.id)
                    if uname_errors:
                        errors.append(f'{name}: {uname_errors[0]}')
                        continue
                    teacher.username = username

                if first_name:
                    teacher.first_name = first_name
                if last_name:
                    teacher.last_name = last_name
                if email and '@' in email:
                    if not CustomUser.objects.filter(email=email).exclude(id=teacher.id).exists():
                        teacher.email = email
                    else:
                        errors.append(f'{name}: email already in use.')
                        continue
                teacher.save()

                if role in valid_roles:
                    old_role = st.role
                    st.role = role
                    # Update system role if role changed
                    if role != old_role:
                        if role == 'accountant':
                            new_sys_role, _ = Role.objects.get_or_create(
                                name=Role.ACCOUNTANT, defaults={'display_name': 'Accountant'}
                            )
                            UserRole.objects.get_or_create(user=teacher, role=new_sys_role)
                        elif role in ('head_of_institute', 'head_of_department'):
                            role_name = Role.HEAD_OF_INSTITUTE if role == 'head_of_institute' else Role.HEAD_OF_DEPARTMENT
                            new_sys_role, _ = Role.objects.get_or_create(
                                name=role_name, defaults={'display_name': dict(SchoolTeacher.ROLE_CHOICES).get(role)}
                            )
                            UserRole.objects.get_or_create(user=teacher, role=new_sys_role)
                st.specialty = specialty
                st.save()
                updated += 1

        if updated:
            log_event(
                user=request.user, school=school, category='data_change',
                action='teacher_batch_updated', detail={
                    'teacher_ids': teacher_ids, 'updated_count': updated,
                },
                request=request,
            )
            messages.success(request, f'{updated} staff member{"s" if updated != 1 else ""} updated.')
        for err in errors:
            messages.error(request, err)
        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherRemoveView(RoleRequiredMixin, View):
    """Soft-remove a teacher from a school (deactivate, preserve account)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = _get_user_school_or_404(request.user, school_id)
        school_teacher = SchoolTeacher.objects.filter(
            school=school, teacher_id=teacher_id, is_active=True
        ).select_related('teacher').first()

        if school_teacher:
            teacher_user = school_teacher.teacher
            teacher_name = teacher_user.get_full_name() or teacher_user.username
            with transaction.atomic():
                # Deactivate the SchoolTeacher link (keep user account intact)
                school_teacher.is_active = False
                school_teacher.save(update_fields=['is_active'])
                # Remove from department assignments
                DepartmentTeacher.objects.filter(
                    department__school=school, teacher=teacher_user
                ).delete()
                # Remove from class assignments
                from .models import ClassTeacher
                ClassTeacher.objects.filter(
                    classroom__school=school, teacher=teacher_user
                ).delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='teacher_removed', detail={
                    'teacher_id': teacher_id, 'teacher_name': teacher_name,
                },
                request=request,
            )
            messages.success(request, f'{teacher_name} has been removed from {school.name}.')
        else:
            messages.warning(request, 'Teacher was not found at this school.')
        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherRestoreView(RoleRequiredMixin, View):
    """Restore a soft-removed teacher (reactivate SchoolTeacher link)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = _get_user_school_or_404(request.user, school_id)
        school_teacher = SchoolTeacher.objects.filter(
            school=school, teacher_id=teacher_id, is_active=False
        ).select_related('teacher').first()

        if school_teacher:
            teacher_user = school_teacher.teacher
            teacher_name = teacher_user.get_full_name() or teacher_user.username
            school_teacher.is_active = True
            school_teacher.save(update_fields=['is_active'])
            log_event(
                user=request.user, school=school, category='data_change',
                action='teacher_restored', detail={
                    'teacher_id': teacher_id, 'teacher_name': teacher_name,
                },
                request=request,
            )
            messages.success(request, f'{teacher_name} has been restored to {school.name}.')
        else:
            messages.warning(request, 'Inactive teacher was not found at this school.')
        return redirect('admin_school_teachers', school_id=school.id)


def _save_inline_terms(request, school, academic_year, number_of_terms, replace=False):
    """Read term_start_N / term_end_N from POST and create/replace Term objects.
    Returns the number of terms successfully saved. Skips slots with missing dates."""
    if not number_of_terms:
        return 0
    if replace:
        Term.objects.filter(academic_year=academic_year).delete()
    count = 0
    for i in range(1, number_of_terms + 1):
        start = request.POST.get(f'term_start_{i}', '').strip()
        end = request.POST.get(f'term_end_{i}', '').strip()
        if start and end:
            Term.objects.create(
                school=school,
                academic_year=academic_year,
                name=f'Term {i}',
                start_date=start,
                end_date=end,
                order=i,
            )
            count += 1
    return count


def _auto_create_sessions_for_school(school, created_by=None):
    """Auto-create ClassSession records for active classrooms in the school.

    Generates sessions for the next 7 days (today inclusive) for every active
    classroom that has a scheduled day, start_time and end_time.  A weekly
    class always falls within this window exactly once; a M/W/F class gets 3;
    a daily class gets 7.  Already-existing sessions are silently skipped.

    Returns the total number of new sessions created.
    """
    from datetime import date as _date, timedelta

    _DAY_MAP = {
        'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
        'friday': 4, 'saturday': 5, 'sunday': 6,
    }

    today = _date.today()
    window_end = today + timedelta(days=6)   # 7 days inclusive

    classrooms = (
        ClassRoom.objects
        .filter(school=school, is_active=True)
        .exclude(day='')
        .exclude(start_time__isnull=True)
        .exclude(end_time__isnull=True)
    )

    # Batch-fetch existing sessions in the window to avoid N queries
    existing_keys = set(
        ClassSession.objects
        .filter(classroom__in=classrooms, date__range=(today, window_end))
        .values_list('classroom_id', 'date')
    )

    to_create = []
    for classroom in classrooms:
        target_wd = _DAY_MAP.get(classroom.day)
        if target_wd is None:
            continue
        # First occurrence of this weekday on or after today
        days_ahead = (target_wd - today.weekday()) % 7
        session_date = today + timedelta(days=days_ahead)
        # Walk every 7 days through the window
        while session_date <= window_end:
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

    ClassSession.objects.bulk_create(to_create, ignore_conflicts=True)
    return len(to_create)


class AcademicYearCreateView(RoleRequiredMixin, View):
    """Create a new academic year for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        return render(request, 'admin_dashboard/academic_year_form.html', {
            'school': school,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        year = request.POST.get('year', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        is_current = request.POST.get('is_current') == '1'
        number_of_terms_raw = request.POST.get('number_of_terms', '').strip()

        form_data = {
            'year': year,
            'start_date': start_date,
            'end_date': end_date,
            'is_current': is_current,
            'number_of_terms': number_of_terms_raw,
        }

        if not year or not start_date or not end_date:
            messages.error(request, 'Year, start date, and end date are all required.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': form_data,
            })

        try:
            year = int(year)
        except (ValueError, TypeError):
            messages.error(request, 'Year must be a valid number.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': form_data,
            })

        number_of_terms = None
        if number_of_terms_raw:
            try:
                number_of_terms = int(number_of_terms_raw)
                if not (1 <= number_of_terms <= 6):
                    raise ValueError
            except (ValueError, TypeError):
                messages.error(request, 'Number of terms must be between 1 and 6.')
                return render(request, 'admin_dashboard/academic_year_form.html', {
                    'school': school,
                    'form_data': form_data,
                })

        if AcademicYear.objects.filter(school=school, year=year).exists():
            messages.error(request, f'Academic year {year} already exists for this school.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': form_data,
            })

        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            with transaction.atomic():
                academic_year = AcademicYear.objects.create(
                    school=school,
                    year=year,
                    start_date=start_date,
                    end_date=end_date,
                    is_current=is_current,
                    number_of_terms=number_of_terms,
                )
                # Create inline term dates if provided
                terms_created = _save_inline_terms(request, school, academic_year, number_of_terms)
        except (DjangoValidationError, ValueError) as e:
            messages.error(request, f'Invalid date value — please check all dates are in the correct format. ({e})')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': form_data,
            })

        # Auto-create upcoming sessions for the next 7 days so classes are
        # immediately visible without teachers having to add sessions manually.
        sessions_created = _auto_create_sessions_for_school(school, created_by=request.user)

        log_event(
            user=request.user, school=school, category='data_change',
            action='academic_year_created',
            detail={'year': year, 'academic_year_id': academic_year.id,
                    'number_of_terms': number_of_terms, 'terms_created': terms_created,
                    'sessions_auto_created': sessions_created},
            request=request,
        )
        if sessions_created:
            messages.success(
                request,
                f'Academic year {year} created successfully. '
                f'{sessions_created} upcoming session{"s" if sessions_created != 1 else ""} '
                f'auto-generated for the next 7 days.',
            )
        else:
            messages.success(request, f'Academic year {year} created successfully.')
        return redirect('admin_school_detail', school_id=school.id)


class AcademicYearEditView(RoleRequiredMixin, View):
    """Edit an existing academic year for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_academic_year(self, request, school_id, academic_year_id):
        school = _get_user_school_or_404(request.user, school_id)
        academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)
        return school, academic_year

    def get(self, request, school_id, academic_year_id):
        school, academic_year = self._get_academic_year(request, school_id, academic_year_id)
        terms = Term.objects.filter(academic_year=academic_year).order_by('order')
        return render(request, 'admin_dashboard/academic_year_form.html', {
            'school': school,
            'academic_year': academic_year,
            'terms': terms,
            'form_data': {
                'year': academic_year.year,
                'start_date': academic_year.start_date.isoformat() if academic_year.start_date else '',
                'end_date': academic_year.end_date.isoformat() if academic_year.end_date else '',
                'is_current': academic_year.is_current,
                'number_of_terms': academic_year.number_of_terms or '',
            },
        })

    def post(self, request, school_id, academic_year_id):
        school, academic_year = self._get_academic_year(request, school_id, academic_year_id)
        year = request.POST.get('year', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        is_current = request.POST.get('is_current') == '1'
        number_of_terms_raw = request.POST.get('number_of_terms', '').strip()

        form_data = {
            'year': year, 'start_date': start_date, 'end_date': end_date,
            'is_current': is_current, 'number_of_terms': number_of_terms_raw,
        }

        if not year or not start_date or not end_date:
            messages.error(request, 'Year, start date, and end date are all required.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school, 'academic_year': academic_year, 'form_data': form_data,
                'terms': Term.objects.filter(academic_year=academic_year).order_by('order'),
            })

        try:
            year = int(year)
        except (ValueError, TypeError):
            messages.error(request, 'Year must be a valid number.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school, 'academic_year': academic_year, 'form_data': form_data,
                'terms': Term.objects.filter(academic_year=academic_year).order_by('order'),
            })

        number_of_terms = None
        if number_of_terms_raw:
            try:
                number_of_terms = int(number_of_terms_raw)
                if not (1 <= number_of_terms <= 6):
                    raise ValueError
            except (ValueError, TypeError):
                messages.error(request, 'Number of terms must be between 1 and 6.')
                return render(request, 'admin_dashboard/academic_year_form.html', {
                    'school': school, 'academic_year': academic_year, 'form_data': form_data,
                    'terms': Term.objects.filter(academic_year=academic_year).order_by('order'),
                })

        # Check duplicate, excluding self
        if AcademicYear.objects.filter(school=school, year=year).exclude(id=academic_year.id).exists():
            messages.error(request, f'Academic year {year} already exists for this school.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school, 'academic_year': academic_year, 'form_data': form_data,
                'terms': Term.objects.filter(academic_year=academic_year).order_by('order'),
            })

        from django.core.exceptions import ValidationError as DjangoValidationError
        try:
            with transaction.atomic():
                academic_year.year = year
                academic_year.start_date = start_date
                academic_year.end_date = end_date
                academic_year.is_current = is_current
                academic_year.number_of_terms = number_of_terms
                academic_year.save()
                # Replace inline term dates if any were submitted
                terms_updated = _save_inline_terms(request, school, academic_year, number_of_terms, replace=True)
        except (DjangoValidationError, ValueError) as e:
            messages.error(request, f'Invalid date value — please check all dates are in the correct format. ({e})')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school, 'academic_year': academic_year, 'form_data': form_data,
                'terms': Term.objects.filter(academic_year=academic_year).order_by('order'),
            })

        log_event(
            user=request.user, school=school, category='data_change',
            action='academic_year_updated',
            detail={'year': year, 'academic_year_id': academic_year.id, 'is_current': is_current,
                    'number_of_terms': number_of_terms, 'terms_updated': terms_updated},
            request=request,
        )
        # Sync scheduled sessions with updated term/year dates
        from . import invoicing_services as svc
        created, deleted = svc.sync_sessions_for_school(school, created_by=request.user)
        if created or deleted:
            parts = []
            if created:
                parts.append(f'{created} session(s) created')
            if deleted:
                parts.append(f'{deleted} orphaned session(s) removed')
            messages.info(request, f'Sessions synced: {", ".join(parts)}.')

        messages.success(request, f'Academic year {year} updated successfully.')
        return redirect('admin_school_detail', school_id=school.id)


class AcademicYearCalendarView(RoleRequiredMixin, View):
    """Full-year calendar for an academic year showing terms and holidays."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, academic_year_id):
        import calendar as cal_module
        from datetime import date, timedelta

        school = _get_user_school_or_404(request.user, school_id)
        academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)

        today = timezone.localdate()

        # Fetch all terms overlapping this academic year's date range
        terms = Term.objects.filter(
            school=school,
            start_date__lte=academic_year.end_date,
            end_date__gte=academic_year.start_date,
        ).order_by('order', 'start_date')

        # Fetch school holidays overlapping this academic year's date range
        school_holidays = SchoolHoliday.objects.filter(
            school=school,
            start_date__lte=academic_year.end_date,
            end_date__gte=academic_year.start_date,
        )

        # Fetch public holidays in this academic year's date range
        public_holidays = PublicHoliday.objects.filter(
            school=school,
            date__gte=academic_year.start_date,
            date__lte=academic_year.end_date,
        )

        # Build day-lookup dictionaries
        term_days = {}  # date -> (term_name, term_order)
        for term in terms:
            d = term.start_date
            while d <= term.end_date:
                term_days[d] = (term.name, term.order)
                d += timedelta(days=1)

        school_holiday_days = {}  # date -> holiday name
        for h in school_holidays:
            d = h.start_date
            while d <= h.end_date:
                school_holiday_days[d] = h.name
                d += timedelta(days=1)

        public_holiday_days = {}  # date -> holiday name
        for h in public_holidays:
            public_holiday_days[h.date] = h.name

        # Build month list spanning the academic year
        start = academic_year.start_date
        end = academic_year.end_date
        months = []
        cur = date(start.year, start.month, 1)
        end_month_start = date(end.year, end.month, 1)

        while cur <= end_month_start:
            # monthcalendar returns weeks [Mon..Sun], 0 = not in this month
            raw_weeks = cal_module.monthcalendar(cur.year, cur.month)
            weeks = []
            for week in raw_weeks:
                days = []
                for day_num in week:
                    if day_num == 0:
                        days.append(None)
                    else:
                        d = date(cur.year, cur.month, day_num)
                        term_info = term_days.get(d)
                        days.append({
                            'date': d,
                            'day': day_num,
                            'weekday': d.weekday(),  # 0=Mon, 6=Sun
                            'is_today': d == today,
                            'in_range': start <= d <= end,
                            'in_term': term_info is not None,
                            'term_name': term_info[0] if term_info else None,
                            'term_order': term_info[1] if term_info else None,
                            'is_school_holiday': d in school_holiday_days,
                            'school_holiday_name': school_holiday_days.get(d),
                            'is_public_holiday': d in public_holiday_days,
                            'public_holiday_name': public_holiday_days.get(d),
                        })
                weeks.append(days)

            months.append({
                'year': cur.year,
                'month': cur.month,
                'name': cur.strftime('%B %Y'),
                'weeks': weeks,
            })

            # Advance to next month
            if cur.month == 12:
                cur = date(cur.year + 1, 1, 1)
            else:
                cur = date(cur.year, cur.month + 1, 1)

        # Term colour palette (cycle through 4 distinct shades)
        term_colours = ['blue', 'emerald', 'violet', 'sky', 'teal', 'indigo']
        term_colour_map = {}
        for i, term in enumerate(terms):
            term_colour_map[term.name] = term_colours[i % len(term_colours)]

        return render(request, 'admin_dashboard/academic_year_calendar.html', {
            'school': school,
            'academic_year': academic_year,
            'terms': terms,
            'months': months,
            'today': today,
            'term_colour_map': term_colour_map,
            'school_holidays': school_holidays,
            'public_holidays': public_holidays,
        })


class AcademicYearTermSetupView(RoleRequiredMixin, View):
    """Set start/end dates for each auto-generated term slot in an academic year."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_objects(self, request, school_id, academic_year_id):
        school = _get_user_school_or_404(request.user, school_id)
        academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)
        return school, academic_year

    def get(self, request, school_id, academic_year_id):
        school, academic_year = self._get_objects(request, school_id, academic_year_id)
        n = academic_year.number_of_terms or 0
        existing_terms = {
            t.order: t for t in Term.objects.filter(academic_year=academic_year).order_by('order')
        }
        term_slots = []
        for i in range(1, n + 1):
            t = existing_terms.get(i)
            term_slots.append({
                'order': i,
                'label': f'Term {i}',
                'start_date': t.start_date.isoformat() if t else '',
                'end_date': t.end_date.isoformat() if t else '',
            })
        return render(request, 'admin_dashboard/term_setup.html', {
            'school': school,
            'academic_year': academic_year,
            'term_slots': term_slots,
        })

    def post(self, request, school_id, academic_year_id):
        school, academic_year = self._get_objects(request, school_id, academic_year_id)
        n = academic_year.number_of_terms or 0
        errors = []
        term_data = []
        for i in range(1, n + 1):
            start = request.POST.get(f'start_date_{i}', '').strip()
            end = request.POST.get(f'end_date_{i}', '').strip()
            if not start or not end:
                errors.append(f'Term {i}: start and end dates are required.')
            else:
                term_data.append({'order': i, 'start': start, 'end': end})

        if errors:
            for e in errors:
                messages.error(request, e)
            term_slots = [
                {
                    'order': i,
                    'label': f'Term {i}',
                    'start_date': request.POST.get(f'start_date_{i}', ''),
                    'end_date': request.POST.get(f'end_date_{i}', ''),
                }
                for i in range(1, n + 1)
            ]
            return render(request, 'admin_dashboard/term_setup.html', {
                'school': school,
                'academic_year': academic_year,
                'term_slots': term_slots,
            })

        with transaction.atomic():
            # Remove existing terms for this academic year, then recreate
            Term.objects.filter(academic_year=academic_year).delete()
            for td in term_data:
                Term.objects.create(
                    school=school,
                    academic_year=academic_year,
                    name=f'Term {td["order"]}',
                    start_date=td['start'],
                    end_date=td['end'],
                    order=td['order'],
                )

        log_event(
            user=request.user, school=school, category='data_change',
            action='terms_setup',
            detail={'academic_year_id': academic_year.id, 'term_count': len(term_data)},
            request=request,
        )
        messages.success(request, f'{len(term_data)} term(s) saved for {academic_year.year}.')
        return redirect('admin_school_detail', school_id=school.id)


class SchoolHolidayManageView(RoleRequiredMixin, View):
    """CRUD for school holidays (e.g. half-term, inset days)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        holidays = SchoolHoliday.objects.filter(school=school).select_related('academic_year', 'term')
        academic_years = AcademicYear.objects.filter(school=school).order_by('-year')
        terms = Term.objects.filter(school=school).select_related('academic_year').order_by('academic_year__year', 'order')
        return render(request, 'admin_dashboard/school_holidays.html', {
            'school': school,
            'holidays': holidays,
            'academic_years': academic_years,
            'terms': terms,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        action = request.POST.get('action', 'create')

        if action == 'delete':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(SchoolHoliday, id=holiday_id, school=school)
            holiday.delete()
            log_event(user=request.user, school=school, category='data_change',
                      action='school_holiday_deleted', detail={'holiday_id': holiday_id}, request=request)
            messages.success(request, 'Holiday deleted.')
            return redirect('admin_school_holidays', school_id=school.id)

        # create or edit
        name = request.POST.get('name', '').strip()
        start_date = request.POST.get('start_date', '').strip()
        end_date = request.POST.get('end_date', '').strip()
        academic_year_id = request.POST.get('academic_year') or None
        term_id = request.POST.get('term') or None

        if not name or not start_date or not end_date:
            messages.error(request, 'Name, start date, and end date are required.')
            return redirect('admin_school_holidays', school_id=school.id)

        academic_year = None
        if academic_year_id:
            academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)
        term = None
        if term_id:
            term = get_object_or_404(Term, id=term_id, school=school)

        if action == 'edit':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(SchoolHoliday, id=holiday_id, school=school)
            holiday.name = name
            holiday.start_date = start_date
            holiday.end_date = end_date
            holiday.academic_year = academic_year
            holiday.term = term
            holiday.save()
            log_event(user=request.user, school=school, category='data_change',
                      action='school_holiday_updated', detail={'holiday_id': holiday.id, 'name': name}, request=request)
            messages.success(request, f'Holiday "{name}" updated.')
        else:
            holiday = SchoolHoliday.objects.create(
                school=school, name=name, start_date=start_date, end_date=end_date,
                academic_year=academic_year, term=term,
            )
            log_event(user=request.user, school=school, category='data_change',
                      action='school_holiday_created', detail={'holiday_id': holiday.id, 'name': name}, request=request)
            messages.success(request, f'Holiday "{name}" added.')

        return redirect('admin_school_holidays', school_id=school.id)


class PublicHolidayManageView(RoleRequiredMixin, View):
    """CRUD for public/national holidays."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        holidays = PublicHoliday.objects.filter(school=school).select_related('academic_year')
        academic_years = AcademicYear.objects.filter(school=school).order_by('-year')
        return render(request, 'admin_dashboard/public_holidays.html', {
            'school': school,
            'holidays': holidays,
            'academic_years': academic_years,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        action = request.POST.get('action', 'create')

        if action == 'delete':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(PublicHoliday, id=holiday_id, school=school)
            holiday.delete()
            log_event(user=request.user, school=school, category='data_change',
                      action='public_holiday_deleted', detail={'holiday_id': holiday_id}, request=request)
            messages.success(request, 'Public holiday deleted.')
            return redirect('admin_public_holidays', school_id=school.id)

        name = request.POST.get('name', '').strip()
        date = request.POST.get('date', '').strip()
        academic_year_id = request.POST.get('academic_year') or None

        if not name or not date:
            messages.error(request, 'Name and date are required.')
            return redirect('admin_public_holidays', school_id=school.id)

        academic_year = None
        if academic_year_id:
            academic_year = get_object_or_404(AcademicYear, id=academic_year_id, school=school)

        if action == 'edit':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(PublicHoliday, id=holiday_id, school=school)
            holiday.name = name
            holiday.date = date
            holiday.academic_year = academic_year
            holiday.save()
            log_event(user=request.user, school=school, category='data_change',
                      action='public_holiday_updated', detail={'holiday_id': holiday.id, 'name': name}, request=request)
            messages.success(request, f'Public holiday "{name}" updated.')
        else:
            holiday = PublicHoliday.objects.create(
                school=school, name=name, date=date, academic_year=academic_year,
            )
            log_event(user=request.user, school=school, category='data_change',
                      action='public_holiday_created', detail={'holiday_id': holiday.id, 'name': name}, request=request)
            messages.success(request, f'Public holiday "{name}" added.')

        return redirect('admin_public_holidays', school_id=school.id)


# ── Student CRUD ──────────────────────────────────────────────────────────────

class SchoolStudentManageView(RoleRequiredMixin, View):
    """Manage students assigned to a school: list and create new students."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def _get_school(self, request, school_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER) or user.has_role(Role.ADMIN):
            return get_object_or_404(School, id=school_id, admin=user)
        if user.has_role(Role.HEAD_OF_DEPARTMENT):
            school = get_object_or_404(School, id=school_id)
            if Department.objects.filter(school=school, head=user).exists():
                return school
        if user.has_role(Role.TEACHER):
            school = get_object_or_404(School, id=school_id)
            if SchoolTeacher.objects.filter(school=school, teacher=user).exists():
                return school
        from django.http import Http404
        raise Http404

    def get(self, request, school_id):
        school = self._get_school(request, school_id)
        from django.db.models import Count, Q
        show_inactive = request.GET.get('show_inactive') == '1'
        qs = SchoolStudent.objects.filter(school=school)
        if not show_inactive:
            qs = qs.filter(is_active=True)
        qs = (
            qs.select_related('student')
            .prefetch_related(
                'student__student_guardians__guardian',
                'student__student_parent_links__parent',
            )
            .annotate(
                class_count=Count(
                    'student__class_student_entries',
                    filter=Q(student__class_student_entries__classroom__school=school),
                )
            )
        )

        # Server-side search
        q = request.GET.get('q', '').strip()
        if q:
            qs = qs.filter(
                Q(student__first_name__icontains=q)
                | Q(student__last_name__icontains=q)
                | Q(student__email__icontains=q)
                | Q(student__username__icontains=q)
            )

        # Server-side ordering
        order_by = request.GET.get('order_by', 'name')
        order_map = {
            'name': ('student__first_name', 'student__last_name'),
            '-name': ('-student__first_name', '-student__last_name'),
            'email': ('student__email',),
            '-email': ('-student__email',),
            'joined': ('joined_at',),
            '-joined': ('-joined_at',),
            'classes': ('class_count',),
            '-classes': ('-class_count',),
        }
        qs = qs.order_by(*order_map.get(order_by, ('student__first_name', 'student__last_name')))

        paginator = Paginator(qs, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'admin_dashboard/school_students.html', {
            'school': school,
            'school_students': page,
            'page': page,
            'show_inactive': show_inactive,
            'q': q,
            'order_by': order_by,
            'total_count': paginator.count,
        })

    def post(self, request, school_id):
        school = self._get_school(request, school_id)

        # Check student limit before adding
        from billing.entitlements import check_student_limit
        allowed, current, limit = check_student_limit(school)
        if not allowed:
            messages.error(
                request,
                f'Your plan allows {limit} students. '
                f'You currently have {current}. Please upgrade your plan.',
            )
            return redirect('admin_school_students', school_id=school.id)

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
        username = request.POST.get('username', '').strip()

        errors = []
        if not first_name:
            errors.append('First name is required.')
        if not last_name:
            errors.append('Last name is required.')
        if not email or '@' not in email:
            errors.append('A valid email address is required.')
        elif CustomUser.objects.filter(email=email).exists():
            errors.append('A user with this email already exists.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')

        # Username: use provided or auto-generate from email
        if username:
            errors.extend(_validate_username(username))
        elif email and '@' in email:
            username = _generate_username_suggestion(email)

        if errors:
            for err in errors:
                messages.error(request, err)
            school_students = SchoolStudent.objects.filter(school=school, is_active=True).select_related('student')
            return render(request, 'admin_dashboard/school_students.html', {
                'school': school,
                'school_students': school_students,
                'class_counts': {},
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'username': username,
                },
            })

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    username=username, email=email, password=password,
                    first_name=first_name, last_name=last_name,
                )
                user.must_change_password = True
                user.profile_completed = False
                user.save(update_fields=['must_change_password', 'profile_completed'])
                student_role, _ = Role.objects.get_or_create(
                    name=Role.STUDENT, defaults={'display_name': 'Student'}
                )
                UserRole.objects.create(user=user, role=student_role, assigned_by=request.user)
                SchoolStudent.objects.create(school=school, student=user)

            log_event(
                user=request.user, school=school, category='data_change',
                action='student_added', detail={
                    'student_username': username, 'student_name': f'{first_name} {last_name}',
                },
                request=request,
            )
            # Send welcome email with login credentials
            from classroom.email_utils import send_staff_welcome_email
            send_staff_welcome_email(
                user=user,
                plain_password=password,
                role_display='Student',
                school=school,
            )
            messages.success(request, f'{first_name} {last_name} added as student. Login username: {username}')
        except Exception as e:
            messages.error(request, f'Error creating student: {e}')

        return redirect('admin_school_students', school_id=school.id)


class SchoolStudentEditView(RoleRequiredMixin, View):
    """Edit a student's details."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def post(self, request, school_id, student_id):
        school = SchoolStudentManageView._get_school(self, request, school_id)
        school_student = get_object_or_404(
            SchoolStudent, school=school, student_id=student_id
        )
        student = school_student.student
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        username = request.POST.get('username', '').strip()

        # Update username if changed
        if username and username != student.username:
            errors = _validate_username(username, exclude_user_id=student.id)
            if errors:
                for err in errors:
                    messages.error(request, err)
                return redirect('admin_school_students', school_id=school.id)
            student.username = username

        if first_name:
            student.first_name = first_name
        if last_name:
            student.last_name = last_name
        if email and '@' in email:
            if not CustomUser.objects.filter(email=email).exclude(id=student.id).exists():
                student.email = email
        student.save()
        log_event(
            user=request.user, school=school, category='data_change',
            action='student_edited', detail={
                'student_id': student_id, 'student_name': student.get_full_name(),
            },
            request=request,
        )
        messages.success(request, f'{student.get_full_name()} updated.')
        return redirect('admin_school_students', school_id=school.id)


class SchoolStudentBatchUpdateView(RoleRequiredMixin, View):
    """Batch update multiple students in one POST."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def post(self, request, school_id):
        school = SchoolStudentManageView._get_school(self, request, school_id)
        student_ids_str = request.POST.get('student_ids', '')
        if not student_ids_str:
            return redirect('admin_school_students', school_id=school.id)

        student_ids = [int(x) for x in student_ids_str.split(',') if x.strip().isdigit()]
        updated = 0
        errors = []

        with transaction.atomic():
            for sid in student_ids:
                ss = SchoolStudent.objects.filter(
                    school=school, student_id=sid, is_active=True
                ).select_related('student').first()
                if not ss:
                    continue

                student = ss.student
                name = student.get_full_name() or student.username
                username = request.POST.get(f'username_{sid}', '').strip()
                first_name = request.POST.get(f'first_name_{sid}', '').strip()
                last_name = request.POST.get(f'last_name_{sid}', '').strip()
                email = request.POST.get(f'email_{sid}', '').strip()

                if username and username != student.username:
                    uname_errors = _validate_username(username, exclude_user_id=student.id)
                    if uname_errors:
                        errors.append(f'{name}: {uname_errors[0]}')
                        continue
                    student.username = username

                if first_name:
                    student.first_name = first_name
                if last_name:
                    student.last_name = last_name
                if email and '@' in email:
                    if not CustomUser.objects.filter(email=email).exclude(id=student.id).exists():
                        student.email = email
                    else:
                        errors.append(f'{name}: email already in use.')
                        continue
                student.save()
                updated += 1

        if updated:
            log_event(
                user=request.user, school=school, category='data_change',
                action='student_batch_updated', detail={
                    'student_ids': student_ids, 'updated_count': updated,
                },
                request=request,
            )
            messages.success(request, f'{updated} student{"s" if updated != 1 else ""} updated.')
        for err in errors:
            messages.error(request, err)
        return redirect('admin_school_students', school_id=school.id)


class SchoolStudentRemoveView(RoleRequiredMixin, View):
    """Soft-remove a student from a school (deactivate, preserve account and history)."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def post(self, request, school_id, student_id):
        school = SchoolStudentManageView._get_school(self, request, school_id)
        school_student = SchoolStudent.objects.filter(
            school=school, student_id=student_id, is_active=True
        ).select_related('student').first()

        if school_student:
            student_user = school_student.student
            name = student_user.get_full_name() or student_user.username
            with transaction.atomic():
                # Deactivate the SchoolStudent link
                school_student.is_active = False
                school_student.save(update_fields=['is_active'])
                # Cascade: deactivate all ClassStudent entries at this school
                ClassStudent.objects.filter(
                    classroom__school=school, student=student_user, is_active=True
                ).update(is_active=False)
            log_event(
                user=request.user, school=school, category='data_change',
                action='student_removed', detail={
                    'student_id': student_id, 'student_name': name,
                },
                request=request,
            )
            messages.success(request, f'{name} has been removed from {school.name}.')
        else:
            messages.warning(request, 'Student was not found at this school.')
        return redirect('admin_school_students', school_id=school.id)


class SchoolStudentRestoreView(RoleRequiredMixin, View):
    """Restore a soft-removed student (reactivate SchoolStudent link and ClassStudent entries)."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def post(self, request, school_id, student_id):
        school = SchoolStudentManageView._get_school(self, request, school_id)
        school_student = SchoolStudent.objects.filter(
            school=school, student_id=student_id, is_active=False
        ).select_related('student').first()

        if school_student:
            student_user = school_student.student
            name = student_user.get_full_name() or student_user.username
            with transaction.atomic():
                school_student.is_active = True
                school_student.save(update_fields=['is_active'])
                # Restore ClassStudent entries at this school
                ClassStudent.objects.filter(
                    classroom__school=school, student=student_user, is_active=False
                ).update(is_active=True)
            log_event(
                user=request.user, school=school, category='data_change',
                action='student_restored', detail={
                    'student_id': student_id, 'student_name': name,
                },
                request=request,
            )
            messages.success(request, f'{name} has been restored to {school.name}.')
        else:
            messages.warning(request, 'Inactive student was not found at this school.')
        return redirect('admin_school_students', school_id=school.id)


# ── Custom Level CRUD ─────────────────────────────────────────────────────────

class SchoolLevelManageView(RoleRequiredMixin, View):
    """Manage custom levels for a school."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
    ]

    def _get_school(self, request, school_id):
        user = request.user
        if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER) or user.has_role(Role.ADMIN):
            return get_object_or_404(School, id=school_id, admin=user)
        if user.has_role(Role.HEAD_OF_DEPARTMENT):
            school = get_object_or_404(School, id=school_id)
            if Department.objects.filter(school=school, head=user).exists():
                return school
        from django.http import Http404
        raise Http404

    def get(self, request, school_id):
        school = self._get_school(request, school_id)
        custom_levels = Level.objects.filter(school=school).order_by('level_number')
        return render(request, 'admin_dashboard/school_levels.html', {
            'school': school,
            'custom_levels': custom_levels,
        })

    def post(self, request, school_id):
        school = self._get_school(request, school_id)
        display_name = request.POST.get('display_name', '').strip()
        description = request.POST.get('description', '').strip()

        if not display_name:
            messages.error(request, 'Level name is required.')
            return redirect('admin_school_levels', school_id=school.id)

        # Auto-generate next level_number starting from 200
        from django.db.models import Max
        max_num = Level.objects.filter(level_number__gte=200).aggregate(
            m=Max('level_number')
        )['m']
        next_num = (max_num or 199) + 1

        level = Level.objects.create(
            level_number=next_num,
            display_name=display_name,
            description=description,
            school=school,
        )
        log_event(
            user=request.user, school=school, category='data_change',
            action='level_created', detail={
                'level_id': level.id, 'display_name': display_name,
            },
            request=request,
        )
        messages.success(request, f'Level "{display_name}" created.')
        return redirect('admin_school_levels', school_id=school.id)


class SchoolLevelEditView(RoleRequiredMixin, View):
    """Edit a custom level's display name / description."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
    ]

    def post(self, request, school_id, level_id):
        school = SchoolLevelManageView._get_school(self, request, school_id)
        level = get_object_or_404(Level, id=level_id, school=school)

        display_name = request.POST.get('display_name', '').strip()
        description = request.POST.get('description', '').strip()
        if display_name:
            level.display_name = display_name
        level.description = description
        level.save()
        log_event(
            user=request.user, school=school, category='data_change',
            action='level_edited', detail={
                'level_id': level_id, 'display_name': level.display_name,
            },
            request=request,
        )
        messages.success(request, f'Level "{level.display_name}" updated.')
        return redirect('admin_school_levels', school_id=school.id)


class SchoolLevelRemoveView(RoleRequiredMixin, View):
    """Delete a custom level."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT,
    ]

    def post(self, request, school_id, level_id):
        school = SchoolLevelManageView._get_school(self, request, school_id)
        level = Level.objects.filter(id=level_id, school=school).first()

        if level:
            name = level.display_name
            level.delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='level_removed', detail={
                    'level_id': level_id, 'display_name': name,
                },
                request=request,
            )
            messages.success(request, f'Level "{name}" deleted.')
        else:
            messages.warning(request, 'Level not found.')
        return redirect('admin_school_levels', school_id=school.id)


class SchoolSubjectManageView(RoleRequiredMixin, View):
    """Manage subjects for a school: list global + school-created, create/edit/delete."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        show_inactive = request.GET.get('show_inactive') == '1'
        global_subjects = Subject.objects.filter(school__isnull=True, is_active=True).order_by('order', 'name')
        if show_inactive:
            school_subjects = Subject.objects.filter(school=school).order_by('order', 'name')
        else:
            school_subjects = Subject.objects.filter(school=school, is_active=True).order_by('order', 'name')
        archived_count = Subject.objects.filter(school=school, is_active=False).count()
        # Global SubjectApps for linking
        from classroom.models import SubjectApp
        subject_apps = SubjectApp.objects.filter(is_active=True).order_by('order', 'name')
        return render(request, 'admin_dashboard/school_subjects.html', {
            'school': school,
            'global_subjects': global_subjects,
            'school_subjects': school_subjects,
            'subject_apps': subject_apps,
            'show_inactive': show_inactive,
            'archived_count': archived_count,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        action = request.POST.get('action', 'create')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            if not name:
                messages.error(request, 'Subject name is required.')
                return redirect('admin_school_subjects', school_id=school.id)
            slug = slugify(name)
            base_slug = slug
            cnt = 1
            while Subject.objects.filter(school=school, slug=slug).exists():
                slug = f'{base_slug}-{cnt}'
                cnt += 1
            global_subject_id = request.POST.get('global_subject_id', '').strip()
            global_subject = None
            if global_subject_id:
                global_subject = Subject.objects.filter(id=global_subject_id, school__isnull=True).first()
            subject = Subject.objects.create(
                name=name, slug=slug, school=school, is_active=True,
                global_subject=global_subject,
            )
            log_event(
                user=request.user, school=school, category='data_change',
                action='subject_created', detail={
                    'subject_id': subject.id, 'subject_name': name,
                },
                request=request,
            )
            messages.success(request, f'Subject "{name}" created.')

        elif action == 'edit':
            subject_id = request.POST.get('subject_id')
            name = request.POST.get('name', '').strip()
            subject = Subject.objects.filter(id=subject_id, school=school).first()
            if subject and name:
                subject.name = name
                subject.slug = slugify(name)
                # Update global subject link
                global_subject_id = request.POST.get('global_subject_id', '').strip()
                if global_subject_id:
                    subject.global_subject = Subject.objects.filter(
                        id=global_subject_id, school__isnull=True,
                    ).first()
                else:
                    subject.global_subject = None
                subject.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='subject_edited', detail={
                        'subject_id': subject_id, 'subject_name': name,
                    },
                    request=request,
                )
                messages.success(request, f'Subject updated to "{name}".')

        elif action == 'delete':
            subject_id = request.POST.get('subject_id')
            subject = Subject.objects.filter(id=subject_id, school=school).first()
            if subject:
                name = subject.name
                subject.is_active = False
                subject.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='subject_archived', detail={
                        'subject_id': subject_id, 'subject_name': name,
                    },
                    request=request,
                )
                messages.success(request, f'Subject "{name}" archived.')

        elif action == 'restore':
            subject_id = request.POST.get('subject_id')
            subject = Subject.objects.filter(id=subject_id, school=school, is_active=False).first()
            if subject:
                subject.is_active = True
                subject.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='subject_restored', detail={
                        'subject_id': subject_id, 'subject_name': subject.name,
                    },
                    request=request,
                )
                messages.success(request, f'Subject "{subject.name}" restored.')

        return redirect('admin_school_subjects', school_id=school.id)


# ---------------------------------------------------------------------------
# Account Blocking & School Suspension (Admin only)
# ---------------------------------------------------------------------------

def _invalidate_user_sessions(user):
    """Delete all database sessions belonging to a specific user."""
    from django.contrib.sessions.models import Session
    from django.utils import timezone as tz
    for session in Session.objects.filter(expire_date__gte=tz.now()):
        data = session.get_decoded()
        if str(data.get('_auth_user_id')) == str(user.pk):
            session.delete()


class BlockUserView(RoleRequiredMixin, View):
    """Block a user account. Admin/HoI only."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request):
        user_id = request.POST.get('user_id')
        reason = request.POST.get('reason', '').strip()
        block_type = request.POST.get('block_type', 'permanent')
        expires_at = request.POST.get('expires_at', '').strip()

        user = get_object_or_404(CustomUser, id=user_id)

        # Don't allow blocking yourself or other admins
        if user == request.user:
            messages.error(request, 'You cannot block your own account.')
            return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))
        if user.is_admin_user and not request.user.is_admin_user:
            messages.error(request, 'Only system admins can block other admins.')
            return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))

        user.is_blocked = True
        user.blocked_at = timezone.now()
        user.blocked_reason = reason
        user.blocked_by = request.user
        user.block_type = block_type
        if block_type == 'temporary' and expires_at:
            from django.utils.dateparse import parse_datetime
            user.block_expires_at = parse_datetime(expires_at)
        else:
            user.block_expires_at = None
        user.save(update_fields=[
            'is_blocked', 'blocked_at', 'blocked_reason',
            'blocked_by', 'block_type', 'block_expires_at',
        ])

        # Force logout all sessions
        _invalidate_user_sessions(user)

        log_event(
            user=request.user, category='admin_action', action='user_blocked',
            detail={'target_user': user.username, 'reason': reason, 'block_type': block_type},
            request=request,
        )

        messages.success(request, f'Account "{user.username}" has been blocked.')
        return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))


class UnblockUserView(RoleRequiredMixin, View):
    """Unblock a user account. Admin/HoI only."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request):
        user_id = request.POST.get('user_id')
        user = get_object_or_404(CustomUser, id=user_id)

        user.is_blocked = False
        user.block_type = ''
        user.save(update_fields=['is_blocked', 'block_type'])

        log_event(
            user=request.user, category='admin_action',
            action='user_unblocked', detail={'target_user': user.username},
            request=request,
        )
        messages.success(request, f'Account "{user.username}" has been unblocked.')
        return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))


class SuspendSchoolView(RoleRequiredMixin, View):
    """Suspend a school. System admin only."""
    required_roles = [Role.ADMIN]

    def post(self, request):
        school_id = request.POST.get('school_id')
        reason = request.POST.get('reason', '').strip()
        school = get_object_or_404(School, id=school_id)

        school.is_suspended = True
        school.suspended_at = timezone.now()
        school.suspended_reason = reason
        school.suspended_by = request.user
        school.save(update_fields=[
            'is_suspended', 'suspended_at', 'suspended_reason', 'suspended_by',
        ])

        # Set subscription status to suspended
        from billing.entitlements import get_school_subscription
        from billing.models import SchoolSubscription
        sub = get_school_subscription(school)
        if sub:
            sub.status = SchoolSubscription.STATUS_SUSPENDED
            sub.save(update_fields=['status', 'updated_at'])

        # Force logout all users in this school
        from .models import SchoolTeacher as ST, SchoolStudent as SS
        user_ids = set()
        user_ids.update(
            ST.objects.filter(school=school, is_active=True)
            .values_list('teacher_id', flat=True)
        )
        user_ids.update(
            SS.objects.filter(school=school, is_active=True)
            .values_list('student_id', flat=True)
        )
        if school.admin_id:
            user_ids.add(school.admin_id)

        for uid in user_ids:
            try:
                u = CustomUser.objects.get(id=uid)
                _invalidate_user_sessions(u)
            except CustomUser.DoesNotExist:
                pass

        log_event(
            user=request.user, school=school, category='admin_action',
            action='school_suspended', detail={'school_name': school.name, 'reason': reason},
            request=request,
        )
        messages.success(request, f'School "{school.name}" has been suspended.')
        return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))


class UnsuspendSchoolView(RoleRequiredMixin, View):
    """Unsuspend a school. System admin only."""
    required_roles = [Role.ADMIN]

    def post(self, request):
        school_id = request.POST.get('school_id')
        school = get_object_or_404(School, id=school_id)

        school.is_suspended = False
        school.save(update_fields=['is_suspended'])

        # Restore subscription to active
        from billing.entitlements import get_school_subscription
        from billing.models import SchoolSubscription
        sub = get_school_subscription(school)
        if sub and sub.status == SchoolSubscription.STATUS_SUSPENDED:
            sub.status = SchoolSubscription.STATUS_ACTIVE
            sub.save(update_fields=['status', 'updated_at'])

        log_event(
            user=request.user, school=school, category='admin_action',
            action='school_unsuspended', detail={'school_name': school.name},
            request=request,
        )
        messages.success(request, f'School "{school.name}" has been unsuspended.')
        return redirect(request.META.get('HTTP_REFERER', 'subjects_hub'))


class ManageTermsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's terms page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_terms', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class ManageHolidaysRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's holidays page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = _get_user_school(request.user)
        if school:
            return redirect('admin_school_holidays', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class ManageParentInvitesRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's parent invites page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
                      Role.HEAD_OF_DEPARTMENT]

    def get(self, request):
        school = _get_user_school(request.user)
        if not school:
            from .models import Department
            dept = Department.objects.filter(head=request.user, is_active=True).first()
            if dept:
                school = dept.school
        if school:
            return redirect('parent_invite_list', school_id=school.id)
        messages.info(request, 'Create a school first.')
        return redirect('admin_school_create')


class TermManageView(RoleRequiredMixin, View):
    """Manage terms for a school: list, create, edit, delete."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        terms = Term.objects.filter(school=school).select_related('academic_year')
        academic_years = AcademicYear.objects.filter(school=school)
        return render(request, 'admin_dashboard/school_terms.html', {
            'school': school,
            'terms': terms,
            'academic_years': academic_years,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            academic_year_id = request.POST.get('academic_year') or None
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            order = request.POST.get('order', 0)

            if not name or not start_date or not end_date:
                messages.error(request, 'Name, start date and end date are required.')
                return redirect('admin_school_terms', school_id=school.id)

            academic_year = None
            if academic_year_id:
                academic_year = AcademicYear.objects.filter(
                    id=academic_year_id, school=school
                ).first()

            try:
                term = Term.objects.create(
                    school=school,
                    academic_year=academic_year,
                    name=name,
                    start_date=start_date,
                    end_date=end_date,
                    order=int(order) if order else 0,
                )
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='term_created', detail={'term_id': term.id, 'term_name': name},
                    request=request,
                )
                messages.success(request, f'Term "{name}" created.')
            except Exception as e:
                messages.error(request, f'Could not create term: {e}')

        elif action == 'edit':
            term_id = request.POST.get('term_id')
            term = get_object_or_404(Term, id=term_id, school=school)
            term.name = request.POST.get('name', '').strip() or term.name
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            if start_date:
                term.start_date = start_date
            if end_date:
                term.end_date = end_date
            academic_year_id = request.POST.get('academic_year')
            if academic_year_id:
                term.academic_year = AcademicYear.objects.filter(
                    id=academic_year_id, school=school
                ).first()
            else:
                term.academic_year = None
            order = request.POST.get('order')
            if order is not None and order != '':
                term.order = int(order)
            try:
                term.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='term_edited', detail={'term_id': term_id, 'term_name': term.name},
                    request=request,
                )
                messages.success(request, f'Term "{term.name}" updated.')
            except Exception as e:
                messages.error(request, f'Could not update term: {e}')

        elif action == 'confirm':
            term_id = request.POST.get('term_id')
            term = get_object_or_404(Term, id=term_id, school=school)
            from datetime import date, timedelta
            one_month_from_now = date.today() + timedelta(days=30)
            if term.start_date <= one_month_from_now:
                messages.warning(
                    request,
                    f'Term "{term.name}" starts on {term.start_date.strftime("%d %b %Y")}. '
                    f'Dates must be confirmed at least 1 month before the term starts.'
                )
            else:
                term.is_confirmed = True
                term.confirmed_at = timezone.now()
                term.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='term_confirmed',
                    detail={'term_id': term.id, 'term_name': term.name},
                    request=request,
                )
                messages.success(request, f'Term "{term.name}" confirmed.')

        elif action == 'delete':
            term_id = request.POST.get('term_id')
            term = get_object_or_404(Term, id=term_id, school=school)
            term_name = term.name
            term.delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='term_deleted', detail={'term_id': term_id, 'term_name': term_name},
                request=request,
            )
            messages.success(request, f'Term "{term_name}" deleted.')

        # Sync scheduled sessions with updated term dates
        from . import invoicing_services as svc
        created, deleted = svc.sync_sessions_for_school(school, created_by=request.user)
        if created or deleted:
            parts = []
            if created:
                parts.append(f'{created} session(s) created')
            if deleted:
                parts.append(f'{deleted} orphaned session(s) removed')
            messages.info(request, f'Sessions synced: {", ".join(parts)}.')

        return redirect('admin_school_terms', school_id=school.id)


class HolidayManageView(RoleRequiredMixin, View):
    """Manage holidays for a school: list, create, edit, delete."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        holidays = SchoolHoliday.objects.filter(school=school).select_related('academic_year')
        academic_years = AcademicYear.objects.filter(school=school)
        return render(request, 'admin_dashboard/school_holidays.html', {
            'school': school,
            'holidays': holidays,
            'academic_years': academic_years,
        })

    def post(self, request, school_id):
        school = _get_user_school_or_404(request.user, school_id)
        action = request.POST.get('action')

        if action == 'create':
            name = request.POST.get('name', '').strip()
            academic_year_id = request.POST.get('academic_year') or None
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')

            if not name or not start_date or not end_date:
                messages.error(request, 'Name, start date and end date are required.')
                return redirect('admin_school_holidays', school_id=school.id)

            academic_year = None
            if academic_year_id:
                academic_year = AcademicYear.objects.filter(
                    id=academic_year_id, school=school
                ).first()

            try:
                holiday = SchoolHoliday.objects.create(
                    school=school,
                    academic_year=academic_year,
                    name=name,
                    start_date=start_date,
                    end_date=end_date,
                )
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='holiday_created',
                    detail={'holiday_id': holiday.id, 'holiday_name': name},
                    request=request,
                )
                messages.success(request, f'Holiday "{name}" created.')
            except Exception as e:
                messages.error(request, f'Could not create holiday: {e}')

        elif action == 'edit':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(SchoolHoliday, id=holiday_id, school=school)
            holiday.name = request.POST.get('name', '').strip() or holiday.name
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            if start_date:
                holiday.start_date = start_date
            if end_date:
                holiday.end_date = end_date
            academic_year_id = request.POST.get('academic_year')
            if academic_year_id:
                holiday.academic_year = AcademicYear.objects.filter(
                    id=academic_year_id, school=school
                ).first()
            else:
                holiday.academic_year = None
            try:
                holiday.save()
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='holiday_edited',
                    detail={'holiday_id': holiday_id, 'holiday_name': holiday.name},
                    request=request,
                )
                messages.success(request, f'Holiday "{holiday.name}" updated.')
            except Exception as e:
                messages.error(request, f'Could not update holiday: {e}')

        elif action == 'delete':
            holiday_id = request.POST.get('holiday_id')
            holiday = get_object_or_404(SchoolHoliday, id=holiday_id, school=school)
            holiday_name = holiday.name
            holiday.delete()
            log_event(
                user=request.user, school=school, category='data_change',
                action='holiday_deleted',
                detail={'holiday_id': holiday_id, 'holiday_name': holiday_name},
                request=request,
            )
            messages.success(request, f'Holiday "{holiday_name}" deleted.')

        return redirect('admin_school_holidays', school_id=school.id)
