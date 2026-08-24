"""Build the frozen snapshot behind an end-of-period progress report (CPP-388).

Everything here is read-only and returns plain JSON-serialisable dicts, because
what it returns IS ``PeriodReport.data`` — the single source the HTML view and
the PDF both render. See ``docs/specs/CPP-388_period_progress_reports.md``.

Two rules run through the whole module:

* **Nothing is invented.** A period with no submissions reports zeros and an
  empty award list; it never borrows figures from a neighbouring period.
* **Nothing is silently dropped.** Answers whose question carries no topic are
  grouped under "Unclassified" rather than excluded — a denominator that
  quietly shrinks is how a report ends up flattering.
"""

from collections import defaultdict
from datetime import date, datetime, time

from django.utils import timezone

from progress.periods import label_for

UNCLASSIFIED = 'Unclassified'

# An award only means something measured against classmates. Below this many
# active students with activity in the window, the class-relative awards are
# skipped entirely — see the spec's §2.5 guard column.
MIN_COHORT = 2

# "Fast and accurate" is accuracy first: speed without marks is not a virtue.
FAST_ACCURATE_MIN_PCT = 85


def _bounds(start, end):
    """The window as timezone-aware datetimes, end-inclusive to the last second."""
    tz = timezone.get_current_timezone()
    begin = timezone.make_aware(datetime.combine(start, time.min), tz)
    finish = timezone.make_aware(datetime.combine(end, time.max), tz)
    return begin, finish


def _pct(part, whole):
    return round((part / whole) * 100) if whole else 0


def _mean(values):
    return round(sum(values) / len(values)) if values else 0


# ---------------------------------------------------------------------------
# Raw material
# ---------------------------------------------------------------------------

def student_submissions(student, start, end, classroom_ids=None):
    """Every homework attempt this student submitted inside the window.

    *classroom_ids* restricts the report to the classes that actually switched
    reporting on, so enabling one class shows that class's work and nothing
    else. ``None`` means every class the student is in.

    Soft-deleted homework is excluded. Its submissions are kept in the database
    so grades survive a teacher removing an assignment, but the homework itself
    is hidden from every teacher, student and parent view — surfacing it in a
    report would undo that deliberately. ``homework__deleted_at`` is spelled out
    because a related-field lookup joins the table directly and never consults
    ``Homework.objects``, the manager that does the hiding.
    """
    from homework.models import HomeworkSubmission

    begin, finish = _bounds(start, end)
    qs = HomeworkSubmission.objects.filter(
        student=student,
        homework__deleted_at__isnull=True,
        submitted_at__gte=begin,
        submitted_at__lte=finish,
    )
    if classroom_ids is not None:
        qs = qs.filter(homework__classroom_id__in=classroom_ids)
    return list(
        qs.select_related('homework', 'homework__classroom')
        .order_by('submitted_at')
    )


def homework_due_in_window(student, start, end, classroom_ids=None):
    """Published homework whose due date falls in the window, for this student.

    Scoped to the classes the student is actively in — homework assigned to a
    class they left is not theirs to be measured against — and further to
    *classroom_ids* when only some classes report.
    """
    from classroom.models import ClassStudent
    from homework.models import Homework

    begin, finish = _bounds(start, end)
    class_ids = list(
        ClassStudent.objects
        .filter(student=student, is_active=True)
        .values_list('classroom_id', flat=True)
    )
    if classroom_ids is not None:
        class_ids = [cid for cid in class_ids if cid in set(classroom_ids)]
    if not class_ids:
        return []
    return list(
        Homework.objects
        .filter(
            classroom_id__in=class_ids,
            published_at__isnull=False,
            due_date__gte=begin,
            due_date__lte=finish,
        )
        .order_by('due_date')
    )


def _group_by_homework(submissions):
    """``{homework_id: [attempts…]}``, each list ordered by attempt number."""
    grouped = defaultdict(list)
    for sub in submissions:
        grouped[sub.homework_id].append(sub)
    for attempts in grouped.values():
        attempts.sort(key=lambda s: s.attempt_number)
    return grouped


# ---------------------------------------------------------------------------
# Sections
# ---------------------------------------------------------------------------

def totals_section(submissions, due):
    """Headline figures — §2.1 of the spec.

    ``avg_first_pct`` vs ``avg_best_pct`` is the pair that makes retrying
    visibly worth doing, so both are computed over the same set of homework
    (the ones actually attempted in the window) rather than over different
    denominators that would make the gap meaningless.
    """
    grouped = _group_by_homework(submissions)
    first_scores, best_scores = [], []
    for attempts in grouped.values():
        first_scores.append(attempts[0].percentage)
        best_scores.append(max(a.percentage for a in attempts))

    avg_first = _mean(first_scores)
    avg_best = _mean(best_scores)

    due_ids = {hw.id for hw in due}
    completed_due = len(due_ids & set(grouped))

    on_time = 0
    for attempts in grouped.values():
        homework = attempts[0].homework
        if homework.due_date and attempts[0].submitted_at <= homework.due_date:
            on_time += 1

    return {
        'assigned': len(due_ids),
        'completed': completed_due,
        'completion_pct': _pct(completed_due, len(due_ids)),
        'homework_attempted': len(grouped),
        'submissions': len(submissions),
        'avg_first_pct': avg_first,
        'avg_best_pct': avg_best,
        'improvement_pct': avg_best - avg_first,
        'time_minutes': round(sum(s.time_taken_seconds for s in submissions) / 60),
        'on_time_pct': _pct(on_time, len(grouped)),
        'best_single_pct': max(best_scores) if best_scores else 0,
    }


def topics_section(submissions):
    """Accuracy per ``classroom.Topic`` over every answer in the window — §2.2.

    Topics come from the questions the student actually answered, not from the
    homework's topic list: a mixed homework spans several topics, and crediting
    all of them for one right answer would be a lie.
    """
    from homework.models import HomeworkStudentAnswer

    if not submissions:
        return []

    answers = (
        HomeworkStudentAnswer.objects
        .filter(submission_id__in=[s.id for s in submissions])
        .select_related('question__topic')
    )

    tally = defaultdict(lambda: {'answered': 0, 'correct': 0})
    for answer in answers:
        topic = answer.question.topic if answer.question_id else None
        name = topic.name if topic else UNCLASSIFIED
        tally[name]['answered'] += 1
        tally[name]['correct'] += 1 if answer.is_correct else 0

    rows = [
        {
            'topic': name,
            'answered': counts['answered'],
            'correct': counts['correct'],
            'accuracy_pct': _pct(counts['correct'], counts['answered']),
        }
        for name, counts in tally.items()
    ]
    # Weakest first: the point of the chart is to show where the work is.
    rows.sort(key=lambda r: (r['accuracy_pct'], -r['answered']))
    return rows


def attempts_section(submissions):
    """Per-homework attempt history and the retry distribution — §2.3.

    This is the section that exists to motivate the retry, so it always shows
    the first→best gain explicitly rather than leaving the reader to subtract.
    """
    grouped = _group_by_homework(submissions)

    items = []
    distribution = defaultdict(int)
    repeated = 0
    for attempts in grouped.values():
        first = attempts[0]
        best = max(attempts, key=lambda a: a.percentage)
        count = len(attempts)
        bucket = '3+' if count >= 3 else str(count)
        distribution[bucket] += 1
        if count > 1:
            repeated += 1
        items.append({
            'title': first.homework.title,
            'classroom': first.homework.classroom.name if first.homework.classroom_id else '',
            'attempts': count,
            'first_pct': first.percentage,
            'best_pct': best.percentage,
            'gain_pct': best.percentage - first.percentage,
        })

    # Biggest gain first — the reader should meet the payoff before the noise.
    items.sort(key=lambda i: (-i['gain_pct'], -i['attempts'], i['title']))

    order = ['1', '2', '3+']
    return {
        'items': items,
        'distribution': [
            {'label': bucket, 'count': distribution[bucket]}
            for bucket in order if distribution[bucket]
        ],
        'repeated': repeated,
        'repeat_rate_pct': _pct(repeated, len(grouped)),
        'avg_attempts': (
            round(len(submissions) / len(grouped), 1) if grouped else 0
        ),
    }


def trend_section(submissions, period_type):
    """Average best-attempt score over time — §2.4.

    Weekly reports bucket by day; anything longer buckets by ISO week, because
    ninety daily dots is a smear, not a trend.
    """
    from progress.periods import WEEKLY

    if not submissions:
        return []

    by_day = period_type == WEEKLY
    buckets = defaultdict(list)
    for sub in submissions:
        local = timezone.localtime(sub.submitted_at).date()
        if by_day:
            key = (local.toordinal(), f'{local:%a %d %b}')
        else:
            iso = local.isocalendar()
            monday = date.fromordinal(local.toordinal() - local.weekday())
            key = (monday.toordinal(), f'W{iso[1]} · {monday:%d %b}')
        buckets[key].append(sub.percentage)

    return [
        {'label': label, 'avg_pct': _mean(scores)}
        for (_, label), scores in sorted(buckets.items(), key=lambda kv: kv[0][0])
    ]


def worksheets_section(student, start, end, classroom_ids=None):
    """Worksheet completions in the window — the secondary source (§2)."""
    from worksheets.models import WorksheetSubmission

    begin, finish = _bounds(start, end)
    qs = WorksheetSubmission.objects.filter(
        student=student,
        completed_at__isnull=False,
        completed_at__gte=begin,
        completed_at__lte=finish,
    )
    if classroom_ids is not None:
        qs = qs.filter(assignment__classroom_id__in=classroom_ids)
    completed = list(qs.select_related('assignment__worksheet'))
    return {
        'completed': len(completed),
        'average_pct': _mean([s.percentage for s in completed]),
        'items': [
            {
                'title': s.assignment.worksheet.name,
                'pct': s.percentage,
                'score': s.score,
                'total': s.total_questions,
            }
            for s in completed
        ],
    }


# ---------------------------------------------------------------------------
# Recognition
# ---------------------------------------------------------------------------

def cohort_stats(classroom, start, end, cache=None):
    """Per-student figures for every active student in *classroom*.

    Awards are class-relative, so scoring one student needs the same figures for
    everyone they are being compared with. The nightly run walks every student
    in turn, so without *cache* a class of 25 recomputes the identical cohort 25
    times; ``run_period`` passes one dict for the whole run.
    """
    key = (classroom.id, start, end)
    if cache is not None and key in cache:
        return cache[key]
    stats = _compute_cohort_stats(classroom, start, end)
    if cache is not None:
        cache[key] = stats
    return stats


def _compute_cohort_stats(classroom, start, end):
    from classroom.models import ClassStudent
    from homework.models import HomeworkSubmission

    begin, finish = _bounds(start, end)
    student_ids = list(
        ClassStudent.objects
        .filter(classroom=classroom, is_active=True)
        .values_list('student_id', flat=True)
    )
    if not student_ids:
        return {}

    submissions = (
        HomeworkSubmission.objects
        .filter(
            student_id__in=student_ids,
            homework__classroom=classroom,
            homework__deleted_at__isnull=True,
            submitted_at__gte=begin,
            submitted_at__lte=finish,
        )
        .select_related('homework')
    )

    by_student = defaultdict(list)
    for sub in submissions:
        by_student[sub.student_id].append(sub)

    stats = {}
    for student_id, subs in by_student.items():
        grouped = _group_by_homework(subs)
        firsts, bests = [], []
        seconds_per_question = []
        perfect = False
        repeated = False
        for attempts in grouped.values():
            first = attempts[0].percentage
            best = max(a.percentage for a in attempts)
            firsts.append(first)
            bests.append(best)
            perfect = perfect or best >= 100
            repeated = repeated or len(attempts) > 1
            for attempt in attempts:
                if attempt.total_questions and attempt.time_taken_seconds:
                    seconds_per_question.append(
                        attempt.time_taken_seconds / attempt.total_questions
                    )
        avg_first = _mean(firsts)
        avg_best = _mean(bests)
        stats[student_id] = {
            'attempts': len(subs),
            'homework_count': len(grouped),
            'avg_first_pct': avg_first,
            'avg_best_pct': avg_best,
            # Deliberately best-minus-first rather than the mean of the
            # per-homework gains: the headline figure is computed that way, and
            # a report that says "+37 points" at the top and "gained 38" in the
            # award four lines below teaches the reader not to trust either.
            'avg_gain_pct': avg_best - avg_first,
            'repeated': repeated,
            'perfect': perfect,
            'seconds_per_question': (
                round(sum(seconds_per_question) / len(seconds_per_question))
                if seconds_per_question else None
            ),
        }
    return stats


def _winners(stats, key, predicate=None, biggest=True):
    """Every student tied for the best value of *key* among those passing *predicate*.

    Ties all win. Rationing recognition on a tiebreak the student cannot see
    would be arbitrary, and the cost of two winners is nothing.
    """
    eligible = {
        student_id: row for student_id, row in stats.items()
        if row.get(key) is not None and (predicate is None or predicate(row))
    }
    if not eligible:
        return set()
    target = (max if biggest else min)(row[key] for row in eligible.values())
    if biggest and not target:
        # Nobody actually did anything on this measure — no award.
        return set()
    return {sid for sid, row in eligible.items() if row[key] == target}


def awards_for(student, classroom, start, end, due_count, cohort_cache=None):
    """Awards this student earned in *classroom* over the window — §2.5."""
    stats = cohort_stats(classroom, start, end, cache=cohort_cache)
    mine = stats.get(student.id)
    if not mine:
        return []

    class_name = classroom.name
    earned = []
    cohort_ready = len(stats) >= MIN_COHORT

    def add(code, label, detail):
        earned.append({
            'code': code, 'label': label,
            'detail': detail, 'classroom': class_name,
        })

    if cohort_ready:
        if student.id in _winners(stats, 'avg_best_pct'):
            add('top_scorer', 'Top Scorer',
                f'Highest average of {mine["avg_best_pct"]}% in {class_name}.')

        if student.id in _winners(
                stats, 'attempts', predicate=lambda r: r['repeated']):
            add('hard_worker', 'Hard Worker',
                f'{mine["attempts"]} attempts in {class_name} — kept going back '
                f'to push the score up.')

        if student.id in _winners(
                stats, 'avg_gain_pct', predicate=lambda r: r['avg_gain_pct'] > 0):
            add('most_improved', 'Most Improved',
                f'Gained {mine["avg_gain_pct"]} percentage points between first '
                f'and best attempts.')

        fast = _winners(
            stats, 'seconds_per_question',
            predicate=lambda r: r['avg_best_pct'] >= FAST_ACCURATE_MIN_PCT,
            biggest=False,
        )
        if student.id in fast:
            add('fast_and_accurate', 'Fast and Accurate',
                f'{mine["avg_best_pct"]}% average at '
                f'{mine["seconds_per_question"]}s per question.')

    # Individual awards need no cohort — they are measured against the work,
    # not against other children.
    if mine['perfect']:
        add('perfect_score', 'Perfect Score',
            f'Scored 100% on a homework in {class_name}.')

    if due_count >= 2 and mine['homework_count'] >= due_count:
        add('full_completion', 'Full Completion',
            f'Attempted all {due_count} homework due in {class_name}.')

    return earned


def _student_classrooms(student, classroom_ids=None):
    from classroom.models import ClassRoom

    qs = ClassRoom.objects.filter(
        class_students__student=student, class_students__is_active=True,
    )
    if classroom_ids is not None:
        qs = qs.filter(id__in=classroom_ids)
    return list(qs.distinct().order_by('name'))


def _due_count_for(classroom, due):
    return sum(1 for hw in due if hw.classroom_id == classroom.id)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_report_data(student, period_type, start, end, term=None,
                      cohort_cache=None, classroom_ids=None):
    """The whole snapshot for one student and one closed window.

    Returns a plain dict — this is exactly what gets stored in
    ``PeriodReport.data`` and rendered by both the page and the PDF. Pass
    *cohort_cache* (a plain dict) when building many students' reports for the
    same window so each class's cohort figures are computed once.

    *classroom_ids* limits the report to the classes that switched reporting
    on. A student in two classes where only one reports gets a report about
    that one — which is what makes "only configured classes get it" true of the
    contents, not just of the trigger.
    """
    submissions = student_submissions(student, start, end, classroom_ids)
    due = homework_due_in_window(student, start, end, classroom_ids)

    awards = []
    classrooms = _student_classrooms(student, classroom_ids)
    for classroom in classrooms:
        awards.extend(awards_for(
            student, classroom, start, end, _due_count_for(classroom, due),
            cohort_cache=cohort_cache,
        ))

    return {
        'period': {
            'type': period_type,
            'label': label_for(period_type, start, end, term),
            'start': start.isoformat(),
            'end': end.isoformat(),
        },
        # Which classes this report actually covers. Recorded so a reader
        # asking "why is my other class missing?" can be answered from the
        # snapshot rather than from today's settings, which may have changed.
        'scope': {
            'classroom_ids': [c.id for c in classrooms],
            'classrooms': [c.name for c in classrooms],
            'all_classes': classroom_ids is None,
        },
        'student': {
            'name': student.get_full_name() or student.username,
            'username': student.username,
        },
        'totals': totals_section(submissions, due),
        'topics': topics_section(submissions),
        'attempts': attempts_section(submissions),
        'trend': trend_section(submissions, period_type),
        'worksheets': worksheets_section(student, start, end, classroom_ids),
        'awards': awards,
    }
