from django.db.models import Subquery, OuterRef


def new_homework_count(request):
    """
    Injects `new_homework_count` — the number of homework assignments that
    are pending (not yet submitted) for the currently logged-in student.

    Returns 0 for unauthenticated users or non-student roles.
    """
    if not request.user.is_authenticated:
        return {'new_homework_count': 0}

    from accounts.models import Role
    user = request.user

    is_student_role = user.roles.filter(
        name__in=[Role.STUDENT, Role.INDIVIDUAL_STUDENT]
    ).exists()
    if not is_student_role:
        return {'new_homework_count': 0}

    from classroom.models import ClassStudent
    from homework.models import Homework, HomeworkSubmission

    class_ids = ClassStudent.objects.filter(
        student=user, is_active=True
    ).values_list('classroom_id', flat=True)

    if not class_ids:
        return {'new_homework_count': 0}

    submitted_ids = HomeworkSubmission.objects.filter(
        student=user,
        homework=OuterRef('pk'),
    )

    count = (
        Homework.objects
        .filter(classroom_id__in=class_ids)
        .exclude(pk__in=Subquery(
            HomeworkSubmission.objects.filter(student=user).values('homework_id')
        ))
        .count()
    )

    return {'new_homework_count': count}
