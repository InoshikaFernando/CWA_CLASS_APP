"""Per-student performance summaries for progress reports + the student dashboard.

Pulls cross-app aggregates (Homework, Maths, Coding) into small plain dicts that
both the per-class progress-report builder (§12.8) and the dashboard summary card
render. Each function returns already-computed primitives — no model objects — so
templates stay dumb and the numbers can be snapshotted onto a report later.

Scoping rules:
  * Homework is scoped to the report's class (homework is assigned per class).
  * Maths and Coding are platform-wide per student — those quizzes / exercises are
    not tied to a class, so a class-scoped figure would be misleading.

Every helper is read-only and tolerant of "no data" (returns zeros, never raises).
"""

from django.db.models import Max


def _pct(part, whole):
    return round((part / whole) * 100) if whole else 0


def homework_summary(student, classroom):
    """Homework completion + average score for ``student`` in ``classroom``.

    "Assigned" = published, non-deleted homeworks for the class (the default
    ``Homework`` manager already hides soft-deleted rows). Completion counts
    homeworks the student has submitted at least once; the average uses each
    attempted homework's *best* submission percentage.
    """
    from homework.models import Homework, HomeworkSubmission

    assigned = list(
        Homework.objects.filter(
            classroom=classroom, published_at__isnull=False,
        ).values_list('id', flat=True)
    )
    total = len(assigned)
    if not total:
        return {'assigned': 0, 'completed': 0, 'completion_pct': 0, 'average_pct': 0}

    subs = HomeworkSubmission.objects.filter(
        student=student, homework_id__in=assigned,
    )
    # Best submission per homework (highest points), computed in one pass.
    best = {}
    for s in subs:
        cur = best.get(s.homework_id)
        if cur is None or s.points > cur.points:
            best[s.homework_id] = s

    completed = len(best)
    average_pct = (
        round(sum(s.percentage for s in best.values()) / completed) if completed else 0
    )
    return {
        'assigned': total,
        'completed': completed,
        'completion_pct': _pct(completed, total),
        'average_pct': average_pct,
    }


def maths_summary(student):
    """Platform-wide Maths performance for ``student``.

    Counts the distinct topic-levels attempted (topic / mixed quizzes) and the
    average of each one's *best* attempt percentage, plus Basic-Facts coverage.
    """
    from maths.models import StudentFinalAnswer, BasicFactsResult

    # Best attempt per (topic, level) — one query, grouped in Python.
    best = {}  # (topic_id, level_id) -> (points, percentage)
    for a in StudentFinalAnswer.objects.filter(student=student).values(
        'topic_id', 'level_id', 'points', 'score', 'total_questions',
    ):
        key = (a['topic_id'], a['level_id'])
        pct = _pct(a['score'], a['total_questions'])
        if key not in best or a['points'] > best[key][0]:
            best[key] = (a['points'], pct)

    topics_attempted = len(best)
    average_pct = (
        round(sum(p for _, p in best.values()) / topics_attempted)
        if topics_attempted else 0
    )

    basic_facts_levels = (
        BasicFactsResult.objects.filter(student=student)
        .values('subtopic', 'level_number').distinct().count()
    )
    return {
        'topics_attempted': topics_attempted,
        'average_pct': average_pct,
        'basic_facts_levels': basic_facts_levels,
    }


def coding_summary(student):
    """Platform-wide Coding performance for ``student``.

    Distinct exercises completed plus distinct algorithm problems solved
    (at least one submission that passed every test).
    """
    from coding.models import StudentExerciseSubmission, StudentProblemSubmission

    exercises_completed = (
        StudentExerciseSubmission.objects.filter(student=student, is_completed=True)
        .values('exercise_id').distinct().count()
    )
    problems_solved = (
        StudentProblemSubmission.objects.filter(student=student, passed_all_tests=True)
        .values('problem_id').distinct().count()
    )
    return {
        'exercises_completed': exercises_completed,
        'problems_solved': problems_solved,
    }


def build_summary(student, classroom, *, homework=True, maths=True, coding=True):
    """Bundle the requested sections into one dict for a report / dashboard card.

    Each flag mirrors a staff "include this section" checkbox; an omitted section
    is left out entirely so callers can ``{% if summary.homework %}`` cleanly.
    """
    out = {}
    if homework and classroom is not None:
        out['homework'] = homework_summary(student, classroom)
    if maths:
        out['maths'] = maths_summary(student)
    if coding:
        out['coding'] = coding_summary(student)
    return out
