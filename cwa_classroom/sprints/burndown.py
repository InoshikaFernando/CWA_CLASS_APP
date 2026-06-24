"""Pure burndown-series computation.

Turns a sprint's stored snapshots into the two lines a burndown chart draws —
the *actual* remaining points and the *ideal* straight line from the committed
baseline down to zero across the sprint. No Jira / DB IO beyond the snapshots
already passed in, so it's trivially unit-testable.
"""
from datetime import timedelta


def _date_range(start, end):
    """Inclusive list of dates from ``start`` to ``end``."""
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def build_burndown_series(sprint):
    """Return chart data for ``sprint`` as a dict of parallel lists.

    Keys:
      ``labels``    — ISO date strings, one per day on the axis.
      ``ideal``     — straight line from committed_points to 0, anchored to the
                      sprint's start/end dates and clamped to [0, committed].
      ``actual``    — remaining points from each day's snapshot; ``None`` for
                      days with no snapshot (Chart.js leaves a gap, so the line
                      stops at the last recorded day rather than diving to zero).
      ``committed`` — the baseline scalar (for the header/legend).

    The axis spans the union of the sprint's [start, end] dates and every
    snapshot date, so a snapshot taken before the start or after the end (e.g. a
    sync past sprint close) is never silently dropped from the chart.
    """
    snapshots = list(sprint.snapshots.all().order_by('snapshot_date'))
    remaining_by_date = {s.snapshot_date: s.remaining_points for s in snapshots}

    bounds = []
    if sprint.start_date:
        bounds.append(sprint.start_date)
    if sprint.end_date:
        bounds.append(sprint.end_date)
    bounds.extend(remaining_by_date)

    dates = _date_range(min(bounds), max(bounds)) if bounds else []
    committed = float(sprint.committed_points or 0)

    ideal = []
    if sprint.start_date and sprint.end_date and sprint.end_date > sprint.start_date:
        # Anchor the ideal line to the real sprint window: full at the start,
        # zero at the end, clamped flat outside it.
        total_days = (sprint.end_date - sprint.start_date).days
        for d in dates:
            elapsed = (d - sprint.start_date).days
            ideal.append(round(max(0.0, min(committed, committed * (1 - elapsed / total_days))), 2))
    else:
        # No usable sprint window — fall back to a linear line across the axis.
        span = len(dates) - 1
        for i in range(len(dates)):
            ideal.append(committed if span <= 0 else round(committed * (1 - i / span), 2))

    actual = [remaining_by_date.get(d) for d in dates]

    return {
        'labels': [d.isoformat() for d in dates],
        'ideal': ideal,
        'actual': actual,
        'committed': committed,
    }


def build_project_series(snapshots):
    """Return whole-project chart data from ordered :class:`ProjectSnapshot`s.

    A project has no fixed end date or committed baseline, so there's no ideal
    line — we plot the actual *remaining* points over time (the burndown) plus
    *total scope* (remaining + completed) so scope growth is visible.

    Keys: ``labels`` (ISO dates), ``remaining``, ``total``, ``open_counts``.
    """
    snaps = list(snapshots)
    return {
        'labels': [s.snapshot_date.isoformat() for s in snaps],
        'remaining': [s.remaining_points for s in snaps],
        'total': [s.total_points for s in snaps],
        'open_counts': [s.open_issue_count for s in snaps],
    }


def reconstruct_project_history(issues, today):
    """Reconstruct daily project burndown points from issue dates.

    ``issues`` is an iterable of dicts: ``created`` (date), ``resolved``
    (date or None), ``points`` (float). Returns one dict per day from the
    earliest created date through ``today``::

        {date, remaining, completed, total, open_count}

    For day D: ``total`` = points of issues created on/before D (scope as of D);
    ``completed`` = points of issues resolved on/before D; ``remaining`` =
    total - completed. This replays history from when issues were opened/closed,
    so the burndown extends into the past instead of only from the first sync.

    Approximation: it uses each issue's *current* story points for all of
    history (Jira doesn't expose point-value history) and ignores reopens.
    """
    issues = [i for i in issues if i.get('created')]
    if not issues:
        return []

    start = min(i['created'] for i in issues)
    span = (today - start).days
    rows = []
    for n in range(span + 1):
        d = start + timedelta(days=n)
        total = completed = 0.0
        open_count = 0
        for i in issues:
            if i['created'] > d:
                continue
            pts = i['points']
            total += pts
            resolved = i.get('resolved')
            if resolved is not None and resolved <= d:
                completed += pts
            else:
                open_count += 1
        rows.append({
            'date': d,
            'remaining': total - completed,
            'completed': completed,
            'total': total,
            'open_count': open_count,
        })
    return rows
