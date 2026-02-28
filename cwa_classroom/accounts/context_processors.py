def user_role(request):
    """Inject primary role and role booleans into every template context."""
    if not request.user.is_authenticated:
        return {}
    return {
        'primary_role': request.user.primary_role,
        'is_student': request.user.is_student,
        'is_individual_student': request.user.is_individual_student,
        'is_teacher': request.user.is_teacher,
        'is_hod': request.user.is_head_of_department,
        'is_accountant': request.user.is_accountant,
        'is_admin_user': request.user.is_admin_user,
    }
