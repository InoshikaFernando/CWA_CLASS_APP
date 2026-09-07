"""Who may read a period report (CPP-388).

Kept in its own module because three entry points share the rule — the list
page, the detail page and the PDF download — and a permission check that lives
in one view is a permission check the next view forgets.
"""

from classroom.models import ClassRoom, ParentStudent


def can_view_report(user, report):
    """True when *user* is allowed to read *report*.

    Callers raise 404 rather than 403 on a False: a 403 confirms the report
    exists, which is itself a leak about another family's child.
    """
    return can_view_student(user, report.student, school=report.school)


def can_view_student(user, student, school=None):
    """True when *user* may read *student*'s reports."""
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.id == student.id:
        return True

    if user.is_parent and ParentStudent.objects.filter(
            parent=user, student=student, is_active=True).exists():
        return True

    if user.is_teacher and ClassRoom.objects.filter(
            class_students__student=student,
            class_students__is_active=True,
            class_teachers__teacher=user,
            is_active=True,
    ).exists():
        return True

    if user.is_head_of_institute or user.is_institute_owner:
        # Institute-level staff see their own institute's students only.
        if school is not None:
            return _runs_school(user, school)
        return ClassRoom.objects.filter(
            class_students__student=student,
            class_students__is_active=True,
            school__in=_schools_run_by(user),
        ).exists()

    return False


def _schools_run_by(user):
    from classroom.models import School, SchoolTeacher

    owned = School.objects.filter(admin=user)
    staffed = School.objects.filter(
        id__in=SchoolTeacher.objects.filter(
            teacher=user, is_active=True,
            role__in=['head_of_institute', 'head_of_department'],
        ).values_list('school_id', flat=True)
    )
    return (owned | staffed).distinct()


def _runs_school(user, school):
    return _schools_run_by(user).filter(id=school.id).exists()
