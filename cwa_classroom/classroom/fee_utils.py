"""
Fee cascade resolution utilities.

Cascade order (first non-NULL wins):
    ClassStudent.fee_override
    → ClassRoom.fee_override
    → DepartmentLevel.fee_override
    → DepartmentSubject.fee_override
    → Department.default_fee
"""
from decimal import Decimal
from typing import Optional, Tuple


def get_effective_fee_for_student(class_student) -> Optional[Decimal]:
    """
    Resolve the effective fee for a ClassStudent by walking the cascade:
    Student → Class → Level → Subject → Department.

    Returns None if no fee is set anywhere in the chain.
    """
    # 1. Student-level override
    if class_student.fee_override is not None:
        return class_student.fee_override

    return get_effective_fee_for_class(class_student.classroom)


def get_effective_fee_for_class(classroom) -> Optional[Decimal]:
    """
    Resolve the effective fee for a ClassRoom (ignoring per-student overrides).
    Walks: Class → Level → Subject → Department.
    """
    # 2. Class-level override
    if classroom.fee_override is not None:
        return classroom.fee_override

    if not classroom.department_id:
        return None

    from .models import DepartmentLevel, DepartmentSubject

    # 3. Level-level override
    level_ids = list(classroom.levels.values_list('id', flat=True))
    if level_ids:
        dl = DepartmentLevel.objects.filter(
            department_id=classroom.department_id,
            level_id__in=level_ids,
            fee_override__isnull=False,
        ).first()
        if dl:
            return dl.fee_override

    # 4. Subject-level override
    if classroom.subject_id:
        ds = DepartmentSubject.objects.filter(
            department_id=classroom.department_id,
            subject_id=classroom.subject_id,
        ).first()
        if ds and ds.fee_override is not None:
            return ds.fee_override

    # 5. Department default
    if classroom.department and classroom.department.default_fee is not None:
        return classroom.department.default_fee

    return None


def get_fee_source_label(class_student) -> str:
    """
    Return a human-readable label indicating where the effective fee came from.
    E.g. 'Student override', 'Class override', 'Level: Beginner',
         'Subject: Guitar', 'Department default'.
    """
    if class_student.fee_override is not None:
        return 'Student override'

    return _get_class_fee_source(class_student.classroom)


def _get_class_fee_source(classroom) -> str:
    """Return the fee source label for a classroom (no student level)."""
    if classroom.fee_override is not None:
        return 'Class override'

    if not classroom.department_id:
        return 'No fee set'

    from .models import DepartmentLevel, DepartmentSubject

    level_ids = list(classroom.levels.values_list('id', flat=True))
    if level_ids:
        dl = DepartmentLevel.objects.filter(
            department_id=classroom.department_id,
            level_id__in=level_ids,
            fee_override__isnull=False,
        ).select_related('level').first()
        if dl:
            return f'Level: {dl.level.display_name}'

    if classroom.subject_id:
        ds = DepartmentSubject.objects.filter(
            department_id=classroom.department_id,
            subject_id=classroom.subject_id,
        ).select_related('subject').first()
        if ds and ds.fee_override is not None:
            return f'Subject: {ds.subject.name}'

    if classroom.department and classroom.department.default_fee is not None:
        return 'Department default'

    return 'No fee set'


def get_parent_fee_for_subject(department) -> Tuple[Optional[Decimal], str]:
    """
    For a DepartmentSubject, the parent is the Department.
    Returns (fee_amount, source_label).
    """
    if department.default_fee is not None:
        return department.default_fee, 'Department default'
    return None, 'No fee set'


def get_parent_fee_for_level(dept_level) -> Tuple[Optional[Decimal], str]:
    """
    For a DepartmentLevel, walk up: Subject → Department.
    Returns (fee_amount, source_label).
    """
    from .models import DepartmentSubject

    # Check if the level's subject has a fee override in this department
    if dept_level.level.subject_id:
        ds = DepartmentSubject.objects.filter(
            department_id=dept_level.department_id,
            subject_id=dept_level.level.subject_id,
        ).select_related('subject').first()
        if ds and ds.fee_override is not None:
            return ds.fee_override, f'Subject: {ds.subject.name}'

    # Fall back to department default
    dept = dept_level.department
    if dept.default_fee is not None:
        return dept.default_fee, 'Department default'

    return None, 'No fee set'


def get_parent_fee_for_class(classroom) -> Tuple[Optional[Decimal], str]:
    """
    For a ClassRoom, walk up: Level → Subject → Department.
    Returns (fee_amount, source_label) — what the class would inherit.
    """
    if not classroom.department_id:
        return None, 'No fee set'

    from .models import DepartmentLevel, DepartmentSubject

    # Level override
    level_ids = list(classroom.levels.values_list('id', flat=True))
    if level_ids:
        dl = DepartmentLevel.objects.filter(
            department_id=classroom.department_id,
            level_id__in=level_ids,
            fee_override__isnull=False,
        ).select_related('level').first()
        if dl:
            return dl.fee_override, f'Level: {dl.level.display_name}'

    # Subject override
    if classroom.subject_id:
        ds = DepartmentSubject.objects.filter(
            department_id=classroom.department_id,
            subject_id=classroom.subject_id,
        ).select_related('subject').first()
        if ds and ds.fee_override is not None:
            return ds.fee_override, f'Subject: {ds.subject.name}'

    # Department default
    if classroom.department and classroom.department.default_fee is not None:
        return classroom.department.default_fee, 'Department default'

    return None, 'No fee set'
