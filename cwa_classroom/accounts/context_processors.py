from .models import Role


def user_role(request):
    """Inject primary role, role booleans, and subscription info into every template context."""
    if not request.user.is_authenticated:
        return {}

    user = request.user

    # Determine the effective active role: session override takes priority
    all_role_names = list(user.roles.filter(is_active=True).values_list('name', flat=True))
    session_role = request.session.get('active_role')
    if session_role and user.has_role(session_role):
        active_role = session_role
    else:
        active_role = user.primary_role

    ctx = {
        'primary_role': user.primary_role,
        'active_role': active_role,
        'user_roles': all_role_names,
        'has_multiple_roles': len(all_role_names) >= 2,
        # Role booleans reflect the active role, not all roles
        'is_student': active_role == Role.STUDENT,
        'is_individual_student': active_role == Role.INDIVIDUAL_STUDENT,
        'is_senior_teacher': active_role == Role.SENIOR_TEACHER,
        'is_teacher': active_role == Role.TEACHER,
        'is_junior_teacher': active_role == Role.JUNIOR_TEACHER,
        'is_any_teacher': active_role in (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER),
        'is_hoi': active_role == Role.HEAD_OF_INSTITUTE,
        'is_hod': active_role == Role.HEAD_OF_DEPARTMENT,
        'is_institute_owner': active_role == Role.INSTITUTE_OWNER,
        'is_accountant': active_role == Role.ACCOUNTANT,
        'is_admin_user': active_role == Role.ADMIN,
        'is_parent': active_role == Role.PARENT,
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

    # Pending parent link request count for sidebar badge (HoI/admin/institute owner)
    if ctx['is_hoi'] or ctx['is_institute_owner'] or ctx['is_admin_user'] or ctx['is_hod'] or ctx['is_any_teacher']:
        from classroom.models import ParentLinkRequest, SchoolTeacher
        try:
            schools = SchoolTeacher.objects.filter(
                teacher=request.user, is_active=True
            ).values_list('school_id', flat=True)
            ctx['sidebar_pending_parent_requests'] = ParentLinkRequest.objects.filter(
                school_student__school_id__in=schools,
                status=ParentLinkRequest.STATUS_PENDING,
            ).exclude(parent=user).count()
        except Exception:
            ctx['sidebar_pending_parent_requests'] = 0

    # Add school subscription info for institute users
    from billing.entitlements import get_school_for_user, get_school_subscription, get_all_schools_for_user
    school = get_school_for_user(request.user)
    if school:
        sub = get_school_subscription(school)
        if sub:
            ctx['school_subscription'] = sub
            ctx['school_plan'] = sub.plan
            ctx['school_trial_days_remaining'] = sub.trial_days_remaining

    # Multi-school switcher: list all schools the user belongs to
    all_schools = get_all_schools_for_user(request.user)
    if all_schools.count() > 1:
        ctx['user_schools'] = all_schools
        ctx['current_school'] = school

    # Whether student has any class enrollments (controls sidebar links)
    if active_role in (Role.STUDENT, Role.INDIVIDUAL_STUDENT):
        from classroom.models import ClassStudent
        ctx['student_has_classes'] = ClassStudent.objects.filter(
            student=user, is_active=True,
        ).exists()

    # Trial / promo info for all students (sidebar banner)
    trial_info = {'is_trialing': False, 'is_promo': False, 'days_remaining': 0}
    if active_role in (Role.STUDENT, Role.INDIVIDUAL_STUDENT):
        if active_role == Role.INDIVIDUAL_STUDENT:
            try:
                ind_sub = user.subscription
                if ind_sub and ind_sub.is_promo_activated and ind_sub.trial_end:
                    trial_info = {
                        'is_trialing': False,
                        'is_promo': True,
                        'days_remaining': ind_sub.access_days_remaining,
                    }
                elif ind_sub and ind_sub.status == 'trialing':
                    trial_info = {'is_trialing': True, 'is_promo': False, 'days_remaining': ind_sub.trial_days_remaining}
            except Exception:
                pass
        else:
            # School student — check school subscription
            from classroom.models import SchoolStudent
            ss = SchoolStudent.objects.filter(student=user, is_active=True).select_related('school').first()
            if ss:
                school_sub = get_school_subscription(ss.school)
                if school_sub and school_sub.status == 'trialing':
                    trial_info = {'is_trialing': True, 'is_promo': False, 'days_remaining': school_sub.trial_days_remaining}
    ctx['trial_info'] = trial_info

    return ctx
