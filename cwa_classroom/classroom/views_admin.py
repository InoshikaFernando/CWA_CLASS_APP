from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from .models import School, SchoolTeacher, AcademicYear, ClassRoom, ClassSession, Department
from .views import RoleRequiredMixin


class AdminDashboardView(RoleRequiredMixin, View):
    """Admin dashboard showing all schools belonging to the current admin/HoD/Institute Owner."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        schools = School.objects.filter(admin=request.user)
        school_data = []
        for school in schools:
            teacher_count = SchoolTeacher.objects.filter(school=school, is_active=True).count()
            student_count = ClassRoom.objects.filter(
                school=school, is_active=True
            ).values_list('students', flat=True).distinct().count()
            school_data.append({
                'school': school,
                'teacher_count': teacher_count,
                'student_count': student_count,
            })
        return render(request, 'admin_dashboard/dashboard.html', {
            'school_data': school_data,
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


class SchoolDetailView(RoleRequiredMixin, View):
    """Show detailed information about a school the admin/HoD owns."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        classes = ClassRoom.objects.filter(school=school, is_active=True).prefetch_related(
            'teachers', 'students', 'levels'
        )
        academic_years = AcademicYear.objects.filter(school=school)
        departments = Department.objects.filter(school=school).select_related('head')
        return render(request, 'admin_dashboard/school_detail.html', {
            'school': school,
            'teachers': teachers,
            'classes': classes,
            'academic_years': academic_years,
            'departments': departments,
        })


class ManageTeachersRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's teacher management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if school:
            return redirect('admin_school_teachers', school_id=school.id)
        messages.info(request, 'Create a school first before managing teachers.')
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
        school = get_object_or_404(School, id=school_id, admin=request.user)
        school_teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        return render(request, 'admin_dashboard/school_teachers.html', {
            'school': school,
            'school_teachers': school_teachers,
            'role_choices': self._get_role_choices(request.user),
        })

    def post(self, request, school_id):
        """Create a new teacher account and assign to this school."""
        school = get_object_or_404(School, id=school_id, admin=request.user)

        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip()
        password = request.POST.get('password', '').strip()
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

        allowed_choices = self._get_role_choices(request.user)
        valid_roles = [choice[0] for choice in allowed_choices]
        if role not in valid_roles:
            role = 'teacher'

        if errors:
            for err in errors:
                messages.error(request, err)
            school_teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
            return render(request, 'admin_dashboard/school_teachers.html', {
                'school': school,
                'school_teachers': school_teachers,
                'role_choices': allowed_choices,
                'form_data': {
                    'first_name': first_name,
                    'last_name': last_name,
                    'email': email,
                    'role': role,
                    'specialty': specialty,
                },
            })

        # Generate username from email (part before @), ensure unique
        base_username = email.split('@')[0].lower().replace(' ', '.')
        username = base_username
        counter = 1
        while CustomUser.objects.filter(username=username).exists():
            username = f'{base_username}{counter}'
            counter += 1

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
                # Assign system-wide role based on school role
                if role == 'head_of_institute':
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.HEAD_OF_INSTITUTE, defaults={'display_name': 'Head of Institute'}
                    )
                elif role == 'head_of_department':
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.HEAD_OF_DEPARTMENT, defaults={'display_name': 'Head of Department'}
                    )
                else:
                    system_role, _ = Role.objects.get_or_create(
                        name=Role.TEACHER, defaults={'display_name': 'Teacher'}
                    )
                UserRole.objects.create(user=user, role=system_role)
                # Link to school with chosen seniority role
                SchoolTeacher.objects.create(
                    school=school, teacher=user, role=role,
                    specialty=specialty,
                )

            messages.success(
                request,
                f'{first_name} {last_name} added as {dict(SchoolTeacher.ROLE_CHOICES).get(role, role)}.'
            )
        except Exception as e:
            messages.error(request, f'Error creating teacher: {e}')

        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherEditView(RoleRequiredMixin, View):
    """Change a teacher's role within a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        school_teacher = get_object_or_404(
            SchoolTeacher, school=school, teacher_id=teacher_id
        )
        new_role = request.POST.get('role', 'teacher')
        specialty = request.POST.get('specialty', '').strip()

        valid_roles = [choice[0] for choice in SchoolTeacher.ROLE_CHOICES]
        if new_role not in valid_roles:
            messages.error(request, 'Invalid role selected.')
            return redirect('admin_school_teachers', school_id=school.id)

        school_teacher.role = new_role
        school_teacher.specialty = specialty
        school_teacher.save()
        messages.success(
            request,
            f'{school_teacher.teacher.get_full_name()} updated.'
        )
        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherRemoveView(RoleRequiredMixin, View):
    """Remove a teacher from a school and delete their account."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        school_teacher = SchoolTeacher.objects.filter(
            school=school, teacher_id=teacher_id
        ).select_related('teacher').first()

        if school_teacher:
            teacher_user = school_teacher.teacher
            teacher_name = teacher_user.get_full_name() or teacher_user.username
            # Delete the SchoolTeacher link
            school_teacher.delete()
            # Delete the user account entirely
            teacher_user.delete()
            messages.success(request, f'{teacher_name} has been removed and their account deleted.')
        else:
            messages.warning(request, 'Teacher was not found at this school.')
        return redirect('admin_school_teachers', school_id=school.id)


class AcademicYearCreateView(RoleRequiredMixin, View):
    """Create a new academic year for a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        return render(request, 'admin_dashboard/academic_year_form.html', {
            'school': school,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
