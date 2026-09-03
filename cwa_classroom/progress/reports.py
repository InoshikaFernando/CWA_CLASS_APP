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

import logging
from collections import defaultdict
from datetime import date, datetime, time

from django.db.models import Q
from django.utils import timezone

from progress.periods import label_for

logger = logging.getLogger(__name__)

UNCLASSIFIED = 'Unclassified'

# The slug every maths-domain strand belongs to. Quizzes, times tables and
# basic facts are maths and only maths, so they have no place in a report
# covering a coding class.
MATHS_SLUG = 'mathematics'

# Homework.subject_slug DEFAULTS to 'mathematics'. It is what a row says when
# nobody said anything, not a statement that the work is maths — the field was
# added by the subject-plugin refactor and back-filled with that value for every
# row that already existed.
#
# So 'mathematics' cannot be read as "this is maths" when deciding what to
# exclude from another subject's report. A Science class whose homework carries
# the default would otherwise have every piece of it filtered away, and the
# report would say the child did nothing rather than saying it is unconfigured.
UNSTATED_SLUG = MATHS_SLUG

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

def student_submissions(student, start, end, classroom_ids=None,
                        subject_slugs=None):
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
    if subject_slugs is not None:
        qs = qs.filter(_subject_filter('homework__subject_slug', subject_slugs))
    return list(
        qs.select_related('homework', 'homework__classroom')
        .order_by('submitted_at')
    )


def homework_due_in_window(student, start, end, classroom_ids=None,
                           subject_slugs=None):
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
    qs = Homework.objects.filter(
        classroom_id__in=class_ids,
        published_at__isnull=False,
        due_date__gte=begin,
        due_date__lte=finish,
    )
    if subject_slugs is not None:
        qs = qs.filter(_subject_filter('subject_slug', subject_slugs))
    return list(qs.order_by('due_date'))


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

def has_activity(data):
    """Whether this report says the child did anything in the window.

    THE one definition. It lived in two places — PeriodReport.has_activity and
    the preview row — and they disagreed: the preview tested
    ``totals['submissions']`` alone, which counts homework submissions and
    nothing else. So a child whose week was coding practice, worksheets,
    quizzes or times tables read "No activity this period — nothing will be
    sent" on the preview while the generator counted them active and sent the
    report. The preview understated the work AND misreported what would
    happen.

    ``activity_items`` is the effort total (see build_report_data): every
    strand, including the completion-only practice left out of the average.
    ``submissions`` stays in the test because a homework submission scoring
    zero is still activity.
    """
    totals = data.get('totals') or {}
    return bool(totals.get('submissions') or totals.get('activity_items'))


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


def subject_practice_section(student, start, end, subject_slugs=None):
    """Practice done in a subject's own app rather than as homework.

    Asked of each covered subject's plugin rather than read here, so a new
    subject supplies its own source instead of `reports.py` growing an `if
    slug == 'coding'`. Maths keeps its dedicated times-tables and basic-facts
    strands: they predate the registry and are named on the report in their
    own right, which a generic "practice" heading would lose.

    Returns the standard empty shape when nothing was done, so the report keeps
    identical keys whether or not any subject has a practice source.
    """
    from classroom import subject_registry

    empty = {'items': 0, 'scored_items': 0, 'attempts': 0, 'avg_first_pct': 0,
             'avg_best_pct': 0, 'scored_avg_best_pct': 0, 'improvement_pct': 0,
             'sections': []}
    if not subject_slugs:
        # None (unscoped) is deliberately empty here rather than "every
        # subject": this section is only meaningful once a report knows which
        # subject it is about.
        return empty

    begin, finish = _bounds(start, end)
    sections = []
    for slug in sorted(subject_slugs):
        plugin = subject_registry.get(slug)
        if plugin is None:
            continue
        section = plugin.practice_section(student, begin, finish)
        if section:
            sections.append(section)

    if not sections:
        return empty

    firsts = [s['avg_first_pct'] for s in sections]
    bests = [s['avg_best_pct'] for s in sections]
    avg_first, avg_best = _mean(firsts), _mean(bests)

    # Split effort from achievement. A coding exercise scores 100 for being
    # finished and 0 for not, which is a completion rate, not a mark. Ninety
    # seven of those would otherwise decide overall_avg_pct on their own and
    # make "96%" mean "she finished nearly everything she opened", in the same
    # column as a maths average that really is accuracy.
    #
    # So the unscored rows stay visible as work done — items, has_activity, the
    # section itself — and only the scored ones reach the headline. Rows are
    # scored unless a plugin says otherwise, because a percentage normally is
    # a mark.
    scored_rows = [
        row for section in sections for row in section['rows']
        if row.get('scored', True)
    ]
    return {
        'items': sum(s['items'] for s in sections),
        'scored_items': len(scored_rows),
        'attempts': sum(s['attempts'] for s in sections),
        'avg_first_pct': avg_first,
        'avg_best_pct': avg_best,
        'scored_avg_best_pct': (
            _mean([row['best_pct'] for row in scored_rows]) if scored_rows else 0
        ),
        'improvement_pct': avg_best - avg_first,
        'sections': sections,
    }


def _topic_names_by_subject(answers):
    """``{(subject_slug, content_id): topic name}`` for a window's answers.

    One bulk call per subject rather than a lookup per answer: a term report
    can carry thousands of answers, and the per-row alternative is what makes a
    report slow enough to time out.

    A subject whose plugin resolves nothing simply contributes no entries, and
    those answers fall through to "Unclassified" — which is honest, and is what
    every non-maths subject did before this existed.
    """
    from classroom import subject_registry

    by_subject = defaultdict(set)
    for answer in answers:
        by_subject[answer['subject_slug']].add(answer['content_id'])

    names = {}
    for slug, content_ids in by_subject.items():
        plugin = subject_registry.get(slug)
        if plugin is None:
            continue
        for content_id, name in plugin.content_topic_names(content_ids).items():
            if name:
                names[(slug, content_id)] = name
    return names


def topics_section(submissions):
    """Accuracy per ``classroom.Topic`` over every answer in the window — §2.2.

    Topics come from the questions the student actually answered, not from the
    homework's topic list: a mixed homework spans several topics, and crediting
    all of them for one right answer would be a lie.
    """
    from homework.models import HomeworkStudentAnswer

    if not submissions:
        return []

    answers = list(
        HomeworkStudentAnswer.objects
        .filter(submission_id__in=[s.id for s in submissions])
        .values('subject_slug', 'content_id', 'is_correct')
    )

    # Resolved through the subject registry rather than answer.question.topic:
    # that FK points at maths.Question and is null for every other subject, so
    # reading it filed every coding answer under "Unclassified". The modern
    # binding is (subject_slug, content_id), which every subject populates.
    names = _topic_names_by_subject(answers)

    tally = defaultdict(lambda: {'answered': 0, 'correct': 0})
    for answer in answers:
        name = names.get(
            (answer['subject_slug'], answer['content_id']), UNCLASSIFIED,
        )
        tally[name]['answered'] += 1
        tally[name]['correct'] += 1 if answer['is_correct'] else 0

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


def _worksheets_assigned(student, begin, finish, classroom_ids):
    """How many worksheets were SET in this window, completed or not.

    Without it "3 worksheets" is a number with no denominator: a reader cannot
    tell three of three from three of ten, and those say opposite things about
    the same child.

    WorksheetAssignment carries no due date — only ``assigned_at`` — so this
    counts what was set during the window rather than what fell due in it, and
    the report labels it that way. Inventing a deadline the model does not have
    would be worse than naming the one date that exists.

    Scoped to the student's own classes when the caller named none; otherwise
    a report would count every worksheet set anywhere in the system.
    """
    from worksheets.models import WorksheetAssignment

    qs = WorksheetAssignment.objects.filter(
        is_active=True, assigned_at__gte=begin, assigned_at__lte=finish,
    )
    if classroom_ids is not None:
        qs = qs.filter(classroom_id__in=classroom_ids)
    else:
        qs = qs.filter(
            classroom__class_students__student=student,
            classroom__class_students__is_active=True,
        )
    return qs.distinct().count()


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
        'assigned': _worksheets_assigned(student, begin, finish, classroom_ids),
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
# Maths practice outside homework: quizzes, times tables, basic facts
#
# CPP-388 originally read homework submissions only, per the ticket. A report
# built on homework alone under-reports a child who practises hard: their quiz
# attempts, times tables and basic facts were invisible. These sections read the
# same closed window, so a period still means one thing across the whole report.
# ---------------------------------------------------------------------------

def _final_answers(student, start, end, quiz_types):
    from maths.models import StudentFinalAnswer

    begin, finish = _bounds(start, end)
    return list(
        StudentFinalAnswer.objects
        .filter(
            student=student, quiz_type__in=quiz_types,
            completed_at__gte=begin, completed_at__lte=finish,
        )
        .select_related('topic', 'level')
        .order_by('completed_at')
    )


def _attempt_pct(row):
    return _pct(row.score, row.total_questions)


def quizzes_section(student, start, end, subject_slugs=None):
    """Topic and mixed maths quizzes attempted in the window.

    Grouped by topic and reported first-attempt vs best, the same shape as
    homework — retrying a quiz is the same behaviour the homework section is
    there to encourage, and showing it differently would hide that.
    """
    attempts = (
        _final_answers(student, start, end, ('topic', 'mixed'))
        if _covers_maths(subject_slugs) else []
    )
    # BrainBuzz is the cross-subject quiz: its sessions carry a Subject FK, so
    # a coding report gets the coding quizzes rather than nothing. Maths quizzes
    # live in their own app and only appear in a maths report.
    buzz = _brainbuzz_items(student, start, end, subject_slugs)

    if not attempts and not buzz:
        return {'attempted': 0, 'attempts': 0, 'avg_first_pct': 0,
                'avg_best_pct': 0, 'improvement_pct': 0, 'items': []}

    by_topic = defaultdict(list)
    for row in attempts:
        # Mixed quizzes have no topic; they are one bucket rather than dropped.
        key = row.topic_id if row.topic_id else '__mixed__'
        by_topic[key].append(row)

    items, firsts, bests = [], [], []
    for rows in by_topic.values():
        first = _attempt_pct(rows[0])
        best = max(_attempt_pct(r) for r in rows)
        firsts.append(first)
        bests.append(best)
        name = rows[0].topic.name if rows[0].topic_id else 'Mixed quiz'
        items.append({
            'name': name,
            'attempts': len(rows),
            'first_pct': first,
            'best_pct': best,
            'gain_pct': best - first,
        })
    # A BrainBuzz session is played once, so first and best are the same
    # figure. Saying so is honest: pretending it improved would put a zero gain
    # in the column that exists to show improvement.
    for item in buzz:
        firsts.append(item['first_pct'])
        bests.append(item['best_pct'])
    items.extend(buzz)
    items.sort(key=lambda i: (-i['gain_pct'], -i['attempts'], i['name']))

    avg_first, avg_best = _mean(firsts), _mean(bests)
    return {
        'attempted': len(by_topic) + len(buzz),
        'attempts': len(attempts) + sum(i['attempts'] for i in buzz),
        'avg_first_pct': avg_first,
        'avg_best_pct': avg_best,
        'improvement_pct': avg_best - avg_first,
        'items': items,
    }


def _brainbuzz_items(student, start, end, subject_slugs=None):
    """BrainBuzz quizzes the student played in the window, one row per session.

    BrainBuzz is the quiz that exists for every subject — its sessions carry a
    ``classroom.Subject`` FK — so this is what lets a coding report carry a
    coding quiz instead of nothing. Scoped to the report's subjects; unscoped
    (``None``) means every subject, as everywhere else.

    Accuracy is counted from the answers rather than read off
    ``BrainBuzzParticipant.score``, which is points including speed bonuses and
    would not be a percentage of anything.
    """
    from brainbuzz.models import BrainBuzzAnswer

    begin, finish = _bounds(start, end)
    qs = BrainBuzzAnswer.objects.filter(
        participant__student=student,
        submitted_at__gte=begin, submitted_at__lte=finish,
    )
    if subject_slugs is not None:
        qs = qs.filter(participant__session__subject__slug__in=subject_slugs)

    rows = qs.values(
        'participant__session_id',
        'participant__session__subject__name',
        'is_correct',
    )

    tally = defaultdict(lambda: {'answered': 0, 'correct': 0, 'name': ''})
    for row in rows:
        entry = tally[row['participant__session_id']]
        entry['answered'] += 1
        entry['correct'] += 1 if row['is_correct'] else 0
        entry['name'] = row['participant__session__subject__name'] or 'Quiz'

    items = []
    for entry in tally.values():
        pct = _pct(entry['correct'], entry['answered'])
        items.append({
            'name': f"{entry['name']} quiz",
            'attempts': 1,
            'first_pct': pct,
            'best_pct': pct,
            'gain_pct': 0,
        })
    return items


def times_tables_section(student, start, end, subject_slugs=None):
    """Times tables practised in the window, best per table and operation."""
    attempts = (
        _final_answers(student, start, end, ('times_table',))
        if _covers_maths(subject_slugs) else []
    )
    if not attempts:
        return {'tables': 0, 'attempts': 0, 'avg_best_pct': 0, 'items': []}

    best = defaultdict(dict)
    for row in attempts:
        if row.table_number is None:
            continue
        # Legacy rows saved no operation; they are still a real attempt.
        operation = row.operation or 'multiplication'
        pct = _attempt_pct(row)
        slot = best[row.table_number]
        if operation not in slot or pct > slot[operation]:
            slot[operation] = pct

    items = [
        {
            'table': table,
            'multiplication_pct': ops.get('multiplication'),
            'division_pct': ops.get('division'),
            'best_pct': max(ops.values()),
        }
        for table, ops in sorted(best.items())
    ]
    return {
        'tables': len(items),
        'attempts': len(attempts),
        'avg_best_pct': _mean([i['best_pct'] for i in items]),
        'items': items,
    }


def basic_facts_section(student, start, end, subject_slugs=None):
    """Basic-facts attempts in the window, best per subtopic."""
    from maths.models import BasicFactsResult

    begin, finish = _bounds(start, end)
    rows = list(
        BasicFactsResult.objects.filter(
            student=student,
            completed_at__gte=begin, completed_at__lte=finish,
        ).values('subtopic', 'level_number', 'score', 'total_points')
    ) if _covers_maths(subject_slugs) else []
    if not rows:
        return {'subtopics': 0, 'attempts': 0, 'avg_best_pct': 0, 'items': []}

    labels = {'PlaceValue': 'Place Value'}
    best = {}
    for row in rows:
        pct = _pct(row['score'], row['total_points'])
        key = row['subtopic'] or 'Unclassified'
        current = best.get(key)
        # Tie-break on level: the best score at the most advanced level is the
        # one worth reporting.
        candidate = (pct, row['level_number'] or 0)
        if current is None or candidate > current:
            best[key] = candidate

    items = [
        {'subtopic': labels.get(k, k), 'level': v[1], 'best_pct': v[0]}
        for k, v in sorted(best.items())
    ]
    return {
        'subtopics': len(items),
        'attempts': len(rows),
        'avg_best_pct': _mean([i['best_pct'] for i in items]),
        'items': items,
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


def covered_subject_slugs(classrooms):
    """The subjects a report covers, or ``None`` when that cannot be known.

    A report has no subject of its own yet, so it takes them from the classes
    it covers. ``None`` means "do not scope", and is returned whenever any
    covered class has no subject set — dropping a class's work on the strength
    of a blank field would be a worse bug than the one this fixes.
    """
    if not classrooms:
        return None
    slugs = set()
    for classroom in classrooms:
        slug = _classroom_subject_slug(classroom)
        if not slug:
            return None
        slugs.add(slug)
    return slugs


def resolved_subject(classroom):
    """The subject this class teaches: its own, else its department's.

    Read live rather than requiring a backfill. Mapping a department to a
    subject is the administrative act that says what its classes teach, so the
    reports should follow it immediately — needing someone to also run a
    command afterwards is a way to have the setting look applied while the
    reports disagree with it.

    The department decides only when it maps to exactly ONE subject.
    Department.subjects is many-to-many because a department can teach several,
    and two is not an answer. A subject set on the class itself always wins.

    Both halves of report-building go through here: this is what a report is
    FILED under (services groups classes by it) and what its content is scoped
    to (``covered_subject_slugs`` below). They must agree, or a report lands in
    the coding pile carrying an unscoped body.
    """
    if classroom.subject_id:
        return classroom.subject
    if classroom.department_id is None:
        return None
    subjects = list(classroom.department.subjects.all())
    return subjects[0] if len(subjects) == 1 else None


def with_subject_sources(qs):
    """Everything ``resolved_subject`` reads, in two queries instead of N."""
    return qs.select_related('subject', 'department').prefetch_related(
        'department__subjects',
    )


def _classroom_subject_slug(classroom):
    subject = resolved_subject(classroom)
    return subject.slug if subject else None



# ---------------------------------------------------------------------------
# What's next: the report's own reading of where to put the effort.
#
# Deterministic rules, not generated prose. This text is read by a child about
# themselves and by a parent about their child, it is frozen into the snapshot
# a family keeps, and it has to be defensible to a teacher who disagrees with
# it. A rule can be pointed at; a sentence a model wrote last Tuesday cannot.
#
# Two things it must never do:
#
#   * Call a topic weak on thin evidence. One wrong answer is not a gap, and
#     telling a child they are bad at something on the strength of it is worse
#     than saying nothing. MIN_TOPIC_ANSWERS is the floor.
#   * Give content advice to someone who has not started. If the work set was
#     not attempted, "focus on fractions" is beside the point.
# ---------------------------------------------------------------------------

#: Below this many answers a topic is not evidence either way.
MIN_TOPIC_ANSWERS = 4
#: At or above this, a topic counts as secure.
STRONG_PCT = 80
#: Below this, a topic counts as a gap worth naming.
WEAK_PCT = 50
#: Most reports carry three lines. More reads as a lecture and gets skimmed.
MAX_SUGGESTIONS = 3


def next_steps_section(data, classrooms=None):
    """Up to three suggestions: what is secure, what to work on, what next.

    Neutral voice on purpose — no "you", no child's name. The same sentence is
    read by the student and by their parent, and second person to one is third
    person to the other.

    Every line names the figure it rests on, so a reader can disagree with the
    conclusion by checking the number rather than by taking it on trust.

    Returns ``{'items': [...]}`` — empty when there is nothing honest to say,
    which is a section the page omits rather than a section reading "no advice".
    """
    totals = data.get('totals') or {}
    items = []

    if not (totals.get('submissions') or totals.get('activity_items')):
        # The report already says the period was empty. Repeating it as advice
        # adds nothing.
        return {'items': []}

    items += _engagement_items(totals)
    if not items:
        items += _topic_items(data, classrooms)
    items += _habit_items(totals, data.get('attempts') or {})

    return {'items': items[:MAX_SUGGESTIONS]}


def _engagement_items(totals):
    """Nothing about topics matters while the work set is going untouched."""
    assigned = totals.get('assigned') or 0
    completed = totals.get('completed') or 0
    if not assigned or completed >= assigned:
        return []

    if not completed:
        return [{
            'kind': 'focus',
            'text': (
                f'None of the {assigned} homework due this period was '
                f'attempted. Starting them is the first step.'
            ),
        }]
    return [{
        'kind': 'focus',
        'text': (
            f'{completed} of {assigned} homework due was attempted. '
            f'Finishing what is set comes before new topics.'
        ),
    }]


def _topic_items(data, classrooms):
    """Strength, gap, and where to go next — on evidence, or not at all."""
    rows = [
        row for row in (data.get('topics') or [])
        if row.get('answered', 0) >= MIN_TOPIC_ANSWERS
        and row.get('topic') != UNCLASSIFIED
    ]
    if not rows:
        return [{
            'kind': 'note',
            'text': (
                'Not enough questions were answered in any one topic this '
                'period to say where the strengths and gaps are.'
            ),
        }]

    # topics_section sorts weakest first; keep that and read from both ends.
    weakest, strongest = rows[0], rows[-1]
    gaps = [row for row in rows if row['accuracy_pct'] < WEAK_PCT]
    secure = [row for row in rows if row['accuracy_pct'] >= STRONG_PCT]
    items = []

    if secure:
        if len(secure) == len(rows):
            items.append({
                'kind': 'strength',
                'text': (
                    f'Every topic answered came out at {STRONG_PCT}% or '
                    f'better — the lowest was {weakest["topic"]} at '
                    f'{weakest["accuracy_pct"]}%.'
                ),
            })
        else:
            items.append({
                'kind': 'strength',
                'text': (
                    f'{strongest["topic"]} is secure at '
                    f'{strongest["accuracy_pct"]}%.'
                ),
            })

    if gaps:
        # One topic, not a list. "Work on all five of these" is not a plan.
        items.append({
            'kind': 'focus',
            'text': (
                f'{weakest["topic"]} is the one to put the time into, at '
                f'{weakest["accuracy_pct"]}% across '
                f'{weakest["answered"]} questions.'
            ),
        })
    elif not secure:
        items.append({
            'kind': 'focus',
            'text': (
                f'{weakest["topic"]} has the most room to improve, at '
                f'{weakest["accuracy_pct"]}%.'
            ),
        })
    else:
        suggestion = _untouched_topic(data, classrooms)
        if suggestion:
            items.append({
                'kind': 'next',
                'text': (
                    f'Nothing here needs shoring up, so {suggestion} is a '
                    f'sensible next topic — this class has material for it '
                    f'and none was attempted this period.'
                ),
            })

    return items


def _untouched_topic(data, classrooms):
    """A topic this class has content for and the student did not touch.

    Asked of the subject plugin rather than read from a table here, so it is
    the same pool a teacher picks homework from — suggesting a topic the class
    has nothing to set would be worse than suggesting nothing.

    Matched on NAME, because that is all the report's topic rows carry. A
    school with two identically named topics under different strands would see
    one treated as the other; the cost is a suggestion already attempted, not
    a wrong figure anywhere.
    """
    if not classrooms:
        return None

    from classroom import subject_registry

    done = {row.get('topic') for row in (data.get('topics') or [])}
    for classroom in classrooms:
        subject = resolved_subject(classroom)
        plugin = subject_registry.get(subject.slug) if subject else None
        if plugin is None or not plugin.supports_homework:
            continue
        try:
            tree = plugin.homework_topic_tree(classroom)
        except Exception:
            # A plugin that cannot build its tree must not fail a report.
            logger.warning(
                'topic tree unavailable for classroom %s', classroom.id,
                exc_info=True,
            )
            continue
        for _strand, mids in tree:
            for _mid, leaves in mids:
                for leaf in leaves:
                    if leaf.name not in done:
                        return leaf.name
    return None


def _habit_items(totals, attempts):
    """One line about how the work was done, not what it was about.

    Silent when nothing was handed in. Every figure below is computed over
    homework submissions, so with none they are all zero — and zero reads
    exactly like one attempt each: ``repeat_rate_pct`` is 0, ``avg_best_pct``
    is 0, and the "attempted once" branch fired next to a Focus line saying
    none of the nine were attempted at all. Two lines, same block, flatly
    contradicting each other. There is no habit to describe until there is a
    submission to describe it from.
    """
    if not totals.get('homework_attempted'):
        return []

    gain = totals.get('improvement_pct') or 0
    if gain >= 10:
        return [{
            'kind': 'habit',
            'text': (
                f'Retrying is working: first attempts averaged '
                f'{totals.get("avg_first_pct", 0)}%, best attempts '
                f'{totals.get("avg_best_pct", 0)}% — a gain of {gain} points.'
            ),
        }]

    repeat_rate = attempts.get('repeat_rate_pct') or 0
    if repeat_rate < 25 and (totals.get('avg_best_pct') or 0) < STRONG_PCT:
        return [{
            'kind': 'habit',
            'text': (
                'Most homework was attempted once. A second attempt is '
                'usually where the biggest gain comes from.'
            ),
        }]

    on_time = totals.get('on_time_pct')
    if totals.get('assigned') and on_time is not None and on_time < 60:
        return [{
            'kind': 'habit',
            'text': f'{on_time}% of homework was handed in on time.',
        }]

    return []

def _resolved_content(content):
    """Content flags with every key present.

    ``None`` means "everything", which is what an unconfigured caller — the
    preview, a management command, a test — should get. Callers that do
    configure it may pass a partial dict; missing keys default to on rather
    than to off, because a report is not improved by silently losing a section
    somebody never mentioned.
    """
    from progress.models import ProgressReportSetting

    resolved = dict(ProgressReportSetting.CONTENT_DEFAULTS)
    if content:
        resolved.update({k: v for k, v in content.items() if k in resolved})
    return resolved


def _subject_filter(field, subject_slugs):
    """Rows belonging to *subject_slugs*, treating the default slug as unstated.

    A maths report takes the default rows, because for maths the default and
    the truth coincide. Any other subject's report takes its own rows AND the
    unstated ones, because the alternative is dropping a class's whole term on
    the strength of a field nobody filled in.

    The cost is that a genuine maths homework set inside a science class counts
    towards science. That is the lesser error: it over-reports one item rather
    than under-reporting everything, and it disappears as soon as the homework
    says which subject it is.
    """
    condition = Q(**{f'{field}__in': list(subject_slugs)})
    if UNSTATED_SLUG not in subject_slugs:
        condition |= Q(**{field: UNSTATED_SLUG})
    return condition


def _covers_maths(subject_slugs):
    """Whether the maths-only strands belong in this report at all."""
    return subject_slugs is None or MATHS_SLUG in subject_slugs


def _student_classrooms(student, classroom_ids=None):
    from classroom.models import ClassRoom

    qs = with_subject_sources(ClassRoom.objects.filter(
        class_students__student=student, class_students__is_active=True,
    ))
    if classroom_ids is not None:
        qs = qs.filter(id__in=classroom_ids)
    return list(qs.distinct().order_by('name'))


def _due_count_for(classroom, due):
    return sum(1 for hw in due if hw.classroom_id == classroom.id)


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------

def build_report_data(student, period_type, start, end, term=None,
                      cohort_cache=None, classroom_ids=None, subject=None,
                      content=None):
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
    # The classes decide which subjects this report is about, so they are
    # resolved before anything is queried rather than only for the awards.
    classrooms = _student_classrooms(student, classroom_ids)
    # An explicit subject wins: run_period already grouped the classes by it,
    # and a report that says "Coding" must not widen itself by re-deriving.
    subjects = (
        {subject.slug} if subject is not None
        else covered_subject_slugs(classrooms)
    )
    content = _resolved_content(content)

    # A section switched off is not queried at all. Each section already
    # returns a well-formed empty result for "no rows", so switching one off
    # reuses that shape rather than a hand-written dict — the snapshot keeps
    # exactly the same keys, and the page and the PDF cannot disagree.
    if content['include_homework']:
        submissions = student_submissions(
            student, start, end, classroom_ids, subjects,
        )
        due = homework_due_in_window(
            student, start, end, classroom_ids, subjects,
        )
    else:
        submissions, due = [], []

    awards = []
    if content['include_awards']:
        for classroom in classrooms:
            awards.extend(awards_for(
                student, classroom, start, end, _due_count_for(classroom, due),
                cohort_cache=cohort_cache,
            ))

    quizzes = quizzes_section(
        student, start, end,
        subjects if content['include_quizzes'] else set(),
    )
    times_tables = times_tables_section(
        student, start, end,
        subjects if content['include_times_tables'] else set(),
    )
    basic_facts = basic_facts_section(
        student, start, end,
        subjects if content['include_basic_facts'] else set(),
    )
    subject_practice = subject_practice_section(
        student, start, end,
        subjects if content['include_subject_practice'] else set(),
    )
    worksheets = worksheets_section(
        student, start, end,
        classroom_ids if content['include_worksheets'] else [],
    )
    totals = totals_section(submissions, due)

    # One figure across everything the child actually did, so a report is not
    # judged on homework alone. Each strand contributes its own best-attempt
    # average, weighted by how many distinct things were attempted in it —
    # otherwise one perfect times table would outweigh a term of homework.
    strands = [
        (totals['homework_attempted'], totals['avg_best_pct']),
        (quizzes['attempted'], quizzes['avg_best_pct']),
        (times_tables['tables'], times_tables['avg_best_pct']),
        (basic_facts['subtopics'], basic_facts['avg_best_pct']),
        # scored_items, not items: completion is effort, not a mark. See
        # subject_practice_section.
        (subject_practice['scored_items'],
         subject_practice['scored_avg_best_pct']),
        (worksheets['completed'], worksheets['average_pct']),
    ]
    counted = [(n, pct) for n, pct in strands if n]

    # Two different totals, and conflating them is what made this wrong once
    # already. `weighted` is the divisor for the average and counts only what
    # carries a mark; `activity_items` is effort and counts everything the
    # child did, including the completion-only practice left out of the
    # average. has_activity reads the second, so a week of coding exercises
    # must not come back as "no activity".
    weighted = sum(n for n, _ in counted)
    unscored = subject_practice['items'] - subject_practice['scored_items']
    totals['activity_items'] = weighted + unscored
    totals['overall_avg_pct'] = (
        round(sum(n * pct for n, pct in counted) / weighted) if weighted else 0
    )

    snapshot = {
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
        'subject': {
            'id': subject.id if subject else None,
            'slug': subject.slug if subject else None,
            'name': subject.name if subject else None,
        },
        # What this report actually carried. A section switched off after the
        # fact must not change a report a family has already read, so the page
        # trusts this rather than today's settings.
        'sections_included': dict(content),
        'totals': totals,
        'topics': topics_section(submissions) if content['include_topics'] else [],
        'attempts': attempts_section(submissions),
        'trend': trend_section(submissions, period_type),
        'worksheets': worksheets,
        'quizzes': quizzes,
        'subject_practice': subject_practice,
        'times_tables': times_tables,
        'basic_facts': basic_facts,
        'awards': awards,
    }

    # Last, and from the finished snapshot rather than from the raw rows: the
    # advice has to rest on the same figures the reader can see above it, or a
    # parent checking it against the tables finds them disagreeing.
    snapshot['next_steps'] = (
        next_steps_section(snapshot, classrooms)
        if content['include_next_steps'] else {'items': []}
    )
    return snapshot
