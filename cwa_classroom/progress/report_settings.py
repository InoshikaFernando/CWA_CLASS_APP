"""Resolve which period reports a class actually sends (CPP-388 follow-up).

Reports are **off until switched on**. The cascade mirrors
``classroom.fee_utils``: the most specific rule that says anything wins, and a
chain that says nothing resolves to off.

    ProgressReportSetting(classroom=…)   most specific
    → ProgressReportSetting(department=…)
    → ProgressReportSetting(school=…)
    → off                                the hard default

Every flag resolves independently, so a department can switch weekly reports on
without committing to term reports, and one class can opt back out.
"""

from progress.models import ProgressReportSetting

PERIOD_FIELDS = ProgressReportSetting.PERIOD_FIELDS
DELIVERY_FIELDS = ProgressReportSetting.DELIVERY_FIELDS
DELIVERY_DEFAULTS = ProgressReportSetting.DELIVERY_DEFAULTS

# What a class resolves to when nothing anywhere in its chain says otherwise.
OFF = {field: False for field in PERIOD_FIELDS}


def _chain(classroom):
    """The setting rows for this class, most specific first.

    Rows are fetched individually rather than in one query because the cascade
    is three lookups at most and the alternative — one query plus in-Python
    sorting — hides which level actually won, which the settings page needs to
    display.
    """
    rows = []
    class_row = ProgressReportSetting.objects.filter(classroom=classroom).first()
    if class_row:
        rows.append(('class', class_row))

    if classroom.department_id:
        dept_row = ProgressReportSetting.objects.filter(
            department_id=classroom.department_id, classroom__isnull=True,
        ).first()
        if dept_row:
            rows.append(('department', dept_row))

    if classroom.school_id:
        school_row = ProgressReportSetting.objects.filter(
            school_id=classroom.school_id,
            department__isnull=True, classroom__isnull=True,
        ).first()
        if school_row:
            rows.append(('school', school_row))

    return rows


def resolve(classroom, chain=None):
    """Effective settings for *classroom*, plus where each value came from.

    Returns ``{field: (value, source)}`` where *source* is ``'class'``,
    ``'department'``, ``'school'``, or ``'default'``. The source is not
    decoration — a settings page that shows an inherited value as if it were
    set on the class is how someone turns off the wrong thing.
    """
    rows = _chain(classroom) if chain is None else chain
    resolved = {}

    for field in PERIOD_FIELDS:
        resolved[field] = (False, 'default')
        for source, row in rows:
            value = getattr(row, field)
            if value is not None:
                resolved[field] = (value, source)
                break

    generating = any(resolved[field][0] for field in PERIOD_FIELDS)
    for field in DELIVERY_FIELDS:
        # Delivery only means anything for a class that generates at all.
        default = DELIVERY_DEFAULTS[field] if generating else False
        resolved[field] = (default, 'default')
        for source, row in rows:
            value = getattr(row, field)
            if value is not None:
                resolved[field] = (value, source)
                break

    return resolved


def effective(classroom):
    """Just the values, without the sources — the form the generator wants."""
    return {field: value for field, (value, _source) in resolve(classroom).items()}


def sends(classroom, period_type):
    """Whether *classroom* reports this period type at all."""
    return effective(classroom).get(period_type, False)


def enabled_classrooms(period_type, school=None):
    """Every active class that reports *period_type*.

    Walks only classes that could possibly be enabled — those in a school with
    at least one setting row — so an install where nobody has configured
    anything costs one query and returns nothing.
    """
    from classroom.models import ClassRoom

    configured_schools = set(
        ProgressReportSetting.objects.values_list('school_id', flat=True)
    )
    if not configured_schools:
        return []

    qs = ClassRoom.objects.filter(is_active=True, school_id__in=configured_schools)
    if school is not None:
        qs = qs.filter(school=school)

    return [
        classroom for classroom in qs.select_related('school', 'department')
        if sends(classroom, period_type)
    ]


def set_for(scope_obj, scope_kind, school, values, user=None):
    """Create or update the setting row for one scope.

    *values* maps field name -> ``True`` / ``False`` / ``None`` (inherit). A row
    whose every field is ``None`` is deleted rather than left behind, so the
    cascade never has to step over a row that says nothing.
    """
    lookup = {'school': school, 'department': None, 'classroom': None}
    if scope_kind == 'department':
        lookup['department'] = scope_obj
    elif scope_kind == 'class':
        lookup['classroom'] = scope_obj
        lookup['department'] = scope_obj.department

    row = ProgressReportSetting.objects.filter(
        school=school,
        department=lookup['department'] if scope_kind != 'school' else None,
        classroom=lookup['classroom'],
    ).first()

    if all(value is None for value in values.values()):
        if row is not None:
            row.delete()
        return None

    if row is None:
        row = ProgressReportSetting(
            school=school,
            department=lookup['department'] if scope_kind != 'school' else None,
            classroom=lookup['classroom'],
        )
    for field, value in values.items():
        setattr(row, field, value)
    row.updated_by = user
    row.save()
    return row
