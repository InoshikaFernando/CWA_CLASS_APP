"""Awarding points, and reading the global leaderboard.

Everything that gives a student points goes through :func:`award_points`, and
everything that reads a standing goes through :func:`get_student_standing`.
Callers never touch the models directly — that is what keeps "points are
awarded for every kind of work, on one scale" true as new activities are added.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from django.db import transaction
from django.db.models import Sum, Max

from .models import PointsAward, PointsSource, StudentPointsTotal

logger = logging.getLogger(__name__)

# One unit of work — a quiz, a homework, a coding problem, a worksheet, a
# puzzle level, a BrainBuzz session — is worth at most this many points, scored
# on how well the student did it. Every source normalises onto this scale so a
# BrainBuzz session (natively 0–1000 *per question*) cannot outweigh a term of
# homework.
POINTS_PER_UNIT = 100.0

# How many names the podium shows. Country-, school- and class-scoped boards are
# planned; they will reuse everything here with an extra filter on the queryset.
PODIUM_SIZE = 3


def normalise(score, total) -> float:
    """Scale a raw ``score``/``total`` result onto the 0–:data:`POINTS_PER_UNIT` scale.

    Used by the sources that have no points column of their own (worksheets,
    number puzzles) and by BrainBuzz, whose native scale is per-question.
    Returns 0.0 when ``total`` is missing or zero rather than raising — a
    half-built session must not break a student's submission.
    """
    try:
        total = float(total or 0)
        score = float(score or 0)
    except (TypeError, ValueError):
        return 0.0
    if total <= 0:
        return 0.0
    return _clamp(score / total * POINTS_PER_UNIT)


def _clamp(points) -> float:
    try:
        points = float(points or 0)
    except (TypeError, ValueError):
        return 0.0
    return round(min(max(points, 0.0), POINTS_PER_UNIT), 2)


def _is_rankable(student) -> bool:
    """Only students compete on the student leaderboard.

    A teacher who sits a quiz to preview it still earns a ledger row (their own
    progress pages read it), but is flagged out of the board so they cannot
    displace a child from the podium.
    """
    from accounts.models import Role
    return bool(
        student.has_role(Role.STUDENT) or student.has_role(Role.INDIVIDUAL_STUDENT)
    )


@transaction.atomic
def award_points(student, source, unit_key, points, label='') -> float:
    """Record ``points`` for one unit of work and return the student's new total.

    Idempotent and monotonic per unit: calling it again for the same
    ``(student, source, unit_key)`` keeps whichever score is higher, so a
    replayed request, a re-graded homework or a worse second attempt can never
    cost a student points they have already earned.

    ``points`` is clamped to 0–:data:`POINTS_PER_UNIT`; pass a raw
    ``score``/``total`` through :func:`normalise` first if the source has no
    points of its own.
    """
    if student is None or not getattr(student, 'pk', None):
        # Anonymous BrainBuzz players have no account to credit. Not an error.
        return 0.0
    if source not in PointsSource.values:
        # Loud rather than silent: an unknown source means an award site was
        # wired up wrong and that activity is quietly earning nothing.
        raise ValueError(f'Unknown points source {source!r}')

    points = _clamp(points)
    unit_key = str(unit_key)[:120]

    award, created = PointsAward.objects.select_for_update().get_or_create(
        student=student, source=source, unit_key=unit_key,
        defaults={'points': points, 'label': label[:160]},
    )
    if not created:
        changed = []
        if points > award.points:
            award.points = points
            changed.append('points')
        if label and award.label != label[:160]:
            award.label = label[:160]
            changed.append('label')
        if not changed:
            # Nothing improved — still make sure the total row exists and is
            # right, so a student whose totals were never built gets one.
            return recalculate_total(student)
        award.save(update_fields=changed + ['updated_at'])

    return recalculate_total(student)


def recalculate_total(student) -> float:
    """Rebuild a student's denormalised total from their ledger rows.

    Cheap (one aggregate over an indexed per-student set) and always correct,
    which beats incrementing a counter that can drift out of step with the
    ledger it summarises.
    """
    agg = PointsAward.objects.filter(student=student).aggregate(
        total=Sum('points'), last=Max('updated_at'),
    )
    total = round(agg['total'] or 0.0, 2)
    row, _ = StudentPointsTotal.objects.update_or_create(
        student=student,
        defaults={
            'total_points': total,
            'units_completed': PointsAward.objects.filter(student=student).count(),
            'is_ranked': _is_rankable(student),
            'last_earned_at': agg['last'],
        },
    )
    return row.total_points


def award_points_safe(student, source, unit_key, points, label='') -> None:
    """:func:`award_points` that logs instead of raising.

    Used at award sites inside a student's submit path. A student who finished
    their homework must not see a 500 because the leaderboard could not be
    updated — but the failure is logged at ERROR, never swallowed silently, so
    a broken award site shows up in the app log rather than as a leaderboard
    that quietly stops moving.
    """
    try:
        award_points(student, source, unit_key, points, label=label)
    except Exception:
        logger.exception(
            'Failed to award %s points to %s for %s/%s',
            points, getattr(student, 'pk', None), source, unit_key,
        )


# ---------------------------------------------------------------------------
# Reading the board
# ---------------------------------------------------------------------------

def board_queryset():
    """Every ranked student's total, best first.

    The single place the board's population is defined. The planned country /
    school / class boards filter this queryset; nothing else changes.
    """
    return (
        StudentPointsTotal.objects
        .filter(is_ranked=True, total_points__gt=0)
        .select_related('student')
        .order_by('-total_points', 'student_id')
    )


def get_rank(total_points) -> int:
    """Standard competition rank for a score: joint 2nd is followed by 4th."""
    if total_points <= 0:
        return 0
    return board_queryset().filter(total_points__gt=total_points).count() + 1


@dataclass
class Standing:
    """Everything the leaderboard card and pop-up need to render."""

    podium: list = field(default_factory=list)   # [{rank, name, points, is_me}]
    rank: int = 0                                # 0 = not on the board yet
    total_points: float = 0.0
    board_size: int = 0
    points_to_next: float = 0.0                  # to overtake the rank above
    next_rank: int = 0
    message: str = ''

    @property
    def on_podium(self) -> bool:
        return 1 <= self.rank <= PODIUM_SIZE

    @property
    def show_own_rank(self) -> bool:
        """A student already named on the podium does not need a rank line."""
        return self.rank > 0 and not self.on_podium

    @property
    def has_board(self) -> bool:
        return bool(self.podium)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        suffix = 'th'
    else:
        suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')
    return f'{n}{suffix}'


def _message(rank, points_to_next, next_rank, has_points) -> str:
    """The line of encouragement under the board.

    Deliberately never mentions how far *behind* anyone is — only the next step
    up, which is always within reach.
    """
    if not has_points:
        return "Answer a few questions to get on the board — every subject counts!"
    if rank == 1:
        return "You're top of the whole school. Keep up the great work! 🎉"
    gap = max(1, int(round(points_to_next)))
    plural = 'point' if gap == 1 else 'points'
    return f"Just {gap} {plural} to reach {_ordinal(next_rank)} place — keep going! 💪"


def get_student_standing(student) -> Standing:
    """The student's place on the global board, ready to render.

    Three queries: the podium, the rank count, and the score directly above.
    """
    board = board_queryset()

    try:
        mine = StudentPointsTotal.objects.get(student=student)
        my_points = mine.total_points if mine.is_ranked else 0.0
    except StudentPointsTotal.DoesNotExist:
        my_points = 0.0

    podium_rows = list(board[:PODIUM_SIZE])
    podium = [
        {
            'rank': i + 1,
            'name': row.display_name,
            'points': round(row.total_points, 1),
            'is_me': row.student_id == student.pk,
        }
        for i, row in enumerate(podium_rows)
    ]

    rank = get_rank(my_points)
    standing = Standing(
        podium=podium,
        rank=rank,
        total_points=round(my_points, 1),
        board_size=board.count(),
    )

    if rank > 1:
        # The score to beat is the lowest one still above this student — beating
        # it is what actually moves them up, even through a block of ties.
        above = board.filter(total_points__gt=my_points).order_by('total_points').first()
        if above is not None:
            standing.next_rank = get_rank(above.total_points)
            standing.points_to_next = round(above.total_points - my_points, 1)

    standing.message = _message(
        rank, standing.points_to_next, standing.next_rank or 1, my_points > 0,
    )
    return standing


def should_show_daily_popup(student, today) -> bool:
    """True on the student's first hub load of the day.

    Reading it *marks* it shown, so a refresh does not re-open the pop-up. The
    board itself stays on the page all day — this only gates the pop-up.
    """
    row, _ = StudentPointsTotal.objects.get_or_create(
        student=student,
        defaults={'is_ranked': _is_rankable(student)},
    )
    if row.leaderboard_shown_on == today:
        return False
    # update() rather than save(): two tabs opened at once both read "not shown
    # yet", and only the row's single write decides. Worst case the pop-up
    # opens in both tabs — never in tomorrow's session as well.
    StudentPointsTotal.objects.filter(pk=row.pk).update(leaderboard_shown_on=today)
    return True
