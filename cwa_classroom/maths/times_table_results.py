"""One reading of a student's times-table results, shared by every surface.

Three pages show a student's times tables — the dashboard wall
(``classroom.views``), the picker at ``/maths/times-tables/`` (``quiz.views``)
and the teacher/parent progress summary (``classroom.progress_summary``) — and
until now each worked out "how did this table go" for itself. They had already
drifted in small ways: the wall read the highest-*points* run while the picker
read the highest *score*, so one page could say 100% where another said 92%.
This module is the only copy of that reading, for the same reason
``maths.constants.TIMES_TABLES_BY_YEAR`` is (see the note there — two copies of
a rule is one rule and one lie).

**Latest leads, best follows.** Every surface used to headline the student's
best-ever attempt. A best score only ever goes up, so it answers "what did this
child once do" and never "what can they do now" — the question that started
this whole feature. So the headline number, and the colour, now come from the
**most recent** attempt, with the best kept beside it in small type.

Keeping the best visible is not decoration. Leading with the latest and
*dropping* the best would mean a child with a hard-won dark-green 7× loses it
to one distracted run — punishing the very practice the freshness nudges exist
to encourage. Showing both says the true thing: "you got 70% today; your best
is 100%". Nothing earned is taken away, and the points ledger, which awards
from the best attempt ever made
(``rewards.rebuild_points_ledger._maths_quizzes``), still matches what the page
shows as the best.

Freshness — how long ago that latest attempt was — lives in
``maths.times_table_freshness`` and is attached here so a caller gets the whole
picture in one read.
"""
from __future__ import annotations

from maths import times_table_freshness


def _percentage(attempt):
    """An attempt's score as a percentage, or None when it asked nothing."""
    if not attempt or not attempt.total_questions:
        return None
    return round(attempt.score / attempt.total_questions * 100)


def _pick_best(attempts):
    """The attempt to show as the student's best for one table and operation.

    Preserves the rule the dashboard wall has always applied: prefer the
    best-by-points *shuffled* run when the student has one whose time is under
    2x their best ordered time — shuffle is the real test, so matching that
    pace is the more impressive result — otherwise whichever best exists.
    """
    shuffled = [a for a in attempts if a.shuffled]
    ordered = [a for a in attempts if not a.shuffled]
    best_shuffled = max(shuffled, key=lambda a: a.points, default=None)
    best_ordered = max(ordered, key=lambda a: a.points, default=None)
    if best_shuffled and best_ordered:
        if best_shuffled.time_taken_seconds < best_ordered.time_taken_seconds * 2:
            return best_shuffled
        return best_ordered
    return best_shuffled or best_ordered


def _pick_latest(attempts):
    """The most recent attempt, in-order and shuffled runs considered together.

    They are separate *scores* — shuffle unlocks the green tiers — but either
    one is the child sitting down to this table, and "how are they doing now"
    is answered by whichever they did last. Ties break on the higher id so a
    same-timestamp import is still deterministic.
    """
    return max(attempts, key=lambda a: (a.completed_at, a.pk), default=None)


def results_map(student, now=None):
    """``{(table_number, operation): {...}}`` for every table the student tried.

    One query. Each value carries:

    ``latest``          the most recent attempt (the headline)
    ``best``            the high-water mark (kept in small type beside it)
    ``latest_pct`` /
    ``best_pct``        their scores as percentages, or None
    ``latest_is_best``  True when today's run IS the best — the page then shows
                        one number rather than repeating it as "best: 100%"
    ``freshness``       ``times_table_freshness.describe`` of the latest attempt
    """
    from maths.models import StudentFinalAnswer

    attempts = {}
    rows = StudentFinalAnswer.objects.filter(
        student=student,
        quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
        table_number__isnull=False,
    ).only(
        'table_number', 'operation', 'shuffled', 'score', 'total_questions',
        'points', 'time_taken_seconds', 'completed_at',
    )
    for row in rows:
        # The earliest attempts predate the operation column; they are
        # multiplication runs, the same reading times_table_freshness and
        # progress.reports take.
        operation = row.operation or times_table_freshness.MULTIPLICATION
        attempts.setdefault((row.table_number, operation), []).append(row)

    out = {}
    for key, group in attempts.items():
        latest = _pick_latest(group)
        best = _pick_best(group)
        latest_pct = _percentage(latest)
        best_pct = _percentage(best)
        out[key] = {
            'latest': latest,
            'best': best,
            'latest_pct': latest_pct,
            'best_pct': best_pct,
            # Compared on the attempt, not the percentage: two runs can both
            # score 100% while one was twice as fast, and the page should not
            # claim the slow one matched the record.
            'latest_is_best': bool(latest and best and latest.pk == best.pk),
            'freshness': times_table_freshness.describe(
                latest.completed_at if latest else None, now),
        }
    return out


def per_table(results, table, operation):
    """One (table, operation) entry, or None when it was never attempted."""
    return results.get((table, operation))


def tables_needing_refresh(results):
    """Table numbers with at least one operation due or stale, sorted."""
    return sorted({
        table for (table, _operation), info in results.items()
        if info['freshness']['needs_refresh']
    })


#: The two rows a wall tile carries, in display order, with the symbol each is
#: labelled by. Division came later than multiplication and legacy rows fold
#: into multiplication, so this is also the order they are read in.
WALL_ROWS = (
    (times_table_freshness.MULTIPLICATION, '×'),
    (times_table_freshness.DIVISION, '÷'),
)


def wall_tiles(student, colour_for, tables=range(1, 16), now=None):
    """The times-tables wall, built once for every page that renders it.

    Two views render ``student/dashboard.html`` — ``classroom.views`` and
    ``progress.views`` — and each used to assemble these tiles itself. They had
    already diverged: only one of them grew the freshness nudges, so the same
    wall warned a student on one page and said nothing on the other. Building
    them here means a change lands on both or neither.

    ``colour_for`` is passed in rather than imported so this module does not
    depend on a view; both callers hand it ``classroom.views._tt_colour``, which
    reads the LATEST attempt now — the colour and the date on a row describe the
    same run.
    """
    results = results_map(student, now)
    tiles = []
    for table in tables:
        rows = [
            {
                'symbol': symbol,
                'operation': operation,
                'result': results.get((table, operation)),
                'colour': colour_for(
                    (results.get((table, operation)) or {}).get('latest')),
            }
            for operation, symbol in WALL_ROWS
        ]
        tiles.append({
            'table': table,
            'rows': rows,
            'needs_refresh': any(
                row['result'] and row['result']['freshness']['needs_refresh']
                for row in rows
            ),
        })
    return tiles, tables_needing_refresh(results)
