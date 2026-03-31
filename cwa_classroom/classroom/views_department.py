from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction, models
from django.utils.text import slugify

from accounts.models import CustomUser, Role, UserRole
from accounts.views import _validate_username, _generate_username_suggestion
from audit.services import log_event
from .models import School, SchoolTeacher, Department, DepartmentTeacher, DepartmentLevel, DepartmentSubject, ClassRoom, Subject, Level
from .views import RoleRequiredMixin
from .email_utils import send_staff_welcome_email


class DepartmentListView(RoleRequiredMixin, View):
    """List departments in a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        show_inactive = request.GET.get('show_inactive') == '1'
        departments = Department.objects.filter(school=school).select_related('head')
        if not show_inactive:
            departments = departments.filter(is_active=True)
        dept_data = []
        total_teachers = 0
        total_classes = 0
        for dept in departments:
            teacher_count = dept.department_teachers.count()
            class_count = dept.classrooms.filter(is_active=True).count()
            total_teachers += teacher_count
            total_classes += class_count
            dept_data.append({
                'department': dept,
                'teacher_count': teacher_count,
                'class_count': class_count,
            })
        paginator = Paginator(dept_data, 25)
        page = paginator.get_page(request.GET.get('page'))
        return render(request, 'admin_dashboard/departments.html', {
            'school': school,
            'dept_data': page,
            'page': page,
            'total_departments': len(dept_data),
            'total_teachers': total_teachers,
            'total_classes': total_classes,
            'show_inactive': show_inactive,
        })


class DepartmentCreateView(RoleRequiredMixin, View):
    """Create a new department in a school."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_subjects(self, school):
        """Return global subjects + school-created subjects for the dropdown."""
        from django.db.models import Q
        return Subject.objects.filter(
            Q(school__isnull=True) | Q(school=school),
            is_active=True,
        ).order_by('order', 'name')

    def get(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        subjects = self._get_subjects(school)
        return render(request, 'admin_dashboard/department_form.html', {
            'school': school,
            'subjects': subjects,
        })

    def post(self, request, school_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        subject_ids = request.POST.getlist('subjects')  # Multi-select
        new_subject_name = request.POST.get('new_subject_name', '').strip()
        subjects = self._get_subjects(school)

        if not name:
            messages.error(request, 'Department name is required.')
            return render(request, 'admin_dashboard/department_form.html', {
                'school': school,
                'subjects': subjects,
                'form_data': {'name': name, 'description': description,
                              'selected_subject_ids': subject_ids,
                              'new_subject_name': new_subject_name},
            })

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
        )

        # Resolve selected subjects and create DepartmentSubject links
        resolved_subjects = []
        for sid in subject_ids:
            if sid == 'new':
                continue  # Handled below
            subj = Subject.objects.filter(id=sid, is_active=True).first()
            if subj:
                resolved_subjects.append(subj)

        # Handle "Create New Subject" option
        if new_subject_name:
            subj_slug = slugify(new_subject_name)
            base_s = subj_slug
            cnt = 1
            while Subject.objects.filter(school=school, slug=subj_slug).exists():
                subj_slug = f'{base_s}-{cnt}'
                cnt += 1
            new_subj = Subject.objects.create(
                name=new_subject_name, slug=subj_slug, school=school, is_active=True,
            )
            resolved_subjects.append(new_subj)

        # Create DepartmentSubject links and auto-map levels
        for order, subj in enumerate(resolved_subjects):
            DepartmentSubject.objects.get_or_create(
                department=dept, subject=subj,
                defaults={'order': order},
            )
            # Auto-assign global levels for this subject
            subj_levels = Level.objects.filter(
                subject=subj, school__isnull=True,
            ).exclude(level_number__gte=100, level_number__lt=200)
            for lv in subj_levels:
                DepartmentLevel.objects.get_or_create(
                    department=dept, level=lv,
                    defaults={'order': lv.level_number},
                )

        if resolved_subjects:
            names = ', '.join(s.name for s in resolved_subjects)
            messages.success(request, f'Department "{name}" created with subjects: {names}.')
        else:
            messages.success(request, f'Department "{name}" created.')
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_created',
            detail={'department_id': dept.id, 'name': name,
                    'subjects': [s.name for s in resolved_subjects]},
            request=request,
        )
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
        ).prefetch_related('teachers', 'students', 'levels')
        mapped_levels = DepartmentLevel.objects.filter(
            department=department,
        ).select_related('level', 'level__subject').order_by('order', 'level__level_number')

        # Department subjects
        department_subjects = DepartmentSubject.objects.filter(
            department=department,
        ).select_related('subject').order_by('subject__name')

        # Subject levels with class counts, grouped by subject (exclude Basic Facts)
        subject_groups = []
        for ds in department_subjects:
            levels_for_subject = []
            for dl in mapped_levels:
                lv = dl.level
                if 100 <= lv.level_number < 200:
                    continue
                if lv.subject_id == ds.subject_id:
                    cls_count = sum(1 for c in classes if lv in c.levels.all())
                    levels_for_subject.append({'level': lv, 'class_count': cls_count})
            subject_groups.append({
                'subject': ds.subject,
                'levels': levels_for_subject,
            })
        # Also collect levels with no subject match (orphaned or unlinked)
        assigned_subject_ids = {ds.subject_id for ds in department_subjects}
        orphan_levels = []
        for dl in mapped_levels:
            lv = dl.level
            if 100 <= lv.level_number < 200:
                continue
            if lv.subject_id not in assigned_subject_ids:
                cls_count = sum(1 for c in classes if lv in c.levels.all())
                orphan_levels.append({'level': lv, 'class_count': cls_count})

        # Group classes by their first level for display
        from collections import OrderedDict
        classes_by_level = OrderedDict()
        ungrouped = []
        for cls in classes:
            cls_levels = list(cls.levels.all())
            if cls_levels:
                key = cls_levels[0].display_name
                classes_by_level.setdefault(key, []).append(cls)
            else:
                ungrouped.append(cls)
        if ungrouped:
            classes_by_level['No Level'] = ungrouped

        return render(request, 'admin_dashboard/department_detail.html', {
            'school': school,
            'department': department,
            'department_subjects': department_subjects,
            'dept_teachers': dept_teachers,
            'classes': classes,
            'mapped_levels': mapped_levels,
            'subject_groups': subject_groups,
            'orphan_levels': orphan_levels,
            'classes_by_level': classes_by_level,
        })


class DepartmentEditView(RoleRequiredMixin, View):
    """Edit department name, description, and subject."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def _get_subjects(self, school):
        from django.db.models import Q
        return Subject.objects.filter(
            Q(school__isnull=True) | Q(school=school),
            is_active=True,
        ).order_by('order', 'name')

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        subjects = self._get_subjects(school)
        current_subject_ids = list(
            DepartmentSubject.objects.filter(department=department)
            .values_list('subject_id', flat=True)
        )
        return render(request, 'admin_dashboard/department_form.html', {
            'school': school,
            'department': department,
            'subjects': subjects,
            'form_data': {
                'name': department.name,
                'description': department.description,
                'selected_subject_ids': [str(sid) for sid in current_subject_ids],
            },
            'editing': True,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        name = request.POST.get('name', '').strip()
        description = request.POST.get('description', '').strip()
        subject_ids = request.POST.getlist('subjects')
        new_subject_name = request.POST.get('new_subject_name', '').strip()

        if not name:
            messages.error(request, 'Department name is required.')
            subjects = self._get_subjects(school)
            return render(request, 'admin_dashboard/department_form.html', {
                'school': school,
                'department': department,
                'subjects': subjects,
                'form_data': {'name': name, 'description': description,
                              'selected_subject_ids': subject_ids},
                'editing': True,
            })

        # Resolve selected subjects
        new_subject_set = set()
        for sid in subject_ids:
            if sid == 'new':
                continue
            subj = Subject.objects.filter(id=sid, is_active=True).first()
            if subj:
                new_subject_set.add(subj.id)

        # Handle "Create New Subject"
        if new_subject_name:
            subj_slug = slugify(new_subject_name)
            base_s = subj_slug
            cnt = 1
            while Subject.objects.filter(school=school, slug=subj_slug).exists():
                subj_slug = f'{base_s}-{cnt}'
                cnt += 1
            new_subj = Subject.objects.create(
                name=new_subject_name, slug=subj_slug, school=school, is_active=True,
            )
            new_subject_set.add(new_subj.id)

        # Sync DepartmentSubject rows
        current_ds = {ds.subject_id: ds for ds in DepartmentSubject.objects.filter(department=department)}
        current_ids = set(current_ds.keys())

        with transaction.atomic():
            # Add new subjects
            for sid in (new_subject_set - current_ids):
                DepartmentSubject.objects.create(
                    department=department, subject_id=sid,
                    order=DepartmentSubject.objects.filter(department=department).count(),
                )
                # Auto-assign global levels for newly added subjects
                subj_levels = Level.objects.filter(
                    subject_id=sid, school__isnull=True,
                ).exclude(level_number__gte=100, level_number__lt=200)
                for lv in subj_levels:
                    DepartmentLevel.objects.get_or_create(
                        department=department, level=lv,
                        defaults={'order': lv.level_number},
                    )
            # Remove unchecked subjects
            for sid in (current_ids - new_subject_set):
                current_ds[sid].delete()

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
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_edited',
            detail={'department_id': department.id, 'name': name},
            request=request,
        )
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

            log_event(
                user=request.user, school=school, category='data_change',
                action='department_hod_assigned',
                detail={'department_id': department.id, 'department': department.name,
                        'hod_id': teacher.id, 'hod': teacher.get_full_name() or teacher.username},
                request=request,
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

                log_event(
                    user=request.user, school=school, category='data_change',
                    action='department_hod_assigned',
                    detail={'department_id': department.id, 'department': department.name,
                            'hod_id': user.id, 'hod': f'{first_name} {last_name}',
                            'new_account': True},
                    request=request,
                )
                messages.success(
                    request,
                    f'{first_name} {last_name} created and assigned as Head of {department.name}. Login username: {username}'
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
        paginator = Paginator(school_teachers, 25)
        page = paginator.get_page(request.GET.get('page'))
        # Currently assigned teacher IDs
        assigned_ids = set(
            DepartmentTeacher.objects.filter(department=department).values_list('teacher_id', flat=True)
        )
        return render(request, 'admin_dashboard/department_teachers.html', {
            'school': school,
            'department': department,
            'school_teachers': page,
            'page': page,
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
            log_event(
                user=request.user, school=school, category='data_change',
                action='department_teachers_updated',
                detail={'department_id': department.id, 'department': department.name,
                        'added': added, 'removed': removed},
                request=request,
            )
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

        log_event(
            user=request.user, school=school, category='data_change',
            action='department_classes_assigned',
            detail={'department_id': department.id, 'department': department.name,
                    'class_ids': list(valid_class_ids)},
            request=request,
        )
        messages.success(request, f'Classes assigned to {department.name} updated.')
        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentManageLevelsView(RoleRequiredMixin, View):
    """Manage which curriculum levels are mapped to a department."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _get_available_levels(self, department):
        """Return subject-appropriate levels for this department (across all its subjects)."""
        from django.db.models import Q
        dept_subject_ids = list(
            DepartmentSubject.objects.filter(department=department)
            .values_list('subject_id', flat=True)
        )
        if dept_subject_ids:
            # Show global levels from all the department's subjects
            qs = Level.objects.filter(
                subject_id__in=dept_subject_ids, school__isnull=True,
            ).exclude(
                level_number__gte=100, level_number__lt=200,
            ).order_by('level_number')
            return qs
        else:
            # Custom department (no subjects): show school custom levels (200+)
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
            log_event(
                user=request.user, school=school, category='data_change',
                action='department_levels_updated',
                detail={'department_id': department.id, 'department': department.name,
                        'added': added, 'removed': removed},
                request=request,
            )
            messages.success(request, f'Level mappings updated: {", ".join(parts)}.')
        else:
            messages.info(request, 'Level mappings saved.')

        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentSubjectLevelsView(RoleRequiredMixin, View):
    """Manage subject levels for a department — create new levels, view existing."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def _next_level_number(self):
        """Return the next available level_number (min 300 for subject levels)."""
        from django.db.models import Max
        max_num = Level.objects.aggregate(m=Max('level_number'))['m'] or 0
        return max(max_num + 1, 300)

    def _get_available_subjects(self, department):
        """Return subjects available to add (global + school-created, not already assigned)."""
        from django.db.models import Q
        assigned_ids = set(
            DepartmentSubject.objects.filter(department=department)
            .values_list('subject_id', flat=True)
        )
        return Subject.objects.filter(
            Q(school__isnull=True) | Q(school=department.school),
            is_active=True,
        ).exclude(id__in=assigned_ids).order_by('order', 'name')

    def get(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)

        # Department subjects
        dept_subjects = DepartmentSubject.objects.filter(
            department=department,
        ).select_related('subject').order_by('subject__name')

        # Levels mapped to this department via DepartmentLevel (exclude Basic Facts)
        dept_levels = (
            DepartmentLevel.objects.filter(department=department)
            .select_related('level', 'level__subject')
            .exclude(level__level_number__gte=100, level__level_number__lt=200)
            .order_by('order', 'level__level_number')
        )

        from .fee_utils import get_parent_fee_for_subject, get_parent_fee_for_level

        # Group levels by subject
        subject_groups = []
        for ds in dept_subjects:
            parent_fee, parent_source = get_parent_fee_for_subject(department)
            levels_for_subject = []
            for dl in dept_levels:
                if dl.level.subject_id == ds.subject_id:
                    class_count = ClassRoom.objects.filter(
                        department=department, levels=dl.level, is_active=True,
                    ).count()
                    lvl_parent_fee, lvl_parent_source = get_parent_fee_for_level(dl)
                    levels_for_subject.append({
                        'dept_level': dl,
                        'level': dl.level,
                        'class_count': class_count,
                        'parent_fee': lvl_parent_fee,
                        'parent_source': lvl_parent_source,
                    })
            subject_groups.append({
                'subject': ds.subject,
                'dept_subject': ds,
                'levels': levels_for_subject,
                'parent_fee': parent_fee,
                'parent_source': parent_source,
            })

        available_subjects = self._get_available_subjects(department)

        # All departments in this school (for "move subject" dropdown)
        all_departments = Department.objects.filter(
            school=school, is_active=True,
        ).exclude(id=department.id).order_by('name')

        # Global levels already mapped to this department
        mapped_level_ids = set(dept_levels.values_list('level_id', flat=True))

        # All available global levels (Year 1–9 + subject-specific), excluding BF
        all_global_levels = (
            Level.objects.filter(school__isnull=True, level_number__lt=100)
            .order_by('level_number')
        )

        # Per-subject: which global levels are not yet mapped
        for group in subject_groups:
            subj = group['subject']
            # Levels with this subject OR the general Year 1-9 global levels
            subject_global = all_global_levels.filter(
                models.Q(subject=subj) | models.Q(subject__isnull=True)
            ).exclude(id__in=mapped_level_ids)
            group['available_global_levels'] = list(subject_global)

        # For the modal: global levels not yet mapped (used if no subjects yet)
        unmapped_global_levels = list(all_global_levels.exclude(id__in=mapped_level_ids))

        return render(request, 'admin_dashboard/department_subject_levels.html', {
            'school': school,
            'department': department,
            'dept_subjects': dept_subjects,
            'subject_groups': subject_groups,
            'available_subjects': available_subjects,
            'all_departments': all_departments,
            'unmapped_global_levels': unmapped_global_levels,
        })

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)

        action = request.POST.get('action', 'add_level')

        # ---- Add Subject action ----
        if action == 'add_subject':
            add_subject_id = request.POST.get('add_subject_id', '').strip()
            new_subject_name = request.POST.get('new_subject_name', '').strip()

            if add_subject_id:
                subj = Subject.objects.filter(id=add_subject_id, is_active=True).first()
                if subj:
                    ds, created = DepartmentSubject.objects.get_or_create(
                        department=department, subject=subj,
                        defaults={'order': DepartmentSubject.objects.filter(department=department).count()},
                    )
                    if created:
                        # Auto-map subject-specific global levels (if any)
                        subj_levels = Level.objects.filter(
                            subject=subj, school__isnull=True,
                        ).exclude(level_number__gte=100, level_number__lt=200)
                        for lv in subj_levels:
                            DepartmentLevel.objects.get_or_create(
                                department=department, level=lv,
                                defaults={'order': lv.level_number},
                            )
                        log_event(
                            user=request.user, school=school, category='data_change',
                            action='department_subject_added',
                            detail={'department_id': department.id, 'department': department.name,
                                    'subject_id': subj.id, 'subject': subj.name},
                            request=request,
                        )
                        messages.success(request, f'Subject "{subj.name}" added to {department.name}.')
                    else:
                        messages.info(request, f'Subject "{subj.name}" is already assigned.')
            elif new_subject_name:
                subj_slug = slugify(new_subject_name)
                base_slug = subj_slug
                counter = 1
                while Subject.objects.filter(school=department.school, slug=subj_slug).exists():
                    subj_slug = f'{base_slug}-{counter}'
                    counter += 1
                subj = Subject.objects.create(
                    name=new_subject_name, slug=subj_slug, school=department.school, is_active=True,
                )
                DepartmentSubject.objects.create(
                    department=department, subject=subj,
                    order=DepartmentSubject.objects.filter(department=department).count(),
                )
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='department_subject_added',
                    detail={'department_id': department.id, 'department': department.name,
                            'subject_id': subj.id, 'subject': new_subject_name,
                            'new_subject': True},
                    request=request,
                )
                messages.success(request, f'Subject "{new_subject_name}" created and added.')
            else:
                messages.error(request, 'Select a subject or enter a new subject name.')

            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # ---- Edit Subject Fee action ----
        if action == 'edit_subject_fee':
            from decimal import Decimal, InvalidOperation
            subject_id = request.POST.get('subject_id', '').strip()
            fee_str = request.POST.get('fee_override', '').strip()
            ds = DepartmentSubject.objects.filter(department=department, subject_id=subject_id).first()
            if ds:
                if fee_str:
                    try:
                        ds.fee_override = Decimal(fee_str)
                    except InvalidOperation:
                        messages.error(request, 'Invalid fee amount.')
                        return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)
                else:
                    ds.fee_override = None
                ds.save(update_fields=['fee_override'])
                log_event(
                    user=request.user, school=school, category='data_change',
                    action='department_subject_fee_updated',
                    detail={'department_id': department.id, 'department': department.name,
                            'subject_id': ds.subject_id, 'subject': ds.subject.name,
                            'fee_override': str(ds.fee_override) if ds.fee_override is not None else None},
                    request=request,
                )
                messages.success(request, f'Fee for {ds.subject.name} updated.')
            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # ---- Edit Subject action ----
        if action == 'edit_subject':
            subject_id = request.POST.get('subject_id', '').strip()
            new_name = request.POST.get('subject_name', '').strip()
            new_dept_id = request.POST.get('new_department_id', '').strip()

            ds = DepartmentSubject.objects.filter(department=department, subject_id=subject_id).select_related('subject').first()
            if not ds:
                messages.error(request, 'Subject not found in this department.')
                return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

            subject = ds.subject

            # Update subject name
            if new_name and new_name != subject.name:
                subject.name = new_name
                subject.slug = slugify(new_name)
                # Ensure slug uniqueness
                base_slug = subject.slug
                counter = 1
                while Subject.objects.filter(school=subject.school, slug=subject.slug).exclude(id=subject.id).exists():
                    subject.slug = f'{base_slug}-{counter}'
                    counter += 1
                subject.save(update_fields=['name', 'slug'])

            # Move subject to a different department
            if new_dept_id and int(new_dept_id) != department.id:
                new_dept = Department.objects.filter(id=new_dept_id, school=school, is_active=True).first()
                if new_dept:
                    # Check the subject isn't already in the target department
                    if DepartmentSubject.objects.filter(department=new_dept, subject=subject).exists():
                        messages.error(request, f'Subject "{subject.name}" is already in {new_dept.name}.')
                    else:
                        # Move the DepartmentSubject record
                        ds.department = new_dept
                        ds.save(update_fields=['department'])

                        # Also move associated DepartmentLevel records
                        DepartmentLevel.objects.filter(
                            department=department,
                            level__subject=subject,
                        ).update(department=new_dept)

                        # Update classes under this subject to the new department
                        ClassRoom.objects.filter(
                            department=department,
                            subject=subject,
                            is_active=True,
                        ).update(department=new_dept)

                        log_event(
                            user=request.user, school=school, category='data_change',
                            action='department_subject_moved',
                            detail={'department_id': department.id, 'department': department.name,
                                    'subject_id': subject.id, 'subject': subject.name,
                                    'new_department_id': new_dept.id, 'new_department': new_dept.name},
                            request=request,
                        )
                        messages.success(request, f'Subject "{subject.name}" moved to {new_dept.name}.')
                        return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)
                else:
                    messages.error(request, 'Target department not found.')
                    return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

            log_event(
                user=request.user, school=school, category='data_change',
                action='department_subject_edited',
                detail={'department_id': department.id, 'department': department.name,
                        'subject_id': subject.id, 'subject': subject.name},
                request=request,
            )
            messages.success(request, f'Subject "{subject.name}" updated.')
            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # ---- Edit Level action ----
        if action == 'edit_level':
            from decimal import Decimal, InvalidOperation
            level_id = request.POST.get('level_id', '').strip()
            display_name = request.POST.get('display_name', '').strip()
            description = request.POST.get('description', '').strip()
            fee_str = request.POST.get('fee_override', '').strip()
            if level_id and display_name:
                level = Level.objects.filter(id=level_id).first()
                dl = DepartmentLevel.objects.filter(department=department, level=level).first() if level else None
                if level and dl:
                    level.display_name = display_name
                    level.description = description
                    level.save()
                    # Update fee override on DepartmentLevel
                    if fee_str:
                        try:
                            dl.fee_override = Decimal(fee_str)
                        except InvalidOperation:
                            dl.fee_override = None
                    else:
                        dl.fee_override = None
                    dl.save(update_fields=['fee_override'])
                    log_event(
                        user=request.user, school=school, category='data_change',
                        action='department_level_edited',
                        detail={'department_id': department.id, 'department': department.name,
                                'level_id': level.id, 'display_name': display_name},
                        request=request,
                    )
                    messages.success(request, f'Level "{display_name}" updated.')
                else:
                    messages.error(request, 'Level not found in this department.')
            else:
                messages.error(request, 'Level name is required.')
            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # ---- Link existing global level ----
        if action == 'link_level':
            global_level_id = request.POST.get('global_level_id', '').strip()
            subject_id = request.POST.get('subject_id', '').strip()
            if not global_level_id:
                messages.error(request, 'Select a global level to link.')
                return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)
            level = Level.objects.filter(id=global_level_id, school__isnull=True).first()
            if not level:
                messages.error(request, 'Invalid level selected.')
                return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)
            dl, created = DepartmentLevel.objects.get_or_create(
                department=department, level=level,
                defaults={'order': level.level_number},
            )
            if created:
                messages.success(request, f'"{level.display_name}" linked to {department.name}.')
            else:
                messages.info(request, f'"{level.display_name}" is already linked.')
            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # ---- Add Level action (default) ----
        level_name = request.POST.get('level_name', '').strip()
        level_description = request.POST.get('level_description', '').strip()
        subject_id = request.POST.get('subject_id', '').strip()

        if not level_name:
            messages.error(request, 'Level name is required.')
            return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)

        # Resolve which subject this level belongs to
        subject = None
        if subject_id:
            subject = Subject.objects.filter(id=subject_id, is_active=True).first()

        # If no subject selected and department has no subjects, auto-create one
        if not subject:
            dept_subjects = DepartmentSubject.objects.filter(department=department).select_related('subject')
            if dept_subjects.exists():
                # Use the first subject by default
                subject = dept_subjects.first().subject
            else:
                # Auto-create a subject from department name
                subj_slug = slugify(department.name)
                base_slug = subj_slug
                counter = 1
                while Subject.objects.filter(school=school, slug=subj_slug).exists():
                    subj_slug = f'{base_slug}-{counter}'
                    counter += 1
                subject = Subject.objects.create(
                    name=department.name, slug=subj_slug, school=school, is_active=True,
                )
                DepartmentSubject.objects.create(
                    department=department, subject=subject, order=0,
                )
                messages.info(request, f'Subject "{subject.name}" created for this department.')

        level_number = self._next_level_number()
        with transaction.atomic():
            level = Level.objects.create(
                level_number=level_number,
                display_name=level_name,
                description=level_description,
                subject=subject,
            )
            DepartmentLevel.objects.get_or_create(
                department=department, level=level,
                defaults={'order': level_number},
            )

        log_event(
            user=request.user, school=school, category='data_change',
            action='department_level_created',
            detail={'department_id': department.id, 'department': department.name,
                    'level_id': level.id, 'level_name': level_name,
                    'subject_id': subject.id, 'subject': subject.name},
            request=request,
        )
        messages.success(request, f'Level "{level_name}" created under {subject.name}.')
        return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)


class DepartmentUpdateFeeView(RoleRequiredMixin, View):
    """Inline update of department default_fee."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)
        fee_str = request.POST.get('default_fee', '').strip()
        if fee_str:
            from decimal import Decimal, InvalidOperation
            try:
                department.default_fee = Decimal(fee_str)
            except InvalidOperation:
                messages.error(request, 'Invalid fee amount.')
                return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)
        else:
            department.default_fee = None
        department.save(update_fields=['default_fee'])
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_fee_updated',
            detail={'department_id': department.id, 'department': department.name,
                    'default_fee': str(department.default_fee) if department.default_fee is not None else None},
            request=request,
        )
        messages.success(request, 'Department fee updated.')
        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentSubjectLevelRemoveView(RoleRequiredMixin, View):
    """Remove a level mapping from a department (does not delete the Level itself)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT]

    def post(self, request, school_id, dept_id, level_id):
        school = get_object_or_404(School, id=school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)
        deleted, _ = DepartmentLevel.objects.filter(
            department=department, level_id=level_id,
        ).delete()
        if deleted:
            log_event(
                user=request.user, school=school, category='data_change',
                action='department_level_removed',
                detail={'department_id': department.id, 'department': department.name,
                        'level_id': level_id},
                request=request,
            )
            messages.success(request, 'Level removed from department.')
        else:
            messages.info(request, 'Level was not mapped to this department.')
        return redirect('admin_department_subject_levels', school_id=school.id, dept_id=department.id)


class DepartmentToggleActiveView(RoleRequiredMixin, View):
    """Toggle the is_active status of a department."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)
        department.is_active = not department.is_active
        department.save(update_fields=['is_active'])
        status = 'activated' if department.is_active else 'deactivated'
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_toggled_active',
            detail={'department_id': department.id, 'name': department.name,
                    'is_active': department.is_active},
            request=request,
        )
        messages.success(request, f'Department "{department.name}" has been {status}.')
        return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)


class DepartmentDeleteView(RoleRequiredMixin, View):
    """Delete a department if it has no classes or teachers."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE]

    def post(self, request, school_id, dept_id):
        school = get_object_or_404(School, id=school_id, admin=request.user)
        department = get_object_or_404(Department, id=dept_id, school=school)

        class_count = department.classrooms.filter(is_active=True).count()
        teacher_count = department.department_teachers.count()

        if class_count > 0 or teacher_count > 0:
            parts = []
            if class_count > 0:
                parts.append(f'{class_count} class{"es" if class_count != 1 else ""}')
            if teacher_count > 0:
                parts.append(f'{teacher_count} teacher{"s" if teacher_count != 1 else ""}')
            messages.error(
                request,
                f'Cannot deactivate "{department.name}" — it still has {" and ".join(parts)}. '
                f'Remove or reassign them first.',
            )
            return redirect('admin_department_detail', school_id=school.id, dept_id=department.id)

        dept_name = department.name
        department.is_active = False
        department.save(update_fields=['is_active'])
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_deleted',
            detail={'department_id': department.id, 'name': dept_name},
            request=request,
        )
        messages.success(request, f'Department "{dept_name}" has been deactivated.')
        return redirect('admin_school_departments', school_id=school.id)


class DepartmentSettingsView(RoleRequiredMixin, View):
    """Manage department-level settings overrides (banking, company, invoice)."""
    required_roles = [Role.ADMIN, Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE, Role.ACCOUNTANT]

    OVERRIDE_FIELDS = [
        'bank_name', 'bank_bsb', 'bank_account_number', 'bank_account_name',
        'invoice_terms', 'invoice_due_days',
        'outgoing_email',
        'abn', 'gst_number',
        'street_address', 'city', 'state_region', 'postal_code', 'country',
    ]

    @staticmethod
    def _is_field_set(value):
        """Check if a field value is meaningfully set (not None/empty)."""
        if value is None:
            return False
        if hasattr(value, 'name'):  # FileField/ImageField
            return bool(value)
        if isinstance(value, str) and value == '':
            return False
        return True

    def _build_form_data(self, department, school):
        """Build form data with department overrides and school defaults."""
        data = {}
        for field in self.OVERRIDE_FIELDS:
            dept_val = getattr(department, field, None)
            school_val = getattr(school, field, '')
            is_set = self._is_field_set(dept_val)
            data[field] = {
                'value': dept_val if is_set else '',
                'school_default': school_val,
                'is_overridden': is_set,
            }
        return data

    def _get_school(self, user, school_id):
        from .views_admin import _get_user_school_or_404
        return _get_user_school_or_404(user, school_id)

    def get(self, request, school_id, dept_id):
        school = self._get_school(request.user, school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)
        return render(request, 'admin_dashboard/department_settings.html', {
            'school': school,
            'department': department,
            'form_data': self._build_form_data(department, school),
        })

    def post(self, request, school_id, dept_id):
        school = self._get_school(request.user, school_id)
        department = get_object_or_404(Department, id=dept_id, school=school)

        for field in self.OVERRIDE_FIELDS:
            override_key = f'override_{field}'
            is_overridden = request.POST.get(override_key) == '1'

            if is_overridden:
                val = request.POST.get(field, '').strip()
                if field == 'invoice_due_days':
                    try:
                        setattr(department, field, int(val) if val else None)
                    except ValueError:
                        setattr(department, field, None)
                else:
                    setattr(department, field, val)
            else:
                # Clear override — revert to school default
                if field == 'invoice_due_days':
                    setattr(department, field, None)
                else:
                    setattr(department, field, '')

        # Handle logo upload
        if request.POST.get('override_logo') == '1' and 'logo' in request.FILES:
            department.logo = request.FILES['logo']
        if request.POST.get('remove_logo') == '1':
            department.logo = ''

        department.save()
        log_event(
            user=request.user, school=school, category='data_change',
            action='department_settings_updated',
            detail={'department_id': department.id, 'department': department.name},
            request=request,
        )
        messages.success(request, f'Settings for "{department.name}" saved successfully.')
        return redirect('admin_department_settings', school_id=school.id, dept_id=department.id)
