def user_role(request):
    """Inject primary role and role booleans into every template context."""
    if not request.user.is_authenticated:
        return {}

    ctx = {
        'primary_role': request.user.primary_role,
        'is_student': request.user.is_student,
        'is_individual_student': request.user.is_individual_student,
        'is_senior_teacher': request.user.is_senior_teacher,
        'is_teacher': request.user.is_teacher,
        'is_junior_teacher': request.user.is_junior_teacher,
        'is_any_teacher': request.user.is_any_teacher,
        'is_hoi': request.user.is_head_of_institute,
        'is_hod': request.user.is_head_of_department,
        'is_institute_owner': request.user.is_institute_owner,
        'is_accountant': request.user.is_accountant,
        'is_admin_user': request.user.is_admin_user,
        'is_parent': request.user.is_parent,
    }

    # Pending enrollment count for sidebar badge (HoI/HoD/teachers only)
    if ctx['is_hoi'] or ctx['is_hod'] or ctx['is_institute_owner'] or ctx['is_any_teacher']:
        from classroom.models import Enrollment, SchoolTeacher, ClassRoom
        try:
            st = SchoolTeacher.objects.filter(
                teacher=request.user, is_active=True
            ).first()
            if st:
                if ctx['is_hoi'] or ctx['is_institute_owner']:
                    classes = ClassRoom.objects.filter(school=st.school, is_active=True)
                else:
                    classes = ClassRoom.objects.filter(
                        school=st.school, is_active=True, teacher=request.user
                    )
                ctx['sidebar_pending_enrollments'] = Enrollment.objects.filter(
                    classroom__in=classes, status='pending'
                ).count()
            else:
                ctx['sidebar_pending_enrollments'] = 0
        except Exception:
            ctx['sidebar_pending_enrollments'] = 0

    return ctx
