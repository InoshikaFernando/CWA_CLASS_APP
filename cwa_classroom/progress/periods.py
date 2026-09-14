"""Period windows for the end-of-period reports (CPP-388).

Pure date arithmetic plus the school lookup a term window needs. Kept separate
from ``progress.reports`` so "which window" and "what happened in it" can be
tested independently — the window maths is where the off-by-one bugs live.
"""

from calendar import monthrange
from datetime import timedelta

from progress.models import PeriodReport

# Re-exported so callers do not have to import the model for a string constant.
WEEKLY = PeriodReport.PERIOD_WEEKLY
MONTHLY = PeriodReport.PERIOD_MONTHLY
TERM = PeriodReport.PERIOD_TERM

# Re-exported for the same reason as the period constants: callers should not
# have to import the settings model to name a mode.
from progress.models import ProgressReportSetting as _Setting  # noqa: E402

MODE_MANUAL = _Setting.MODE_MANUAL
MODE_AUTO = _Setting.MODE_AUTO


def week_window(day):
    """The Monday→Sunday week containing *day*."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


def month_window(day):
    """The 1st→last-day month containing *day*."""
    start = day.replace(day=1)
    return start, day.replace(day=monthrange(day.year, day.month)[1])


def previous_week(reference):
    """The week that closed most recently before *reference*."""
    return week_window(reference - timedelta(days=7))


def previous_month(reference):
    """The month that closed most recently before *reference*."""
    first_of_this = reference.replace(day=1)
    return month_window(first_of_this - timedelta(days=1))


def label_for(period_type, start, end, term=None, partial=False):
    """Reader-facing label for a window, e.g. "Week of 17 Aug 2026".

    *partial* marks a window that has not closed yet — a term still running,
    reported as far as today (CPP-425). It is said in the label rather than
    only in the page around it, because the label travels: it is stored in the
    snapshot, printed on the PDF and used as the email subject, and a partial
    term that reads exactly like a finished one is how a half-term average gets
    quoted back to a parent as the final word.
    """
    if period_type == WEEKLY:
        return f'Week of {start:%d %b %Y}'
    if period_type == MONTHLY:
        return f'{start:%B %Y}'
    if term is not None:
        year = f' {term.academic_year.year}' if term.academic_year_id else ''
        suffix = ' (to date)' if partial else ''
        return f'{term.name}{year}{suffix}'
    return f'{start:%d %b %Y} – {end:%d %b %Y}'


def student_school(student):
    """The school a student belongs to, or ``None`` for an individual learner.

    Cascades: active class membership first (it is the most specific and the
    one homework is actually assigned through), then the school-student link.
    Returning ``None`` is a real answer, not a failure — individual learners
    still get weekly and monthly reports.
    """
    from classroom.models import ClassStudent, SchoolStudent

    membership = (
        ClassStudent.objects
        .filter(student=student, is_active=True, classroom__school__isnull=False)
        .select_related('classroom__school')
        .order_by('-joined_at')
        .first()
    )
    if membership:
        return membership.classroom.school

    link = (
        SchoolStudent.objects
        .filter(student=student, is_active=True)
        .select_related('school')
        .order_by('-id')
        .first()
    )
    return link.school if link else None


# How far after a term ends a school may still schedule its report. The
# per-class setting decides the exact day; this only bounds how many terms the
# daily tick has to consider, so a stale term from last year is never re-offered.
MAX_TERM_OFFSET_DAYS = 60


def terms_recently_ended(day):
    """Terms that ended recently enough for their report to still be due.

    A term report never fires on the term's last day — the last day's
    submissions would be racing the tick — so this starts from the day after.
    Which day inside the window a given class actually sends on is the
    ``send_term_after_days`` setting's business, not this function's.
    """
    from classroom.models import Term

    return Term.objects.filter(
        end_date__lt=day,
        end_date__gte=day - timedelta(days=MAX_TERM_OFFSET_DAYS),
    ).select_related('school', 'academic_year')


def due_periods(reference):
    """Which period windows closed such that *reference* is their report day.

    Returns a list of ``(period_type, start, end, term_or_None)``. Weekly fires
    on Mondays, monthly on the 1st, term on the day after a term's end date —
    so a daily cron needs no calendar logic of its own, and a run on any other
    day is a legitimate no-op rather than a mistake.
    """
    due = []
    # The weekly and monthly windows are always offered; which day a school
    # actually sends on is its own setting, checked per class further down the
    # chain. Filtering here would hard-code Monday and the 1st for everyone.
    start, end = previous_week(reference)
    due.append((WEEKLY, start, end, None))
    start, end = previous_month(reference)
    due.append((MONTHLY, start, end, None))
    # Every recently-ended term is offered; the per-class schedule decides
    # which of them actually sends today. Weekly and monthly work the same way
    # — the window is offered, the setting picks the day.
    for term in terms_recently_ended(reference):
        due.append((TERM, term.start_date, term.end_date, term))
    return due


def window_for(period_type, reference, term=None):
    """The window a caller means when they ask for one period type explicitly.

    Used by ``--period weekly`` on the management command: it reports the last
    *closed* window relative to *reference*, whatever day of the week it is run.
    """
    if period_type == WEEKLY:
        return previous_week(reference)
    if period_type == MONTHLY:
        return previous_month(reference)
    if term is not None:
        return term.start_date, term.end_date
    raise ValueError(f'A {TERM} window needs a term')


def most_recent_ended_terms(reference):
    """Terms that have already ended, most recent first, one per school.

    ``--period term`` outside the day-after-end window still has to mean
    something; this is the term a human would mean by "the term that just
    finished" for each school.
    """
    from classroom.models import Term

    seen = set()
    picked = []
    ended = (
        Term.objects.filter(end_date__lt=reference)
        .select_related('school', 'academic_year')
        .order_by('school_id', '-end_date')
    )
    for term in ended:
        if term.school_id in seen:
            continue
        seen.add(term.school_id)
        picked.append(term)
    return picked


def reviewable_terms(school, reference):
    """Every term of *school* that has begun, most recent first.

    What staff may *look at*, which is a wider set than what the generator
    sends: CPP-388 only ever resolved "the term that just finished", so a
    school in the middle of its first term had nothing to open at all, and a
    teacher mid-term could not see how a class was tracking.

    A term that has not started yet is left out — there is nothing in it.
    """
    from classroom.models import Term

    if school is None:
        return []
    return list(
        Term.objects
        .filter(school=school, start_date__lte=reference)
        .select_related('school', 'academic_year')
        .order_by('-start_date', '-end_date')
    )


def term_in_progress(term, reference):
    """Whether *term* is still running on *reference*."""
    if term is None:
        return False
    return term.start_date <= reference <= term.end_date


def term_window(term, reference):
    """``(start, end, partial)`` for one term, as at *reference*.

    A finished term reports its own dates. A term still running reports from
    its start to **today**, not to its end date: a window that runs into the
    future would divide this term's work by a term's worth of homework and
    report every child as behind.
    """
    if term is None:
        return None, None, False
    if term_in_progress(term, reference):
        return term.start_date, reference, True
    return term.start_date, term.end_date, False


def default_term(terms, reference):
    """Which term the preview opens on, given :func:`reviewable_terms`.

    The term that has just finished, because that is the one a school is about
    to send and the one this page has always shown. Only when there is no
    finished term does it fall back to the one running — that school used to
    get a dead end reading "no term has ended yet", which is true and useless.
    """
    ended = [term for term in terms if term.end_date < reference]
    if ended:
        return ended[0]
    return terms[0] if terms else None


def is_valid_period(period_type):
    return period_type in (WEEKLY, MONTHLY, TERM)


def today():
    """Local "today" — wrapped so tests can freeze it in one place."""
    from django.utils import timezone

    return timezone.localdate()


__all__ = [
    'WEEKLY', 'MONTHLY', 'TERM',
    'week_window', 'month_window', 'previous_week', 'previous_month',
    'label_for', 'student_school', 'terms_recently_ended', 'due_periods',
    'window_for', 'most_recent_ended_terms', 'is_valid_period', 'today',
    'reviewable_terms', 'term_in_progress', 'term_window', 'default_term',
    'MODE_MANUAL', 'MODE_AUTO',
]
