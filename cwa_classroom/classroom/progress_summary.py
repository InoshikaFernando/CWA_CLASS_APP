"""Per-student performance summaries for progress reports + the student dashboard.

Folds cross-app performance (Homework, Worksheets, Maths, Coding) into plain
dicts for the per-class report builder (§12.8) and the dashboard card. The dict
returned by :func:`build_summary` IS the report's ``summary_snapshot`` — the
single source of truth the templates render, so the report and dashboard stay
consistent even as the underlying data changes.

Scoping:
  * Homework and Worksheets are class-scoped (assigned per class). Each supports a
    "summary" mode (completion % + average) or a "selected" mode (specific items
    the staff picked for the class, each shown with this student's score).
  * Maths and Coding are platform-wide per student. Maths can additionally include
    times-table, quiz-topic and basic-facts breakdowns.

Every helper is read-only and tolerant of "no data" (returns zeros / empty lists).
"""

from django.db.models import Max


def _pct(part, whole):
    return round((part / whole) * 100) if whole else 0


# ---------------------------------------------------------------------------
# Homework (class-scoped)
# ---------------------------------------------------------------------------

def homework_section(student, classroom, mode='summary', ids=None):
    """Homework section for ``student`` in ``classroom``.

    ``mode='summary'`` → completion % + average of best-attempt scores over the
    class's published homeworks. ``mode='selected'`` → one row per picked homework
    id with this student's best score (``ids`` = homework PKs chosen for the class).
    """
    from homework.models import Homework, HomeworkSubmission

    if mode == 'selected':
        chosen = list(
            Homework.objects.filter(classroom=classroom, id__in=ids or [])
            .values('id', 'title')
        )
        items = []
        for hw in chosen:
            best = HomeworkSubmission.get_best_submission(
                Homework(id=hw['id']), student,
            )
            items.append({
                'title': hw['title'],
                'attempted': best is not None,
                'pct': best.percentage if best else None,
            })
        return {'mode': 'selected', 'items': items}

    assigned = list(
        Homework.objects.filter(classroom=classroom, published_at__isnull=False)
        .values_list('id', flat=True)
    )
    total = len(assigned)
    best_by_hw = {}
    if total:
        for s in HomeworkSubmission.objects.filter(student=student, homework_id__in=assigned):
            cur = best_by_hw.get(s.homework_id)
            if cur is None or s.points > cur.points:
                best_by_hw[s.homework_id] = s
    completed = len(best_by_hw)
    return {
        'mode': 'summary',
        'assigned': total,
        'completed': completed,
        'completion_pct': _pct(completed, total),
        'average_pct': (
            round(sum(s.percentage for s in best_by_hw.values()) / completed)
            if completed else 0
        ),
    }


# ---------------------------------------------------------------------------
# Worksheets (class-scoped) — mirrors homework
# ---------------------------------------------------------------------------

def worksheet_section(student, classroom, mode='summary', ids=None):
    """Worksheet section for ``student`` in ``classroom`` (see :func:`homework_section`).

    ``ids`` in selected mode are ``WorksheetAssignment`` PKs picked for the class.
    """
    from worksheets.models import WorksheetAssignment, WorksheetSubmission

    if mode == 'selected':
        chosen = list(
            WorksheetAssignment.objects.filter(classroom=classroom, id__in=ids or [])
            .select_related('worksheet')
        )
        sub_by_assignment = {
            sub.assignment_id: sub
            for sub in WorksheetSubmission.objects.filter(
                student=student, assignment_id__in=[a.id for a in chosen],
            )
        }
        items = []
        for a in chosen:
            sub = sub_by_assignment.get(a.id)
            items.append({
                'title': a.worksheet.name,
                'attempted': sub is not None and sub.is_complete,
                'pct': sub.percentage if (sub and sub.is_complete) else None,
            })
        return {'mode': 'selected', 'items': items}

    assigned = list(
        WorksheetAssignment.objects.filter(classroom=classroom, is_active=True)
        .values_list('id', flat=True)
    )
    total = len(assigned)
    subs = {
        sub.assignment_id: sub
        for sub in WorksheetSubmission.objects.filter(
            student=student, assignment_id__in=assigned, completed_at__isnull=False,
        )
    }
    completed = len(subs)
    return {
        'mode': 'summary',
        'assigned': total,
        'completed': completed,
        'completion_pct': _pct(completed, total),
        'average_pct': (
            round(sum(s.percentage for s in subs.values()) / completed)
            if completed else 0
        ),
    }


# ---------------------------------------------------------------------------
# Maths (platform-wide) — summary numbers + optional breakdowns
# ---------------------------------------------------------------------------

def _maths_times_tables(student):
    """Best multiplication / division % per times-table the student attempted."""
    from maths.models import StudentFinalAnswer

    best = {}  # table -> {op: (points, pct)}
    for r in StudentFinalAnswer.objects.filter(
        student=student, quiz_type='times_table', table_number__isnull=False,
    ).values('table_number', 'operation', 'score', 'total_questions', 'points'):
        slot = best.setdefault(r['table_number'], {})
        op = r['operation'] or ''
        pct = _pct(r['score'], r['total_questions'])
        if op not in slot or r['points'] > slot[op][0]:
            slot[op] = (r['points'], pct)
    return [
        {
            'table': t,
            'multiplication_pct': best[t].get('multiplication', (0, None))[1],
            'division_pct': best[t].get('division', (0, None))[1],
        }
        for t in sorted(best)
    ]


def _maths_topics(student):
    """Best % per maths quiz topic (topic / mixed quizzes)."""
    from maths.models import StudentFinalAnswer

    best = {}  # topic_id -> (points, pct, name)
    for r in StudentFinalAnswer.objects.filter(
        student=student, quiz_type__in=['topic', 'mixed'],
    ).values('topic_id', 'topic__name', 'score', 'total_questions', 'points'):
        pct = _pct(r['score'], r['total_questions'])
        name = r['topic__name'] or 'Mixed'
        cur = best.get(r['topic_id'])
        if cur is None or r['points'] > cur[0]:
            best[r['topic_id']] = (r['points'], pct, name)
    return [
        {'name': v[2], 'best_pct': v[1]}
        for v in sorted(best.values(), key=lambda x: (-x[1], x[2] or ''))
    ]


def _maths_basic_facts(student):
    """Best % per Basic-Facts subtopic (across levels)."""
    from maths.models import BasicFactsResult

    labels = {'PlaceValue': 'Place Value'}
    best = {}  # subtopic -> (points, pct)
    for r in BasicFactsResult.objects.filter(student=student).values(
        'subtopic', 'score', 'total_points', 'points',
    ):
        pct = _pct(r['score'], r['total_points'])
        cur = best.get(r['subtopic'])
        if cur is None or r['points'] > cur[0]:
            best[r['subtopic']] = (r['points'], pct)
    return [
        {'subtopic': labels.get(st, st), 'best_pct': v[1]}
        for st, v in sorted(best.items())
    ]


def maths_summary(student, *, times_tables=False, topics=False, basic_facts=False):
    """Platform-wide Maths performance, plus any breakdowns the staff ticked."""
    from maths.models import StudentFinalAnswer, BasicFactsResult

    best = {}  # (topic, level) -> (points, pct)
    for a in StudentFinalAnswer.objects.filter(student=student).values(
        'topic_id', 'level_id', 'points', 'score', 'total_questions',
    ):
        key = (a['topic_id'], a['level_id'])
        pct = _pct(a['score'], a['total_questions'])
        if key not in best or a['points'] > best[key][0]:
            best[key] = (a['points'], pct)

    topics_attempted = len(best)
    out = {
        'topics_attempted': topics_attempted,
        'average_pct': (
            round(sum(p for _, p in best.values()) / topics_attempted)
            if topics_attempted else 0
        ),
        'basic_facts_levels': (
            BasicFactsResult.objects.filter(student=student)
            .values('subtopic', 'level_number').distinct().count()
        ),
    }
    if times_tables:
        out['times_tables'] = _maths_times_tables(student)
    if topics:
        out['topics'] = _maths_topics(student)
    if basic_facts:
        out['basic_facts'] = _maths_basic_facts(student)
    return out


# ---------------------------------------------------------------------------
# Coding (platform-wide)
# ---------------------------------------------------------------------------

def coding_section(student, mode='summary', language_ids=None):
    """Coding section for ``student``.

    ``mode='summary'`` → distinct exercises completed + algorithm problems solved.
    ``mode='selected'`` → for each picked language (``language_ids`` = CodingLanguage
    PKs), per-topic exercise completion (% of the topic's exercises this student has
    completed).
    """
    from coding.models import (
        StudentExerciseSubmission, StudentProblemSubmission,
        CodingLanguage, CodingExercise,
    )

    if mode == 'selected':
        completed = set(
            StudentExerciseSubmission.objects.filter(student=student, is_completed=True)
            .values_list('exercise_id', flat=True)
        )
        # exercise_id -> topic_id, for every exercise in the picked languages.
        ex_topic = list(
            CodingExercise.objects.filter(
                topic_level__topic__language_id__in=language_ids or [],
            ).values_list('id', 'topic_level__topic_id')
        )
        totals = {}  # topic_id -> [total, done]
        for ex_id, topic_id in ex_topic:
            t = totals.setdefault(topic_id, [0, 0])
            t[0] += 1
            if ex_id in completed:
                t[1] += 1

        languages = []
        for lang in CodingLanguage.objects.filter(
            id__in=language_ids or [],
        ).prefetch_related('topics').order_by('order', 'name'):
            topics = [
                {
                    'name': topic.name,
                    'completed': totals[topic.id][1],
                    'total': totals[topic.id][0],
                    'pct': _pct(totals[topic.id][1], totals[topic.id][0]),
                }
                for topic in lang.topics.all()
                if totals.get(topic.id, [0])[0]
            ]
            languages.append({'name': lang.name, 'topics': topics})
        return {'mode': 'selected', 'languages': languages}

    return {
        'mode': 'summary',
        'exercises_completed': (
            StudentExerciseSubmission.objects.filter(student=student, is_completed=True)
            .values('exercise_id').distinct().count()
        ),
        'problems_solved': (
            StudentProblemSubmission.objects.filter(student=student, passed_all_tests=True)
            .values('problem_id').distinct().count()
        ),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def build_summary(student, classroom, *,
                  homework=True, homework_mode='summary', homework_ids=None,
                  worksheets=False, worksheet_mode='summary', worksheet_ids=None,
                  maths=True, maths_times_tables=False, maths_topics=False,
                  maths_basic_facts=False,
                  coding=True, coding_mode='summary', coding_language_ids=None):
    """Bundle the selected sections into one snapshot dict.

    Each flag mirrors a staff "include this section" checkbox; an omitted section
    is left out so callers can ``{% if summary.homework %}`` cleanly. Homework and
    Worksheets each take a mode ('summary' | 'selected') and, for 'selected', the
    list of item ids picked for the class.
    """
    out = {}
    if homework and classroom is not None:
        out['homework'] = homework_section(student, classroom, homework_mode, homework_ids)
    if worksheets and classroom is not None:
        out['worksheets'] = worksheet_section(student, classroom, worksheet_mode, worksheet_ids)
    if maths:
        out['maths'] = maths_summary(
            student, times_tables=maths_times_tables,
            topics=maths_topics, basic_facts=maths_basic_facts,
        )
    if coding:
        out['coding'] = coding_section(student, coding_mode, coding_language_ids)
    return out
