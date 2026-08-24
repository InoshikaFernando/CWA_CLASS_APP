"""Whether the period-report link is worth showing (CPP-388 follow-up).

Reports are opt-in per school / department / class, so most users have nothing
behind the link. Showing it anyway would put a permanently empty page in the
sidebar of every school that has not switched reports on, which reads as a
broken feature rather than as an unconfigured one.
"""

from accounts.models import Role


def _students_for(user, active_role):
    if active_role == Role.PARENT:
        from classroom.models import ParentStudent

        return list(
            ParentStudent.objects
            .filter(parent=user, is_active=True)
            .values_list('student_id', flat=True)
        )
    return [user.id]


def has_reports_for_sidebar(user, active_role):
    """True when this user has a report to read, or a class that will make one.

    Checks for an existing report first: that is one indexed query, and it is
    the common case once a school is live. Only if there is none does it fall
    through to the cascade, which is the more expensive answer.
    """
    from classroom.models import ClassStudent
    from progress import report_settings
    from progress.models import PeriodReport

    student_ids = _students_for(user, active_role)
    if not student_ids:
        return False

    if PeriodReport.objects.filter(student_id__in=student_ids).exists():
        return True

    classrooms = (
        ClassStudent.objects
        .filter(student_id__in=student_ids, is_active=True)
        .select_related('classroom__school', 'classroom__department')
    )
    for membership in classrooms:
        values = report_settings.effective(membership.classroom)
        if any(values[field] for field in report_settings.PERIOD_FIELDS):
            return True
    return False
