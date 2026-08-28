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
from progress.periods import MONTHLY, WEEKLY

PERIOD_FIELDS = ProgressReportSetting.PERIOD_FIELDS
DELIVERY_FIELDS = ProgressReportSetting.DELIVERY_FIELDS
DELIVERY_DEFAULTS = ProgressReportSetting.DELIVERY_DEFAULTS
SCHEDULE_FIELDS = ProgressReportSetting.SCHEDULE_FIELDS
CONTENT_FIELDS = ProgressReportSetting.CONTENT_FIELDS
CONTENT_DEFAULTS = ProgressReportSetting.CONTENT_DEFAULTS
SCHEDULE_DEFAULTS = ProgressReportSetting.SCHEDULE_DEFAULTS
SCHEDULE_FOR_PERIOD = ProgressReportSetting.SCHEDULE_FOR_PERIOD
MODE_MANUAL = ProgressReportSetting.MODE_MANUAL
MODE_AUTO = ProgressReportSetting.MODE_AUTO

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

    # Manual unless someone said automatic. A schedule that starts sending on
    # its own is not something a school should acquire by not noticing.
    resolved['mode'] = (MODE_MANUAL, 'default')
    for source, row in rows:
        if row.mode:
            resolved['mode'] = (row.mode, source)
            break

    for field in SCHEDULE_FIELDS:
        resolved[field] = (SCHEDULE_DEFAULTS[field], 'default')
        for source, row in rows:
            value = getattr(row, field)
            if value is not None:
                resolved[field] = (value, source)
                break

    generating = any(resolved[field][0] for field in PERIOD_FIELDS)

    # Content, unlike the period flags, is opt-out: a school that switched
    # reporting on has asked for the report's contents too. A class that
    # generates nothing resolves them all off so the settings page does not
    # offer choices about a report that will never exist.
    for field in CONTENT_FIELDS:
        default = CONTENT_DEFAULTS[field] if generating else False
        resolved[field] = (default, 'default')
        for source, row in rows:
            value = getattr(row, field)
            if value is not None:
                resolved[field] = (value, source)
                break

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


def is_auto(classroom):
    """Whether this class sends on a schedule rather than on a staff click."""
    return effective(classroom).get('mode') == MODE_AUTO


def scheduled_for(values, period_type, reference, term=None):
    """Whether an automatic run for *period_type* lands on *reference*.

    Weekly fires on a chosen weekday, monthly on a chosen day of the month, and
    a term report a chosen number of days after the term ended. The *window* is
    still the closed one either way — the schedule only decides which day the
    school wants to hear about it, never what the report covers.
    """
    if period_type == WEEKLY:
        return reference.weekday() == values['send_weekly_on']
    if period_type == MONTHLY:
        return reference.day == values['send_monthly_on']
    if term is None or term.end_date is None:
        return False
    return (reference - term.end_date).days == values['send_term_after_days']


def enabled_classrooms(period_type, school=None, mode=None, reference=None,
                       term=None):
    """Every active class that reports *period_type*.

    Walks only classes that could possibly be enabled — those in a school with
    at least one setting row — so an install where nobody has configured
    anything costs one query and returns nothing.

    *mode* filters to manual or automatic classes. *reference* additionally
    keeps only the automatic classes whose schedule actually lands on that
    date, which is what lets one generic daily tick serve every school without
    anybody configuring a cron per school.
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

    picked = []
    for classroom in qs.select_related('school', 'department', 'subject'):
        values = effective(classroom)
        if not values.get(period_type):
            continue
        if mode is not None and values['mode'] != mode:
            continue
        if reference is not None and values['mode'] == MODE_AUTO:
            if not scheduled_for(values, period_type, reference, term=term):
                continue
        picked.append(classroom)
    return picked


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
