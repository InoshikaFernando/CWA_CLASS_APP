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
)
from .views import RoleRequiredMixin
from .email_utils import send_staff_welcome_email


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
                logout(request)
                return redirect('login')

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
        messages.success(request, f'School "{school.name}" has been {status}.')
        return redirect('admin_school_detail', school_id=school.id)


class SchoolDeleteView(RoleRequiredMixin, View):
    """Deactivate a school (soft-delete). Redirects to toggle-active for consistency."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id):
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
        return render(request, 'admin_dashboard/school_detail.html', {
            'school': school,
            'teachers': teachers,
            'classes': classes,
            'academic_years': academic_years,
            'departments': departments,
            'school_students': school_students,
            'student_count': school_students.count(),
            'custom_levels': custom_levels,
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

        # Handle logo upload
        if 'logo' in request.FILES:
            school.logo = request.FILES['logo']
        if request.POST.get('remove_logo') == '1':
            school.logo = ''

        school.save()
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
            school_teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        else:
            school_teachers = SchoolTeacher.objects.filter(school=school, is_active=True).select_related('teacher')
        paginator = Paginator(school_teachers, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'admin_dashboard/school_teachers.html', {
            'school': school,
            'school_teachers': page,
            'page': page,
            'role_choices': self._get_role_choices(request.user),
            'show_inactive': show_inactive,
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
            messages.success(request, f'{teacher_name} has been restored to {school.name}.')
        else:
            messages.warning(request, 'Inactive teacher was not found at this school.')
        return redirect('admin_school_teachers', school_id=school.id)


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

        if not year or not start_date or not end_date:
            messages.error(request, 'Year, start date, and end date are all required.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': {
                    'year': year,
                    'start_date': start_date,
                    'end_date': end_date,
                },
            })

        try:
            year = int(year)
        except (ValueError, TypeError):
            messages.error(request, 'Year must be a valid number.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': {
                    'year': year,
                    'start_date': start_date,
                    'end_date': end_date,
                },
            })

        if AcademicYear.objects.filter(school=school, year=year).exists():
            messages.error(request, f'Academic year {year} already exists for this school.')
            return render(request, 'admin_dashboard/academic_year_form.html', {
                'school': school,
                'form_data': {
                    'year': year,
                    'start_date': start_date,
                    'end_date': end_date,
                },
            })

        AcademicYear.objects.create(
            school=school,
            year=year,
            start_date=start_date,
            end_date=end_date,
        )
        messages.success(request, f'Academic year {year} created successfully.')
        return redirect('admin_school_detail', school_id=school.id)


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
        school_students = (
            qs.select_related('student')
            .annotate(
                class_count=Count(
                    'student__class_student_entries',
                    filter=Q(student__class_student_entries__classroom__school=school),
                )
            )
        )
        paginator = Paginator(school_students, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'admin_dashboard/school_students.html', {
            'school': school,
            'school_students': page,
            'page': page,
            'show_inactive': show_inactive,
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

        Level.objects.create(
            level_number=next_num,
            display_name=display_name,
            description=description,
            school=school,
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
            Subject.objects.create(
                name=name, slug=slug, school=school, is_active=True,
                global_subject=global_subject,
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
                messages.success(request, f'Subject updated to "{name}".')

        elif action == 'delete':
            subject_id = request.POST.get('subject_id')
            subject = Subject.objects.filter(id=subject_id, school=school).first()
            if subject:
                name = subject.name
                subject.is_active = False
                subject.save()
                messages.success(request, f'Subject "{name}" archived.')

        elif action == 'restore':
            subject_id = request.POST.get('subject_id')
            subject = Subject.objects.filter(id=subject_id, school=school, is_active=False).first()
            if subject:
                subject.is_active = True
                subject.save()
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

        from audit.services import log_event
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
                Term.objects.create(
                    school=school,
                    academic_year=academic_year,
                    name=name,
                    start_date=start_date,
                    end_date=end_date,
                    order=int(order) if order else 0,
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
                messages.success(request, f'Term "{term.name}" updated.')
            except Exception as e:
                messages.error(request, f'Could not update term: {e}')

        elif action == 'delete':
            term_id = request.POST.get('term_id')
            term = get_object_or_404(Term, id=term_id, school=school)
            term_name = term.name
            term.delete()
            messages.success(request, f'Term "{term_name}" deleted.')

        return redirect('admin_school_terms', school_id=school.id)
