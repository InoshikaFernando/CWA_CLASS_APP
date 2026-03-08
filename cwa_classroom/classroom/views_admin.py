from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify
from django.utils import timezone

from accounts.models import CustomUser, Role, UserRole
from .models import School, SchoolTeacher, AcademicYear, ClassRoom, ClassSession
from .views import RoleRequiredMixin


class AdminDashboardView(RoleRequiredMixin, View):
    """Admin dashboard showing all schools belonging to the current admin."""
    required_role = Role.ADMIN

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
    """Create a new school owned by the current admin."""
    required_role = Role.ADMIN

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
    """Show detailed information about a school the admin owns."""
    required_role = Role.ADMIN

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        classes = ClassRoom.objects.filter(school=school, is_active=True).prefetch_related(
            'teachers', 'students', 'levels'
        )
        academic_years = AcademicYear.objects.filter(school=school)
        return render(request, 'admin_dashboard/school_detail.html', {
            'school': school,
            'teachers': teachers,
            'classes': classes,
            'academic_years': academic_years,
        })


class SchoolTeacherManageView(RoleRequiredMixin, View):
    """Manage teachers assigned to a school: list, add, and update roles."""
    required_role = Role.ADMIN

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        school_teachers = SchoolTeacher.objects.filter(school=school).select_related('teacher')
        assigned_teacher_ids = school_teachers.values_list('teacher_id', flat=True)
        available_teachers = CustomUser.objects.filter(
            roles__name__in=[Role.TEACHER, Role.SENIOR_TEACHER, Role.JUNIOR_TEACHER],
        ).exclude(id__in=assigned_teacher_ids).distinct()
        return render(request, 'admin_dashboard/school_teachers.html', {
            'school': school,
            'school_teachers': school_teachers,
            'available_teachers': available_teachers,
            'role_choices': SchoolTeacher.ROLE_CHOICES,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        teacher_id = request.POST.get('teacher_id')
        role = request.POST.get('role', 'teacher')

        if not teacher_id:
            messages.error(request, 'Please select a teacher.')
            return redirect('admin_school_teachers', school_id=school.id)

        teacher = get_object_or_404(CustomUser, id=teacher_id)

        # Validate role is a valid choice
        valid_roles = [choice[0] for choice in SchoolTeacher.ROLE_CHOICES]
        if role not in valid_roles:
            role = 'teacher'

        school_teacher, created = SchoolTeacher.objects.get_or_create(
            school=school,
            teacher=teacher,
            defaults={'role': role},
        )
        if created:
            messages.success(
                request,
                f'{teacher.username} added to {school.name} as {school_teacher.get_role_display()}.'
            )
        else:
            # Teacher already exists at this school -- update their role
            school_teacher.role = role
            school_teacher.save()
            messages.success(
                request,
                f'{teacher.username} role updated to {school_teacher.get_role_display()}.'
            )

        return redirect('admin_school_teachers', school_id=school.id)


class SchoolTeacherRemoveView(RoleRequiredMixin, View):
    """Remove a teacher from a school."""
    required_role = Role.ADMIN

    def post(self, request, school_id, teacher_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        deleted_count, _ = SchoolTeacher.objects.filter(
            school=school, teacher_id=teacher_id
        ).delete()
        if deleted_count:
            messages.success(request, 'Teacher removed from school.')
        else:
            messages.warning(request, 'Teacher was not found at this school.')
        return redirect('admin_school_teachers', school_id=school.id)


class AcademicYearCreateView(RoleRequiredMixin, View):
    """Create a new academic year for a school."""
    required_role = Role.ADMIN

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
