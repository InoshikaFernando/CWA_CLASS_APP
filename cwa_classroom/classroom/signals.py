from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='classroom.ClassTeacher')
def auto_assign_teacher_to_department(sender, instance, created, **kwargs):
    """
    When a teacher is assigned to a class, ensure they are also
    a member of that class's department (if the class has one).
    """
    if not created:
        return  # Only on new assignments, not updates

    classroom = instance.classroom
    teacher = instance.teacher

    if not classroom.department_id:
        return  # Class has no department — nothing to do

    from .models import DepartmentTeacher

    DepartmentTeacher.objects.get_or_create(
        department_id=classroom.department_id,
        teacher=teacher,
    )
