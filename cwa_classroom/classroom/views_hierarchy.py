from django.db.models import Count
from django.shortcuts import render, get_object_or_404, redirect
from django.views import View
from django.contrib import messages

from accounts.models import Role
from .models import (
    School, SchoolTeacher, Department, DepartmentTeacher,
    ClassRoom, ClassTeacher,
)
from .views import RoleRequiredMixin


# Consistent palette for shared-class colour coding
SHARED_CLASS_COLORS = [
    {'bg': 'bg-blue-100', 'border': 'border-blue-400', 'text': 'text-blue-800'},
    {'bg': 'bg-purple-100', 'border': 'border-purple-400', 'text': 'text-purple-800'},
    {'bg': 'bg-amber-100', 'border': 'border-amber-400', 'text': 'text-amber-800'},
    {'bg': 'bg-rose-100', 'border': 'border-rose-400', 'text': 'text-rose-800'},
    {'bg': 'bg-teal-100', 'border': 'border-teal-400', 'text': 'text-teal-800'},
    {'bg': 'bg-indigo-100', 'border': 'border-indigo-400', 'text': 'text-indigo-800'},
    {'bg': 'bg-lime-100', 'border': 'border-lime-400', 'text': 'text-lime-800'},
    {'bg': 'bg-cyan-100', 'border': 'border-cyan-400', 'text': 'text-cyan-800'},
]


class SchoolHierarchyView(RoleRequiredMixin, View):
    """Tree / org-chart view of a school's staff hierarchy."""
    required_roles = [
        Role.ADMIN, Role.INSTITUTE_OWNER,
        Role.HEAD_OF_INSTITUTE, Role.HEAD_OF_DEPARTMENT,
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, school_id=None):
        # ── resolve school ──────────────────────────────────────
        if school_id:
            school = get_object_or_404(School, pk=school_id, is_active=True)
        else:
            schools = School.objects.filter(admin=request.user, is_active=True)
            if not schools.exists():
                # Try via SchoolTeacher membership
                school_ids = SchoolTeacher.objects.filter(
                    teacher=request.user, is_active=True,
                ).values_list('school_id', flat=True)
                schools = School.objects.filter(pk__in=school_ids, is_active=True)

            if schools.count() == 1:
                school = schools.first()
            elif schools.count() > 1:
                return render(request, 'hierarchy/school_picker.html', {
                    'schools': schools,
                })
            else:
                messages.error(request, 'No schools found.')
                return redirect('hod_overview')

        # ── HoI (head of institute) ─────────────────────────────
        hoi_memberships = SchoolTeacher.objects.filter(
            school=school, role='head_of_institute', is_active=True,
        ).select_related('teacher')
        hoi_users = [m.teacher for m in hoi_memberships]

        # ── Departments with HoDs ───────────────────────────────
        departments = Department.objects.filter(
            school=school, is_active=True,
        ).select_related('head').order_by('name')

        # ── Build class → teacher map to detect shared classes ──
        all_class_teachers = ClassTeacher.objects.filter(
            classroom__school=school, classroom__is_active=True,
        ).select_related('classroom', 'teacher')

        class_teacher_map = {}  # class_id → set of teacher_ids
        for ct in all_class_teachers:
            class_teacher_map.setdefault(ct.classroom_id, set()).add(ct.teacher_id)

        shared_class_ids = {
            cid for cid, tids in class_teacher_map.items() if len(tids) >= 2
        }

        # Assign a colour index to each shared class
        shared_class_colors = {}
        for idx, cid in enumerate(sorted(shared_class_ids)):
            shared_class_colors[cid] = SHARED_CLASS_COLORS[idx % len(SHARED_CLASS_COLORS)]

        # ── Determine which classes this user can access ──────────
        user = request.user
        if user.has_role(Role.ADMIN) or user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
            # Admin / HoI / Owner can view all classes in their school
            accessible_class_ids = set(
                ClassRoom.objects.filter(
                    school=school, is_active=True,
                ).values_list('id', flat=True)
            )
        elif user.has_role(Role.HEAD_OF_DEPARTMENT):
            # HoD can view classes in departments they head
            accessible_class_ids = set(
                ClassRoom.objects.filter(
                    department__head=user, is_active=True,
                ).values_list('id', flat=True)
            )
        else:
            # Teachers can only view classes they are assigned to
            accessible_class_ids = set(
                ClassRoom.objects.filter(
                    class_teachers__teacher=user, is_active=True,
                ).values_list('id', flat=True)
            )

        # ── Build per-department hierarchy ───────────────────────
        dept_hierarchy = []
        for dept in departments:
            # Teachers in this department
            dept_teacher_links = DepartmentTeacher.objects.filter(
                department=dept,
            ).select_related('teacher')

            teacher_ids = [dt.teacher_id for dt in dept_teacher_links]

            # Get SchoolTeacher role for each
            school_teacher_roles = {
                st.teacher_id: st.get_role_display()
                for st in SchoolTeacher.objects.filter(
                    school=school, teacher_id__in=teacher_ids, is_active=True,
                )
            }
            school_teacher_role_keys = {
                st.teacher_id: st.role
                for st in SchoolTeacher.objects.filter(
                    school=school, teacher_id__in=teacher_ids, is_active=True,
                )
            }

            # Build teacher list with classes
            teachers_data = []
            seen_teacher_ids = set()      # track teachers already shown in this dept
            shown_class_ids = set()       # track classes already shown in this dept

            for dt in dept_teacher_links:
                teacher = dt.teacher
                seen_teacher_ids.add(teacher.id)
                role_display = school_teacher_roles.get(teacher.id, 'Teacher')
                role_key = school_teacher_role_keys.get(teacher.id, 'teacher')

                # Classes for this teacher in this department
                teacher_classes = ClassRoom.objects.filter(
                    school=school,
                    department=dept,
                    class_teachers__teacher=teacher,
                    is_active=True,
                ).annotate(
                    student_count=Count('class_students'),
                ).distinct()

                classes_data = []
                for cls in teacher_classes:
                    shown_class_ids.add(cls.id)
                    color = shared_class_colors.get(cls.id)
                    classes_data.append({
                        'classroom': cls,
                        'is_shared': cls.id in shared_class_ids,
                        'color': color,
                        'student_count': cls.student_count,
                        'can_view': cls.id in accessible_class_ids,
                    })

                teachers_data.append({
                    'user': teacher,
                    'role_display': role_display,
                    'role_key': role_key,
                    'classes': classes_data,
                })

            # ── Also include classes that belong to this department via FK ──
            # but whose teachers aren't formally in DepartmentTeacher
            dept_owned_classes = ClassRoom.objects.filter(
                department=dept, is_active=True,
            ).exclude(id__in=shown_class_ids).annotate(
                student_count=Count('class_students'),
            ).distinct()

            # Group these classes by their teacher(s)
            extra_teacher_classes = {}  # teacher_id → list of class_data
            for cls in dept_owned_classes:
                cls_teachers = ClassTeacher.objects.filter(
                    classroom=cls,
                ).select_related('teacher')
                if cls_teachers.exists():
                    for ct in cls_teachers:
                        extra_teacher_classes.setdefault(ct.teacher_id, {
                            'teacher': ct.teacher,
                            'classes': [],
                        })
                        color = shared_class_colors.get(cls.id)
                        extra_teacher_classes[ct.teacher_id]['classes'].append({
                            'classroom': cls,
                            'is_shared': cls.id in shared_class_ids,
                            'color': color,
                            'student_count': cls.student_count,
                            'can_view': cls.id in accessible_class_ids,
                        })

            # Merge extra teachers into teachers_data
            for teacher_id, data in extra_teacher_classes.items():
                teacher = data['teacher']
                if teacher_id in seen_teacher_ids:
                    # Teacher already shown — append their department-owned classes
                    for td in teachers_data:
                        if td['user'].id == teacher_id:
                            existing_ids = {c['classroom'].id for c in td['classes']}
                            for cls_data in data['classes']:
                                if cls_data['classroom'].id not in existing_ids:
                                    td['classes'].append(cls_data)
                            break
                else:
                    # Teacher not in dept — add them with only dept-owned classes
                    st = SchoolTeacher.objects.filter(
                        school=school, teacher=teacher, is_active=True,
                    ).first()
                    teachers_data.append({
                        'user': teacher,
                        'role_display': st.get_role_display() if st else 'Teacher',
                        'role_key': st.role if st else 'teacher',
                        'classes': data['classes'],
                    })

            # Sort teachers: senior_teacher first, then teacher, then junior_teacher
            role_order = {
                'head_of_institute': 0,
                'head_of_department': 1,
                'senior_teacher': 2,
                'teacher': 3,
                'junior_teacher': 4,
            }
            teachers_data.sort(key=lambda t: role_order.get(t['role_key'], 5))

            dept_hierarchy.append({
                'department': dept,
                'hod': dept.head,
                'teachers': teachers_data,
            })

        return render(request, 'hierarchy/school_hierarchy.html', {
            'school': school,
            'hoi_users': hoi_users,
            'dept_hierarchy': dept_hierarchy,
            'shared_class_colors': shared_class_colors,
        })
