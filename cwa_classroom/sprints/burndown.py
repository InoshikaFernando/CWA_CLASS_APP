"""Pure burndown-series computation.

Turns a sprint's stored snapshots into the two lines a burndown chart draws —
the *actual* remaining points and the *ideal* straight line from the committed
baseline down to zero across the sprint's calendar days. No Jira / DB IO beyond
the snapshots already passed in, so it's trivially unit-testable.
"""
from datetime import timedelta


def _date_range(start, end):
    """Inclusive list of dates from ``start`` to ``end``."""
    days = (end - start).days
    return [start + timedelta(days=i) for i in range(days + 1)]


def build_burndown_series(sprint):
    """Return chart data for ``sprint`` as a dict of parallel lists.

    Keys:
      ``labels``    — ISO date strings, one per sprint day.
      ``ideal``     — straight line from committed_points to 0.
      ``actual``    — remaining points from each day's snapshot; ``None`` for
                      days with no snapshot yet (Chart.js leaves a gap, so the
                      line stops at "today" rather than diving to zero).
      ``committed`` — the baseline scalar (for the header/legend).

    When the sprint has no start/end dates we fall back to the snapshot dates so
    the chart still renders something useful.
    """
    snapshots = list(sprint.snapshots.all().order_by('snapshot_date'))
    remaining_by_date = {s.snapshot_date: s.remaining_points for s in snapshots}

    if sprint.start_date and sprint.end_date and sprint.end_date >= sprint.start_date:
        dates = _date_range(sprint.start_date, sprint.end_date)
    elif snapshots:
        dates = _date_range(snapshots[0].snapshot_date, snapshots[-1].snapshot_date)
    else:
        dates = []

    committed = float(sprint.committed_points or 0)
    span = len(dates) - 1

    ideal = []
    for i, _ in enumerate(dates):
        if span <= 0:
            ideal.append(committed)
        else:
            ideal.append(round(committed * (1 - i / span), 2))

    actual = [remaining_by_date.get(d) for d in dates]

    return {
        'labels': [d.isoformat() for d in dates],
        'ideal': ideal,
        'actual': actual,
        'committed': committed,
    }
