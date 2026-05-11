def active_worksheet_count(request):
    """
    Injects `active_worksheet_count` — the number of active worksheet assignments
    with incomplete submissions for the currently logged-in student.

    Returns 0 for unauthenticated users or non-student roles.
    """
    if not request.user.is_authenticated:
        return {'active_worksheet_count': 0}

    from accounts.models import Role
    user = request.user

    is_student_role = user.roles.filter(
        name__in=[Role.STUDENT, Role.INDIVIDUAL_STUDENT]
    ).exists()
    if not is_student_role:
        return {'active_worksheet_count': 0}

    from classroom.models import ClassStudent
    from .models import WorksheetAssignment, WorksheetSubmission

    class_ids = ClassStudent.objects.filter(
        student=user, is_active=True,
    ).values_list('classroom_id', flat=True)

    if not class_ids:
        return {'active_worksheet_count': 0}

    # Active assignments in enrolled classes
    active_assignment_ids = WorksheetAssignment.objects.filter(
        classroom_id__in=class_ids,
        is_active=True,
    ).values_list('pk', flat=True)

    if not active_assignment_ids:
        return {'active_worksheet_count': 0}

    # Completed submissions
    completed_ids = WorksheetSubmission.objects.filter(
        assignment_id__in=active_assignment_ids,
        student=user,
        completed_at__isnull=False,
    ).values_list('assignment_id', flat=True)

    # Count assignments that are active but NOT yet completed
    count = len(set(active_assignment_ids) - set(completed_ids))
    return {'active_worksheet_count': count}
