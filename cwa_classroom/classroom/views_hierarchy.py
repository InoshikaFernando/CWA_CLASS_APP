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
            # HoD can view classes in departments they head + classes they teach
            from django.db.models import Q
            accessible_class_ids = set(
                ClassRoom.objects.filter(
                    Q(department__head=user) | Q(class_teachers__teacher=user),
                    is_active=True,
                ).values_list('id', flat=True)
            )
        else:
            # Teachers can only view classes they are assigned to
            accessible_class_ids = set(
                ClassRoom.objects.filter(
                    class_teachers__teacher=user, is_active=True,
                ).values_list('id', flat=True)
            )

        # ── Bulk-fetch all data upfront (eliminates N+1 queries) ──
        all_dept_teacher_links = DepartmentTeacher.objects.filter(
            department__in=departments,
        ).select_related('teacher')

        # Group by department_id
        dept_teacher_map = {}  # dept_id → list of DepartmentTeacher
        for dt in all_dept_teacher_links:
            dept_teacher_map.setdefault(dt.department_id, []).append(dt)

        # All school teacher roles in one query
        all_school_teachers = SchoolTeacher.objects.filter(
            school=school, is_active=True,
        ).select_related('teacher')
        school_teacher_role_map = {}   # teacher_id → role display
        school_teacher_key_map = {}    # teacher_id → role key
        school_teacher_obj_map = {}    # teacher_id → SchoolTeacher
        for st in all_school_teachers:
            school_teacher_role_map[st.teacher_id] = st.get_role_display()
            school_teacher_key_map[st.teacher_id] = st.role
            school_teacher_obj_map[st.teacher_id] = st

        # Build teacher_id → set of class_ids from already-fetched all_class_teachers
        teacher_class_ids = {}  # teacher_id → set of class_ids
        for ct in all_class_teachers:
            teacher_class_ids.setdefault(ct.teacher_id, set()).add(ct.classroom_id)

        # Fetch all active classes for the school with student counts in one query
        all_classes = ClassRoom.objects.filter(
            school=school, is_active=True,
        ).annotate(student_count=Count('class_students')).distinct()
        class_obj_map = {cls.id: cls for cls in all_classes}

        # ── Build per-department hierarchy ───────────────────────
        dept_hierarchy = []
        for dept in departments:
            dept_links = dept_teacher_map.get(dept.id, [])
            # Pre-compute which classes belong to this department
            dept_class_ids = {cls.id for cls in all_classes if cls.department_id == dept.id}

            teachers_data = []
            seen_teacher_ids = set()
            shown_class_ids = set()

            for dt in dept_links:
                teacher = dt.teacher
                seen_teacher_ids.add(teacher.id)
                role_display = school_teacher_role_map.get(teacher.id, 'Teacher')
                role_key = school_teacher_key_map.get(teacher.id, 'teacher')

                # Get classes for this teacher, filtered to THIS department only
                t_class_ids = teacher_class_ids.get(teacher.id, set())
                classes_data = []
                for cid in (t_class_ids & dept_class_ids):
                    cls = class_obj_map.get(cid)
                    if not cls:
                        continue
                    shown_class_ids.add(cid)
                    color = shared_class_colors.get(cid)
                    classes_data.append({
                        'classroom': cls,
                        'is_shared': cid in shared_class_ids,
                        'color': color,
                        'student_count': cls.student_count,
                        'can_view': cid in accessible_class_ids,
                    })

                teachers_data.append({
                    'user': teacher,
                    'role_display': role_display,
                    'role_key': role_key,
                    'classes': classes_data,
                })

            # ── Also include classes that belong to this department via FK ──
            # but whose teachers aren't formally in DepartmentTeacher
            extra_teacher_classes = {}
            for cls in all_classes:
                if cls.department_id == dept.id and cls.id not in shown_class_ids:
                    # Find teachers of this class from pre-built map
                    cls_teacher_ids = class_teacher_map.get(cls.id, set())
                    if cls_teacher_ids:
                        for tid in cls_teacher_ids:
                            if tid not in extra_teacher_classes:
                                teacher_obj = school_teacher_obj_map.get(tid)
                                extra_teacher_classes[tid] = {
                                    'teacher': teacher_obj.teacher if teacher_obj else None,
                                    'classes': [],
                                }
                            color = shared_class_colors.get(cls.id)
                            extra_teacher_classes[tid]['classes'].append({
                                'classroom': cls,
                                'is_shared': cls.id in shared_class_ids,
                                'color': color,
                                'student_count': cls.student_count,
                                'can_view': cls.id in accessible_class_ids,
                            })

            # Merge extra teachers into teachers_data
            for teacher_id, data in extra_teacher_classes.items():
                teacher = data['teacher']
                if not teacher:
                    continue
                if teacher_id in seen_teacher_ids:
                    for td in teachers_data:
                        if td['user'].id == teacher_id:
                            existing_ids = {c['classroom'].id for c in td['classes']}
                            for cls_data in data['classes']:
                                if cls_data['classroom'].id not in existing_ids:
                                    td['classes'].append(cls_data)
                            break
                else:
                    teachers_data.append({
                        'user': teacher,
                        'role_display': school_teacher_role_map.get(teacher_id, 'Teacher'),
                        'role_key': school_teacher_key_map.get(teacher_id, 'teacher'),
                        'classes': data['classes'],
                    })

            # Sort teachers by role priority
            role_order = {
                'head_of_institute': 0,
                'head_of_department': 1,
                'senior_teacher': 2,
                'teacher': 3,
                'junior_teacher': 4,
            }
            teachers_data.sort(key=lambda t: role_order.get(t['role_key'], 5))

            # Collect unassigned classes (in this dept but no teacher at all)
            unassigned_classes = []
            for cls in all_classes:
                if cls.department_id == dept.id and cls.id not in shown_class_ids and cls.id not in class_teacher_map:
                    unassigned_classes.append({
                        'classroom': cls,
                        'student_count': cls.student_count,
                        'can_view': cls.id in accessible_class_ids,
                    })

            dept_hierarchy.append({
                'department': dept,
                'hod': dept.head,
                'teachers': teachers_data,
                'unassigned_classes': unassigned_classes,
            })

        return render(request, 'hierarchy/school_hierarchy.html', {
            'school': school,
            'hoi_users': hoi_users,
            'dept_hierarchy': dept_hierarchy,
            'shared_class_colors': shared_class_colors,
        })
