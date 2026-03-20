def user_role(request):
    """Inject primary role, role booleans, and subscription info into every template context."""
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
    }

    # Add school subscription info for institute users
    from billing.entitlements import get_school_for_user, get_school_subscription
    school = get_school_for_user(request.user)
    if school:
        sub = get_school_subscription(school)
        if sub:
            ctx['school_subscription'] = sub
            ctx['school_plan'] = sub.plan
            ctx['school_trial_days_remaining'] = sub.trial_days_remaining

    return ctx
