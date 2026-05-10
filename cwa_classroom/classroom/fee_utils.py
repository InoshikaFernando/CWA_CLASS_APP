"""
Fee cascade resolution utilities.

Cascade order (first non-NULL wins):
    StudentFeeOverride (school-wide, most recent effective_from <= as_of)
    → ClassStudent.fee_override
    → ClassRoom.fee_override
    → DepartmentLevel.fee_override
    → DepartmentSubject.fee_override
    → Department.default_fee
    → School.default_fee
"""
from datetime import date as _date_cls
from decimal import Decimal
from typing import Optional, Tuple


def _get_student_fee_override(class_student, as_of=None):
    """Return the most recent StudentFeeOverride for this student+school
    with effective_from <= as_of (defaults to today), or None.
    """
    classroom = class_student.classroom
    if not classroom.school_id:
        return None
    if as_of is None:
        as_of = _date_cls.today()

    from .models import StudentFeeOverride
    return (
        StudentFeeOverride.objects
        .filter(
            student_id=class_student.student_id,
            school_id=classroom.school_id,
            effective_from__lte=as_of,
        )
        .order_by('-effective_from', '-created_at')
        .first()
    )


def get_effective_fee_for_student(class_student, as_of=None) -> Optional[Decimal]:
    """
    Resolve the effective fee for a ClassStudent by walking the cascade:
    StudentFeeOverride → Student → Class → Level → Subject → Department.

    Returns None if no fee is set anywhere in the chain.

    `as_of` (date): the date to use when selecting the active StudentFeeOverride.
    Defaults to today. Pass a billing_period_end for historical invoice calculation.
    """
    # 0. School-wide StudentFeeOverride (date-aware)
    sfo = _get_student_fee_override(class_student, as_of=as_of)
    if sfo is not None:
        return sfo.daily_rate

    # 1. Per-class student override (0 is treated as "no override" — use inherited fee)
    if class_student.fee_override:
        return class_student.fee_override

    return get_effective_fee_for_class(class_student.classroom)


def get_effective_fee_for_class(classroom) -> Optional[Decimal]:
    """
    Resolve the effective fee for a ClassRoom (ignoring per-student overrides).
    Walks: Class → Level → Subject → Department → School.
    """
    # 2. Class-level override
    if classroom.fee_override is not None:
        return classroom.fee_override

    from .models import DepartmentLevel, DepartmentSubject

    if classroom.department_id:
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

    # 6. School default
    if classroom.school_id and classroom.school.default_fee is not None:
        return classroom.school.default_fee

    return None


def get_fee_source_label(class_student, as_of=None) -> str:
    """
    Return a human-readable label indicating where the effective fee came from.
    E.g. 'Student override (school)', 'Student override', 'Class override',
         'Level: Beginner', 'Subject: Guitar', 'Department default'.
    """
    sfo = _get_student_fee_override(class_student, as_of=as_of)
    if sfo is not None:
        return 'Student override (school)'

    if class_student.fee_override:
        return 'Student override'

    return _get_class_fee_source(class_student.classroom)


def _get_class_fee_source(classroom) -> str:
    """Return the fee source label for a classroom (no student level)."""
    if classroom.fee_override is not None:
        return 'Class override'

    from .models import DepartmentLevel, DepartmentSubject

    if classroom.department_id:
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

    if classroom.school_id and classroom.school.default_fee is not None:
        return 'School default'

    return 'No fee set'


def get_parent_fee_for_subject(department) -> Tuple[Optional[Decimal], str]:
    """
    For a DepartmentSubject, the parent is the Department, then School.
    Returns (fee_amount, source_label).
    """
    if department.default_fee is not None:
        return department.default_fee, 'Department default'
    if department.school_id and department.school.default_fee is not None:
        return department.school.default_fee, 'School default'
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

    # Fall back to department default, then school default
    dept = dept_level.department
    if dept.default_fee is not None:
        return dept.default_fee, 'Department default'
    if dept.school_id and dept.school.default_fee is not None:
        return dept.school.default_fee, 'School default'

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

    # School default
    if classroom.school_id and classroom.school.default_fee is not None:
        return classroom.school.default_fee, 'School default'

    return None, 'No fee set'
