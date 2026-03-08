from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify

from accounts.models import CustomUser, Role, UserRole
from .models import School, SchoolTeacher, Department, DepartmentTeacher, ClassRoom
from .views import RoleRequiredMixin
from .email_utils import send_staff_welcome_email


class DepartmentListView(RoleRequiredMixin, View):
    """List departments in a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        departments = Department.objects.filter(school=school).select_related('head')
        dept_data = []
        for dept in departments:
            teacher_count = dept.department_teachers.count()
            class_count = dept.classrooms.filter(is_active=True).count()
            dept_data.append({
                'department': dept,
                'teacher_count': teacher_count,
                'class_count': class_count,
            })
        return render(request, 'admin_dashboard/departments.html', {
            'school': school,
            'dept_data': dept_data,
        })


class DepartmentCreateView(RoleRequiredMixin, View):
    """Create a new department in a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        return render(request, 'admin_dashboard/department_form.html', {
            'school': school,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Department name is required.')
            return render(request, 'admin_dashboard/department_form.html', {
                'school': school,
                'form_data': {'name': name, 'description': description},
            })

        slug = slugify(name)
        base_slug = slug
        counter = 1
        while Department.objects.filter(school=school, slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        Department.objects.create(
            school=school,
            name=name,
            slug=slug,
            description=description,
        )
        messages.success(request, f'Department "{name}" created successfully.')
        return redirect('admin_school_departments', school_id=school.id)


class DepartmentDetailView(RoleRequiredMixin, View):
    """Show department info, HoD, teachers, and classes."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        dept_teachers = DepartmentTeacher.objects.filter(
            department=department
        ).select_related('teacher')
        classes = ClassRoom.objects.filter(
            department=department, is_active=True
        ).prefetch_related('teachers', 'students')
        return render(request, 'admin_dashboard/department_detail.html', {
            'school': school,
            'department': department,
            'dept_teachers': dept_teachers,
            'classes': classes,
        })


class DepartmentEditView(RoleRequiredMixin, View):
    """Edit department name and description."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        return render(request, 'admin_dashboard/department_form.html', {
            'school': school,
            'department': department,
            'form_data': {
                'name': department.name,
                'description': department.description,
            },
            'editing': True,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()

        if not name:
            messages.error(request, 'Department name is required.')
            return render(request, 'admin_dashboard/department_form.html', {
                'school': school,
                'department': department,
                'form_data': {'name': name, 'description': description},
                'editing': True,
            })

        # Update slug if name changed
        if name != department.name:
            slug = slugify(name)
            base_slug = slug
            counter = 1
            while Department.objects.filter(school=school, slug=slug).exclude(id=department.id).exists():
                slug = f'{base_slug}-{counter}'
                counter += 1
            department.slug = slug

        department.name = name
        department.description = description
        department.save()
        messages.success(request, f'Department "{name}" updated successfully.')
        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentAssignHoDView(RoleRequiredMixin, View):
    """Assign an existing teacher as HoD or create a new HoD account."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        # Get teachers already at this school who could be HoD
        school_teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True
        ).select_related('teacher')
        return render(request, 'admin_dashboard/department_assign_hod.html', {
            'school': school,
            'department': department,
            'school_teachers': school_teachers,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        action = request.POST.get('action', '')

        if action == 'assign_existing':
            teacher_id = request.POST.get('teacher_id')
            if not teacher_id:
                messages.error(request, 'Please select a teacher.')
                return redirect('admin_department_assign_hod', school_id=school.id, dept_id=department.id)

            teacher = get_object_or_404(CustomUser, id=teacher_id)
            # Verify teacher belongs to this school
            if not SchoolTeacher.objects.filter(school=school, teacher=teacher, is_active=True).exists():
                messages.error(request, 'This teacher does not belong to this school.')
                return redirect('admin_department_assign_hod', school_id=school.id, dept_id=department.id)

            with transaction.atomic():
                department.head = teacher
                department.save()
                # Ensure the teacher has the HoD system role
                hod_role, _ = Role.objects.get_or_create(
                    name=Role.HEAD_OF_DEPARTMENT,
                    defaults={'display_name': 'Head of Department'},
                )
                UserRole.objects.get_or_create(user=teacher, role=hod_role)
                # Update their school role to head_of_department
                SchoolTeacher.objects.filter(
                    school=school, teacher=teacher
                ).update(role='head_of_department')
                # Also ensure they're a department teacher
                DepartmentTeacher.objects.get_or_create(
                    department=department, teacher=teacher
                )

            messages.success(
                request,
                f'{teacher.get_full_name() or teacher.username} assigned as Head of {department.name}.'
            )
            return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)

        elif action == 'create_new':
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            email = request.POST.get('email', '').strip()
            password = request.POST.get('password', '').strip()

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

            if errors:
                for err in errors:
                    messages.error(request, err)
                school_teachers = SchoolTeacher.objects.filter(
                    school=school, is_active=True
                ).select_related('teacher')
                return render(request, 'admin_dashboard/department_assign_hod.html', {
                    'school': school,
                    'department': department,
                    'school_teachers': school_teachers,
                    'form_data': {
                        'first_name': first_name,
                        'last_name': last_name,
                        'email': email,
                    },
                })

            base_username = email.split('@')[0].lower().replace(' ', '.')
            username = base_username
            counter = 1
            while CustomUser.objects.filter(username=username).exists():
                username = f'{base_username}{counter}'
                counter += 1

            try:
                with transaction.atomic():
                    user = CustomUser.objects.create_user(
                        username=username,
                        email=email,
                        password=password,
                        first_name=first_name,
                        last_name=last_name,
                    )
                    # Assign HoD system role
                    hod_role, _ = Role.objects.get_or_create(
                        name=Role.HEAD_OF_DEPARTMENT,
                        defaults={'display_name': 'Head of Department'},
                    )
                    UserRole.objects.create(user=user, role=hod_role)
                    # Link to school as HoD
                    SchoolTeacher.objects.create(
                        school=school, teacher=user, role='head_of_department',
                    )
                    # Assign as department head
                    department.head = user
                    department.save()
                    # Add as department teacher
                    DepartmentTeacher.objects.create(
                        department=department, teacher=user
                    )

                messages.success(
                    request,
                    f'{first_name} {last_name} created and assigned as Head of {department.name}.'
                )
                # Send welcome email with login credentials
                send_staff_welcome_email(
                    user=user,
                    plain_password=password,
                    role_display='Head of Department',
                    school=school,
                    department=department,
                )
            except Exception as e:
                messages.error(request, f'Error creating HoD: {e}')

            return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)

        messages.error(request, 'Invalid action.')
        return redirect('admin_department_assign_hod', school_id=school.id, dept_id=department.id)


class DepartmentManageTeachersView(RoleRequiredMixin, View):
    """Add/remove teachers from a department."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        # All school teachers
        school_teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True
        ).select_related('teacher')
        # Currently assigned teacher IDs
        assigned_ids = set(
            DepartmentTeacher.objects.filter(department=department).values_list('teacher_id', flat=True)
        )
        return render(request, 'admin_dashboard/department_teachers.html', {
            'school': school,
            'department': department,
            'school_teachers': school_teachers,
            'assigned_ids': assigned_ids,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        selected_teacher_ids = request.POST.getlist('teacher_ids')

        try:
            selected_ids = set(int(tid) for tid in selected_teacher_ids)
        except (ValueError, TypeError):
            selected_ids = set()

        # Validate all selected teachers belong to this school
        valid_teacher_ids = set(
            SchoolTeacher.objects.filter(
                school=school, is_active=True, teacher_id__in=selected_ids
            ).values_list('teacher_id', flat=True)
        )

        current_ids = set(
            DepartmentTeacher.objects.filter(department=department).values_list('teacher_id', flat=True)
        )

        # Don't remove the department head
        head_id = department.head_id

        with transaction.atomic():
            # Add new teachers
            to_add = valid_teacher_ids - current_ids
            for tid in to_add:
                DepartmentTeacher.objects.get_or_create(department=department, teacher_id=tid)

            # Remove unselected teachers (but not the head)
            to_remove = current_ids - valid_teacher_ids
            if head_id:
                to_remove.discard(head_id)
            DepartmentTeacher.objects.filter(
                department=department, teacher_id__in=to_remove
            ).delete()

        added = len(to_add)
        removed = len(to_remove)
        if added or removed:
            parts = []
            if added:
                parts.append(f'{added} added')
            if removed:
                parts.append(f'{removed} removed')
            messages.success(request, f'Department teachers updated: {", ".join(parts)}.')
        else:
            messages.info(request, 'No changes made.')

        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentAssignClassesView(RoleRequiredMixin, View):
    """Assign classrooms to a department."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        # All active classes in this school
        all_classes = ClassRoom.objects.filter(
            school=school, is_active=True
        ).prefetch_related('teachers', 'students')
        # Currently assigned class IDs
        assigned_ids = set(
            ClassRoom.objects.filter(department=department).values_list('id', flat=True)
        )
        return render(request, 'admin_dashboard/department_assign_classes.html', {
            'school': school,
            'department': department,
            'all_classes': all_classes,
            'assigned_ids': assigned_ids,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        selected_class_ids = request.POST.getlist('class_ids')

        try:
            selected_ids = set(int(cid) for cid in selected_class_ids)
        except (ValueError, TypeError):
            selected_ids = set()

        # Validate classes belong to this school
        valid_class_ids = set(
            ClassRoom.objects.filter(
                school=school, is_active=True, id__in=selected_ids
            ).values_list('id', flat=True)
        )

        with transaction.atomic():
            # Assign selected classes to this department
            ClassRoom.objects.filter(id__in=valid_class_ids).update(department=department)
            # Remove from this department any classes that were unselected
            ClassRoom.objects.filter(
                department=department, school=school
            ).exclude(id__in=valid_class_ids).update(department=None)

        messages.success(request, f'Classes assigned to {department.name} updated.')
        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)
