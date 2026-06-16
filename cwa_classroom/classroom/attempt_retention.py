"""Shared retention policy for student *attempt* history.

Homework submissions and quiz results are kept per student so that the
student, their teacher and their parent can review past results (and the
questions/answers) later. To stop these tables growing without bound we keep
only the most recent :data:`ATTEMPT_HISTORY_LIMIT` attempts in each series and
prune the rest whenever a new attempt is saved.

The helper here is deliberately model-agnostic and imports nothing from the
Django model layer at module load, so both ``homework`` and ``maths`` can call
it without risking circular imports.
"""

# How many attempts to keep per student per assignment / quiz series.
ATTEMPT_HISTORY_LIMIT = 10


def prune_to_last_n(model, filter_kwargs, keep=ATTEMPT_HISTORY_LIMIT, order_by='-id'):
    """Delete all but the most recent ``keep`` rows of ``model``.

    ``filter_kwargs`` selects the attempt *series* (e.g. one student's
    submissions for one homework). Rows are ordered most-recent-first by
    ``order_by`` and everything past the ``keep``-th row is deleted.

    Returns the number of rows deleted (0 when nothing was pruned).
    """
    stale_ids = list(
        model.objects.filter(**filter_kwargs)
        .order_by(order_by)
        .values_list('pk', flat=True)[keep:]
    )
    if not stale_ids:
        return 0
    deleted, _ = model.objects.filter(pk__in=stale_ids).delete()
    return deleted
