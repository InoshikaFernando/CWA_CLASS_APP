from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver(post_save, sender='classroom.ClassTeacher')
def auto_assign_teacher_to_department(sender, instance, created, **kwargs):
    """
    When a teacher is assigned to a class:
    1. Ensure they are a member of that class's department (if any).
    2. Auto-grant senior_teacher role if they have no teacher-tier role yet.
    """
    if not created:
        return  # Only on new assignments, not updates

    classroom = instance.classroom
    teacher = instance.teacher

    # ── 1. Department membership ──────────────────────────────────────────────
    if classroom.department_id:
        from .models import DepartmentTeacher
        DepartmentTeacher.objects.get_or_create(
            department_id=classroom.department_id,
            teacher=teacher,
        )

    # ── 2. Auto-grant a teacher-tier role if the user has none ───────────────
    from accounts.models import Role, UserRole
    TEACHER_TIERS = {Role.JUNIOR_TEACHER, Role.TEACHER, Role.SENIOR_TEACHER}
    has_teacher_role = UserRole.objects.filter(
        user=teacher,
        role__name__in=TEACHER_TIERS,
    ).exists()
    if not has_teacher_role:
        # Prefer senior_teacher; fall back to teacher if it isn't seeded yet
        default_role = (
            Role.objects.filter(name=Role.SENIOR_TEACHER).first()
            or Role.objects.filter(name=Role.TEACHER).first()
        )
        if default_role:
            UserRole.objects.get_or_create(user=teacher, role=default_role)


@receiver(post_delete, sender='classroom.ClassTeacher')
def auto_remove_teacher_from_department(sender, instance, **kwargs):
    """
    When a teacher is removed from a class, check if they still teach
    any other classes in that department. If not, remove them from the
    department — unless they are the department head.
    """
    from .models import ClassTeacher, DepartmentTeacher, Department

    classroom = instance.classroom
    teacher = instance.teacher

    if not classroom.department_id:
        return

    # Don't remove the department head
    try:
        dept = Department.objects.get(pk=classroom.department_id)
        if dept.head_id == teacher.id:
            return
    except Department.DoesNotExist:
        return

    # Check if teacher still has any classes in this department
    still_has_classes = ClassTeacher.objects.filter(
        classroom__department_id=classroom.department_id,
        teacher=teacher,
    ).exists()

    if not still_has_classes:
        DepartmentTeacher.objects.filter(
            department_id=classroom.department_id,
            teacher=teacher,
        ).delete()
