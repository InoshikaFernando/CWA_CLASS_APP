"""Cross-subject student points — the data behind the global leaderboard.

Why a separate ledger instead of summing what the apps already store
--------------------------------------------------------------------
Every activity app keeps its own ``points`` column, and none of them can be
summed into a lifetime total:

* **They are pruned.** ``classroom.attempt_retention.prune_to_last_n`` deletes
  all but the last 10 attempts in a series after every save, so a total summed
  from ``StudentFinalAnswer`` / ``HomeworkSubmission`` *shrinks* the more a
  student practises — exactly backwards.
* **They are not all additive.** ``coding.StudentProblemSubmission.points``
  stores the student's *best so far* on every row, so summing the rows
  multiplies a single success by the attempt count.
* **They are on different scales.** BrainBuzz awards up to 1000 points per
  *question*; everything else caps at 100 per *attempt*.
* **Several activities award nothing at all** — worksheets, number puzzles and
  coding exercises have no points column.

So this app owns one normalised, append-only-ish ledger that every activity
writes through :func:`rewards.services.award_points`.

The unit of account
-------------------
One **unit of work** — a topic quiz, a homework, a coding problem, a worksheet,
a puzzle level, a live BrainBuzz session — is worth up to
:data:`rewards.services.POINTS_PER_UNIT` points, scored on how well the student
did it. A student keeps their **best** result per unit, mirroring the
``Max('points')`` / ``order_by('-points').first()`` semantics every existing
reader in the codebase already uses.

That makes the total grow with *breadth and mastery* rather than with grinding:
re-sitting the same quiz can only ever raise that one unit's score, while a new
topic, homework or problem adds a new unit. It is also stable — replaying a
quiz can never lower a total, and pruning attempt history can never erase one.
"""

from django.conf import settings
from django.db import models


class PointsSource(models.TextChoices):
    """Where a unit of work came from.

    Values are stored in the database, so they are part of the ledger's
    contract — rename the label freely, never the value.
    """

    MATHS_QUIZ = 'maths_quiz', 'Subject quiz'
    BASIC_FACTS = 'basic_facts', 'Basic facts'
    TIMES_TABLES = 'times_tables', 'Times tables'
    HOMEWORK = 'homework', 'Homework'
    CODING_PROBLEM = 'coding_problem', 'Coding problem'
    CODING_EXERCISE = 'coding_exercise', 'Coding exercise'
    WORKSHEET = 'worksheet', 'Worksheet'
    NUMBER_PUZZLE = 'number_puzzle', 'Number puzzle'
    BRAINBUZZ = 'brainbuzz', 'BrainBuzz'


class PointsAward(models.Model):
    """The best points a student has scored on one unit of work.

    One row per ``(student, source, unit_key)``. ``unit_key`` names the unit
    *within* its source (a homework id, a topic+level pair, a coding problem
    id …) and is opaque to everything except the service that writes it.
    """

    student = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='points_awards',
    )
    source = models.CharField(
        max_length=32, choices=PointsSource.choices, db_index=True,
        help_text='Which activity this unit of work belongs to.',
    )
    unit_key = models.CharField(
        max_length=120,
        help_text="Identifies the unit within its source, e.g. a homework id "
                  "or a 'topic:7:level:3' pair. Opaque outside rewards.services.",
    )
    points = models.FloatField(
        default=0.0,
        help_text='Best score on this unit so far, normalised to 0–100.',
    )
    label = models.CharField(
        max_length=160, blank=True,
        help_text='Human-readable name of the unit, for "where did my points '
                  'come from" views. Never used for identity.',
    )
    first_earned_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['student', 'source', 'unit_key'],
                name='rewards_award_unique_unit',
            ),
        ]
        indexes = [
            models.Index(fields=['student', 'source'], name='rewards_award_stu_src_idx'),
        ]
        ordering = ['-points', 'source']

    def __str__(self):
        return f'{self.student} — {self.get_source_display()} {self.unit_key}: {self.points:.1f}'


class StudentPointsTotal(models.Model):
    """One row per student holding their lifetime total.

    Denormalised from :class:`PointsAward` so a rank is a single indexed
    ``COUNT(total_points > mine)`` rather than an aggregate over the whole
    ledger — the leaderboard is read on every hub load, by every student.
    """

    student = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='points_total',
    )
    total_points = models.FloatField(
        default=0.0, db_index=True,
        help_text='Sum of every PointsAward for this student. Indexed — the '
                  'rank query counts rows above this value.',
    )
    units_completed = models.PositiveIntegerField(
        default=0, help_text='How many units of work the student has scored on.',
    )
    is_ranked = models.BooleanField(
        default=True, db_index=True,
        help_text='False for non-students (a teacher trying a quiz), so they '
                  'never appear on or displace anyone from the board.',
    )
    last_earned_at = models.DateTimeField(null=True, blank=True)
    leaderboard_shown_on = models.DateField(
        null=True, blank=True,
        help_text="Local date the standings pop-up was last shown. Gates the "
                  "once-a-day modal; stored here rather than in the session so "
                  "it holds across devices and browsers.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-total_points', 'student_id']
        indexes = [
            models.Index(fields=['is_ranked', '-total_points'], name='rewards_total_board_idx'),
        ]

    def __str__(self):
        return f'{self.student}: {self.total_points:.1f} points'

    @property
    def display_name(self):
        """Board name for this student.

        The board is global — it spans every school and country — so it shows a
        first name and a last initial rather than identifying a child in full to
        strangers. Falls back to the username only when there is no first name.
        """
        first = (self.student.first_name or '').strip()
        last = (self.student.last_name or '').strip()
        if not first:
            return self.student.username
        return f'{first} {last[0]}.' if last else first
