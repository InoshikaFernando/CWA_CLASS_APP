"""How recently a times table was practised — and when a result stops speaking
for today.

The times-tables wall (``classroom.views.StudentDashboardView``) and the table
picker (``quiz.views.TimesTablesHomeView``) show a student's score per table
and operation with no date on it at all. So a dark-green 7× reads as dark green
months later, and nothing on either page says the child has not multiplied by
seven since. (Both pages now lead with the student's LATEST attempt rather than
their best — see ``maths.times_table_results`` — which makes the score current
but still says nothing about *when*. That is this module's job.)

That is a *display* problem, and this module fixes it as one. It deletes
nothing and it recomputes nothing:

* Expiring (deleting, or ignoring) old attempts would take points off
  students. ``rewards.management.commands.rebuild_points_ledger._maths_quizzes``
  awards times-table points from ``Max('points')`` over every attempt a student
  has, so dropping the best attempt makes the next ledger rebuild quietly lower
  their total — the silent failure CLAUDE.md forbids.
* It would also lose the evidence a parent wants. "Not practised since March"
  is true and useful; showing grey says "never practised", which is false.

So the best result keeps standing, and *freshness* is reported beside it,
derived from ``completed_at`` on the fly. Nothing is stored, so there is no
migration and no backfill: a table's freshness is a fact about today, and it
changes without anything being written.

Freshness is taken from the student's **most recent** attempt, never from their
best one. A child who scored 100% in March and 40% last week has practised
recently; the pass that decides the colour is not the pass that decides whether
the colour is current.

Two thresholds, both in days:

==============  =========================  ================================
State           Since the last attempt     What the page shows
==============  =========================  ================================
``FRESH``       under ``fresh_after_days`` the result as it is
``DUE``         up to ``stale_after_days`` the result, faded, "Due a refresh"
``STALE``       beyond that                the result, washed out, "Needs a refresh"
``NEVER``       no attempt at all          nothing new — the existing grey
==============  =========================  ================================

The defaults are 42 days (six weeks) and 90 days (three months). Six weeks is
the first nudge rather than three, because a table a child is still learning
decays by lack of retrieval long before a term is out; three months is the
point at which the result stops being evidence about now.

Both are overridable in settings (``TIMES_TABLE_FRESH_DAYS``,
``TIMES_TABLE_STALE_DAYS``) but deliberately *default* here rather than being
declared in ``settings.py``: every file in the project package except
``version.py`` is watched by ci.yml's ``shared`` filter, so putting two tuning
constants there would make this change run all 20 unit suites and all 15 UI
groups (see CLAUDE.md § Conventions). Tests use ``override_settings`` exactly
as they would for a settings-declared value.
"""
from __future__ import annotations

from django.conf import settings
from django.utils import timezone
from django.utils.timesince import timesince

#: A result still current enough to stand on its own.
FRESH = 'fresh'
#: Getting old — shown, faded, with a nudge.
DUE = 'due'
#: Old enough that it no longer says anything about today.
STALE = 'stale'
#: Never attempted. Not a staleness state; the pages already show these grey.
NEVER = 'never'

DEFAULT_FRESH_DAYS = 42   # six weeks
DEFAULT_STALE_DAYS = 90   # three months

#: Operation recorded on the earliest times-table attempts, before the column
#: existed. Those rows are multiplication — division came later — and both
#: ``progress.reports.times_tables_section`` and the wall already read them
#: that way, so the map below normalises them rather than dropping them.
LEGACY_OPERATION = ''
MULTIPLICATION = 'multiplication'
DIVISION = 'division'


def fresh_after_days():
    """Days after which a result is shown as due a refresh."""
    return int(getattr(settings, 'TIMES_TABLE_FRESH_DAYS', DEFAULT_FRESH_DAYS))


def stale_after_days():
    """Days after which a result is shown as stale.

    Never less than :func:`fresh_after_days` — a misconfiguration that put
    "stale" before "due" would skip the gentler state entirely and is clamped
    rather than obeyed.
    """
    return max(
        int(getattr(settings, 'TIMES_TABLE_STALE_DAYS', DEFAULT_STALE_DAYS)),
        fresh_after_days(),
    )


def days_since(last_practised, now=None):
    """Whole days between ``last_practised`` and now, or ``None`` if never.

    A future timestamp (clock skew on an imported row) counts as 0 rather than
    a negative age, so it reads as practised today instead of impossibly fresh.
    """
    if last_practised is None:
        return None
    now = now or timezone.now()
    return max(0, (now - last_practised).days)


def state_for(last_practised, now=None):
    """:data:`FRESH` / :data:`DUE` / :data:`STALE` / :data:`NEVER`."""
    days = days_since(last_practised, now)
    if days is None:
        return NEVER
    if days < fresh_after_days():
        return FRESH
    if days < stale_after_days():
        return DUE
    return STALE


def describe(last_practised, now=None):
    """Everything a template needs to render one result's freshness.

    ``wash`` is a Tailwind class the two pages apply to the result's existing
    colour tile, kept here rather than in each template so the wall and the
    picker cannot drift apart — the same reason ``classroom.views._tt_colour``
    returns classes from Python.
    """
    now = now or timezone.now()
    state = state_for(last_practised, now)
    days = days_since(last_practised, now)
    return {
        'state': state,
        'days': days,
        # "3 months", "2 weeks" — one unit is enough for a nudge, and the
        # full "3 months, 1 week" reads as precision nobody asked for.
        'ago': timesince(last_practised, now, depth=1) if last_practised else None,
        'last_practised': last_practised,
        'needs_refresh': state in (DUE, STALE),
        'label': {
            DUE: 'Due a refresh',
            STALE: 'Needs a refresh',
        }.get(state, ''),
        'wash': {
            DUE: 'opacity-75',
            STALE: 'opacity-50 saturate-50',
        }.get(state, ''),
    }


def last_practised_map(student):
    """``{(table_number, operation): datetime}`` — each table's LAST attempt.

    One query for the whole wall. Keyed by the operation the page shows, so
    legacy rows saved with no operation are counted as multiplication (see
    :data:`LEGACY_OPERATION`); where a student has both, the later of the two
    wins, which is what "when did you last do your 7 times tables" means.

    Shuffled and in-order runs are deliberately NOT separate keys. They are
    separate *scores* — shuffle is the real test and unlocks the green tiers —
    but either one is the child sitting down and doing that table, which is
    the only question freshness asks.
    """
    from django.db.models import Max

    from maths.models import StudentFinalAnswer

    latest = {}
    rows = (
        StudentFinalAnswer.objects
        .filter(
            student=student,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
            table_number__isnull=False,
        )
        .values('table_number', 'operation')
        .annotate(last=Max('completed_at'))
    )
    for row in rows:
        operation = row['operation'] or MULTIPLICATION
        key = (row['table_number'], operation)
        if key not in latest or row['last'] > latest[key]:
            latest[key] = row['last']
    return latest


def describe_map(student, now=None):
    """:func:`describe` for every (table, operation) the student has attempted."""
    now = now or timezone.now()
    return {
        key: describe(last, now)
        for key, last in last_practised_map(student).items()
    }


def tables_needing_refresh(freshness_by_key):
    """The table numbers with at least one operation due or stale, sorted.

    Takes the mapping :func:`describe_map` returns so a page that already built
    it does not go back to the database to count.
    """
    return sorted({
        table for (table, _operation), info in freshness_by_key.items()
        if info['needs_refresh']
    })
