from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from accounts.views import _validate_username, _generate_username_suggestion
from .models import (
    School, SchoolTeacher, AcademicYear, ClassRoom, ClassSession, Department,
    SchoolStudent, Level, Subject, DepartmentSubject,
)
from .views import RoleRequiredMixin
from .email_utils import send_staff_welcome_email


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
        school_students = SchoolStudent.objects.filter(school=school).select_related('student')
        return render(request, 'admin_dashboard/school_detail.html', {
            'school': school,
            'teachers': teachers,
            'classes': classes,
            'academic_years': academic_years,
            'departments': departments,
            'school_students': school_students,
            'student_count': school_students.count(),
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


class ManageStudentsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's student management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if school:
            return redirect('admin_school_students', school_id=school.id)
        messages.info(request, 'Create a school first before managing students.')
        return redirect('admin_school_create')


class ManageDepartmentsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's department management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if school:
            return redirect('admin_school_departments', school_id=school.id)
        messages.info(request, 'Create a school first before managing departments.')
        return redirect('admin_school_create')


class ManageSubjectsRedirectView(RoleRequiredMixin, View):
    """Shortcut: redirects to the first school's subject management page."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request):
        school = School.objects.filter(admin=request.user).first()
        if school:
            return redirect('admin_school_subjects', school_id=school.id)
        messages.info(request, 'Create a school first before managing subjects.')
        return redirect('admin_school_create')


class SchoolSubjectManageView(RoleRequiredMixin, View):
    """Manage subjects for a school: list global + school-created, create/edit/delete."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        global_subjects = Subject.objects.filter(school__isnull=True, is_active=True).order_by('order', 'name')
        school_subjects = Subject.objects.filter(school=school, is_active=True).order_by('order', 'name')
        return render(request, 'admin_dashboard/school_subjects.html', {
            'school': school,
            'global_subjects': global_subjects,
            'school_subjects': school_subjects,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
            Subject.objects.create(name=name, slug=slug, school=school, is_active=True)
            messages.success(request, f'Subject "{name}" created.')

        elif action == 'edit':
            subject_id = request.POST.get('subject_id')
            name = request.POST.get('name', '').strip()
            subject = Subject.objects.filter(id=subject_id, school=school).first()
            if subject and name:
                subject.name = name
                subject.slug = slugify(name)
                subject.save()
                messages.success(request, f'Subject updated to "{name}".')

        elif action == 'delete':
            subject_id = request.POST.get('subject_id')
            subject = Subject.objects.filter(id=subject_id, school=school).first()
            if subject:
                name = subject.name
                subject.is_active = False
                subject.save()
                messages.success(request, f'Subject "{name}" removed.')

        return redirect('admin_school_subjects', school_id=school.id)


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
            school_teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
            return render(request, 'admin_dashboard/school_teachers.html', {
                'school': school,
                'school_teachers': school_teachers,
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
            messages.error(request, f'Error creating teacher: {e}')

        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherEditView(RoleRequiredMixin, View):
    """Edit a teacher's details and role within a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, teacher_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
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
        school_students = (
            SchoolStudent.objects.filter(school=school)
            .select_related('student')
            .annotate(
                class_count=Count(
                    'student__class_student_entries',
                    filter=Q(student__class_student_entries__classroom__school=school),
                )
            )
        )
        return render(request, 'admin_dashboard/school_students.html', {
            'school': school,
            'school_students': school_students,
        })

    def post(self, request, school_id):
        school = self._get_school(request, school_id)

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
            school_students = SchoolStudent.objects.filter(school=school).select_related('student')
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
                student_role, _ = Role.objects.get_or_create(
                    name=Role.STUDENT, defaults={'display_name': 'Student'}
                )
                UserRole.objects.create(user=user, role=student_role, assigned_by=request.user)
                SchoolStudent.objects.create(school=school, student=user)
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


class SchoolStudentRemoveView(RoleRequiredMixin, View):
    """Remove a student from a school and delete their account."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.TEACHER,
    ]

    def post(self, request, school_id, student_id):
        school = SchoolStudentManageView._get_school(self, request, school_id)
        school_student = SchoolStudent.objects.filter(
            school=school, student_id=student_id
        ).select_related('student').first()

        if school_student:
            student_user = school_student.student
            name = student_user.get_full_name() or student_user.username
            school_student.delete()
            student_user.delete()
            messages.success(request, f'{name} has been removed and their account deleted.')
        else:
            messages.warning(request, 'Student was not found at this school.')
        return redirect('admin_school_students', school_id=school.id)
