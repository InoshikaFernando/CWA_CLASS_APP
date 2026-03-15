from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.db import transaction
from django.utils.text import slugify

from accounts.models import CustomUser, Role, UserRole
from accounts.views import _validate_username, _generate_username_suggestion
from .models import School, SchoolTeacher, Department, DepartmentTeacher, DepartmentLevel, ClassRoom, Subject, Level
from .views import RoleRequiredMixin


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
        subjects = Subject.objects.filter(is_active=True).order_by('order', 'name')
        return render(request, 'admin_dashboard/department_form.html', {
            'school': school,
            'subjects': subjects,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        subject_id = request.POST.get('subject', '').strip()
        subjects = Subject.objects.filter(is_active=True).order_by('order', 'name')

        if not name:
            messages.error(request, 'Department name is required.')
            return render(request, 'admin_dashboard/department_form.html', {
                'school': school,
                'subjects': subjects,
                'form_data': {'name': name, 'description': description, 'subject': subject_id},
            })

        # Resolve subject
        subject = None
        if subject_id and subject_id != 'other':
            subject = Subject.objects.filter(id=subject_id, is_active=True).first()

        slug = slugify(name)
        base_slug = slug
        counter = 1
        while Department.objects.filter(school=school, slug=slug).exists():
            slug = f'{base_slug}-{counter}'
            counter += 1

        dept = Department.objects.create(
            school=school,
            name=name,
            slug=slug,
            description=description,
            subject=subject,
        )
        # Auto-assign levels based on subject module via DepartmentLevel M2M
        if subject:
            from .models import DepartmentLevel
            # Find all global levels belonging to this subject (e.g. Year 1-9 for Mathematics)
            subject_levels = Level.objects.filter(
                subject=subject, school__isnull=True,
            ).exclude(
                level_number__gte=100, level_number__lt=200,  # Exclude Basic Facts
            )
            for lv in subject_levels:
                DepartmentLevel.objects.get_or_create(
                    department=dept, level=lv,
                    defaults={'order': lv.level_number},
                )
        if subject:
            messages.success(request, f'Department "{name}" created with {subject.name} question bank.')
        else:
            messages.success(request, f'Department "{name}" created as a custom subject.')
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
        mapped_levels = DepartmentLevel.objects.filter(
            department=department,
        ).select_related('level').order_by('order', 'level__level_number')
        return render(request, 'admin_dashboard/department_detail.html', {
            'school': school,
            'department': department,
            'dept_teachers': dept_teachers,
            'classes': classes,
            'mapped_levels': mapped_levels,
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
                        'username': username,
                    },
                })

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
                    f'{first_name} {last_name} created and assigned as Head of {department.name}. Login username: {username}'
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


class DepartmentManageLevelsView(RoleRequiredMixin, View):
    """Manage which curriculum levels are mapped to a department."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _get_available_levels(self, department):
        """Return subject-appropriate levels for this department."""
        if department.subject and department.subject.slug == 'mathematics':
            # Maths: show Year 1-9 only (global, level_number 1-9)
            return Level.objects.filter(
                subject=department.subject, school__isnull=True,
            ).exclude(
                level_number__gte=100, level_number__lt=200,
            ).order_by('level_number')
        elif department.subject:
            # Other subject with global levels
            return Level.objects.filter(
                subject=department.subject, school__isnull=True,
            ).order_by('level_number')
        else:
            # Custom department (no subject): show school custom levels (200+)
            return Level.objects.filter(
                school=department.school, level_number__gte=200,
            ).order_by('level_number')

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)

        available_levels = self._get_available_levels(department)
        # Current mappings: {level_id: DepartmentLevel}
        current_mappings = {
            dl.level_id: dl
            for dl in DepartmentLevel.objects.filter(department=department).select_related('level')
        }

        level_data = []
        for lv in available_levels:
            dl = current_mappings.get(lv.id)
            level_data.append({
                'level': lv,
                'is_mapped': dl is not None,
                'local_display_name': dl.local_display_name if dl else '',
            })

        return render(request, 'admin_dashboard/department_manage_levels.html', {
            'school': school,
            'department': department,
            'level_data': level_data,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)

        selected_level_ids = request.POST.getlist('level_ids')
        try:
            selected_ids = set(int(lid) for lid in selected_level_ids)
        except (ValueError, TypeError):
            selected_ids = set()

        # Only allow levels that are actually available for this department
        available_levels = self._get_available_levels(department)
        available_ids = set(available_levels.values_list('id', flat=True))
        valid_ids = selected_ids & available_ids

        current_dl_map = {
            dl.level_id: dl
            for dl in DepartmentLevel.objects.filter(department=department)
        }

        with transaction.atomic():
            # Add new mappings
            added = 0
            for level_id in valid_ids:
                if level_id not in current_dl_map:
                    local_name = request.POST.get(f'local_name_{level_id}', '').strip()
                    lv = Level.objects.get(id=level_id)
                    DepartmentLevel.objects.create(
                        department=department, level=lv,
                        local_display_name=local_name,
                        order=lv.level_number,
                    )
                    added += 1
                else:
                    # Update local_display_name if changed
                    local_name = request.POST.get(f'local_name_{level_id}', '').strip()
                    dl = current_dl_map[level_id]
                    if dl.local_display_name != local_name:
                        dl.local_display_name = local_name
                        dl.save(update_fields=['local_display_name'])

            # Remove unchecked levels
            to_remove = set(current_dl_map.keys()) - valid_ids
            # Only remove levels that are in the available set (don't touch mappings outside our scope)
            to_remove = to_remove & available_ids
            removed = DepartmentLevel.objects.filter(
                department=department, level_id__in=to_remove,
            ).delete()[0] if to_remove else 0

        if added or removed:
            parts = []
            if added:
                parts.append(f'{added} added')
            if removed:
                parts.append(f'{removed} removed')
            messages.success(request, f'Level mappings updated: {", ".join(parts)}.')
        else:
            messages.info(request, 'Level mappings saved.')

        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)
