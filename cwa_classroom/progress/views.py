from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import date, timedelta

from classroom.models import Topic, Level
from maths.models import StudentFinalAnswer, BasicFactsResult, TopicLevelStatistics, TimeLog


def _build_strand_data(student, level, include_attempts=False):
    """Build strand_data list for a level, grouping topics by parent strand.
    Topics without a parent (flat/legacy) are grouped under strand=None.

    Uses classroom.Topic for the display hierarchy (parent/order/is_active),
    but bridges to maths.Topic/Level by name for result lookups.
    Colour is based on mean/std-dev from TopicLevelStatistics.
    """
    from maths.models import Topic as MathsTopic, Level as MathsLevel

    # Resolve the maths-side Level from the classroom Level's level_number
    maths_level = MathsLevel.objects.filter(level_number=level.level_number).first()

    # Build a name → maths.Topic lookup to avoid per-topic DB hits
    maths_topic_map = {t.name: t for t in MathsTopic.objects.all()}

    # Pre-fetch statistics for this level keyed by maths topic id
    stats_map = {}
    if maths_level:
        for s in TopicLevelStatistics.objects.filter(level=maths_level).select_related('topic'):
            stats_map[s.topic_id] = s

    all_topics = (
        Topic.objects.filter(levels=level, is_active=True)
        .select_related('parent')
        .order_by('parent__order', 'order', 'name')
    )
    strand_dict = {}
    for topic in all_topics:
        key = topic.parent_id if topic.parent_id else '__flat__'
        if key not in strand_dict:
            strand_dict[key] = {'strand': topic.parent, 'subtopics': []}

        # Bridge classroom.Topic → maths.Topic by name
        maths_topic = maths_topic_map.get(topic.name)

        best = None
        if maths_topic and maths_level:
            best = StudentFinalAnswer.get_best_result(student, maths_topic, maths_level)

        # Colour based on stats (mean/sigma) if available, else fallback
        if best and maths_topic:
            stats = stats_map.get(maths_topic.id)
            if stats:
                colour = stats.get_colour_band(best.points)
            else:
                # No stats yet — treat as average
                colour = 'bg-green-200 text-green-900'
        elif best:
            colour = 'bg-green-200 text-green-900'
        else:
            colour = 'bg-gray-100 text-gray-400'

        entry = {
            'topic': topic,
            'maths_topic': maths_topic,
            'best': best,
            'colour': colour,
        }
        if include_attempts:
            if maths_topic and maths_level:
                entry['attempts'] = StudentFinalAnswer.objects.filter(
                    student=student, topic=maths_topic, level=maths_level
                ).count()
            else:
                entry['attempts'] = 0
        strand_dict[key]['subtopics'].append(entry)
    return list(strand_dict.values())


def _get_colour(percentage):
    """Return Tailwind bg+text classes based on percentage."""
    if percentage is None:
        return 'bg-gray-100 text-gray-400'
    if percentage >= 90:
        return 'bg-green-600 text-white'
    if percentage >= 75:
        return 'bg-green-400 text-white'
    if percentage >= 60:
        return 'bg-green-200 text-green-900'
    if percentage >= 45:
        return 'bg-yellow-200 text-yellow-900'
    if percentage >= 30:
        return 'bg-orange-200 text-orange-900'
    return 'bg-red-200 text-red-900'


class StudentDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        user = request.user
        if not (user.is_student or user.is_individual_student):
            return redirect('home')

        # ── Topic quiz results ────────────────────────────────────────
        from classroom.models import ClassRoom
        classrooms = ClassRoom.objects.filter(students=user, is_active=True)
        if classrooms.exists():
            levels = Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).distinct().order_by('level_number')
        else:
            # Student not in any classroom — show all available levels
            levels = Level.objects.filter(level_number__lte=8).order_by('level_number')

        # Build progress grid: level → strand → subtopic → best result
        progress_grid = []
        for level in levels:
            progress_grid.append({
                'level': level,
                'strand_data': _build_strand_data(user, level, include_attempts=True),
            })

        # ── Basic Facts results ───────────────────────────────────────
        from quiz.basic_facts import SUBTOPIC_CONFIG, SUBTOPIC_LABELS
        bf_grid = []
        for subtopic, cfg in SUBTOPIC_CONFIG.items():
            start, end = cfg['level_range']
            levels_data = []
            for i, num in enumerate(range(start, end + 1)):
                best = BasicFactsResult.get_best_result(user, subtopic, num)
                levels_data.append({
                    'level_number': num,
                    'display_level': i + 1,
                    'best': best,
                    'colour': _get_colour(best.percentage if best else None),
                })
            bf_grid.append({
                'subtopic': subtopic,
                'label': SUBTOPIC_LABELS[subtopic],
                'levels': levels_data,
            })

        # ── Times Tables results ─────────────────────────────────────
        from classroom.views import _tt_colour
        tt_results = []
        for table in range(1, 13):
            best_mul = StudentFinalAnswer.objects.filter(
                student=user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='multiplication',
                table_number=table,
            ).order_by('-points').first()
            best_div = StudentFinalAnswer.objects.filter(
                student=user,
                quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                operation='division',
                table_number=table,
            ).order_by('-points').first()
            # Legacy: attempts without operation saved (old records)
            if not best_mul and not best_div:
                best_legacy = StudentFinalAnswer.objects.filter(
                    student=user,
                    quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
                    operation='',
                    table_number=table,
                ).order_by('-points').first()
            else:
                best_legacy = None
            tt_results.append({
                'table': table,
                'mul': best_mul,
                'div': best_div,
                'legacy': best_legacy,
                'mul_colour': _tt_colour(best_mul if best_mul else best_legacy),
                'div_colour': _tt_colour(best_div),
            })

        # ── Recent activity ───────────────────────────────────────────
        recent_topic = StudentFinalAnswer.objects.filter(
            student=user,
            quiz_type__in=[StudentFinalAnswer.QUIZ_TYPE_TOPIC, StudentFinalAnswer.QUIZ_TYPE_MIXED],
        ).select_related('topic', 'level').order_by('-completed_at')[:5]

        recent_bf = BasicFactsResult.objects.filter(
            student=user
        ).order_by('-completed_at')[:5]

        recent_tt = StudentFinalAnswer.objects.filter(
            student=user,
            quiz_type=StudentFinalAnswer.QUIZ_TYPE_TIMES_TABLE,
        ).select_related('level').order_by('-completed_at')[:5]

        # ── Time log ─────────────────────────────────────────────────
        from maths.views import update_time_log_from_activities
        from classroom.views import _format_seconds

        time_log = update_time_log_from_activities(user)
        time_daily = _format_seconds(time_log.daily_total_seconds)
        time_weekly = _format_seconds(time_log.weekly_total_seconds)

        return render(request, 'student/dashboard.html', {
            'progress_grid': progress_grid,
            'bf_grid': bf_grid,
            'tt_results': tt_results,
            'recent_topic': recent_topic,
            'recent_bf': recent_bf,
            'recent_tt': recent_tt,
            'time_log': time_log,
            'time_daily': time_daily,
            'time_weekly': time_weekly,
        })


class StudentDetailProgressView(LoginRequiredMixin, View):
    """Teacher view: single student's full progress."""
    def get(self, request, student_id):
        if not (request.user.is_teacher or request.user.is_head_of_institute or request.user.is_institute_owner):
            return redirect('home')
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, id=student_id)

        from classroom.models import ClassRoom
        classrooms = ClassRoom.objects.filter(students=student, teachers=request.user, is_active=True)
        if not classrooms.exists() and not (request.user.is_head_of_institute or request.user.is_institute_owner):
            return redirect('home')

        levels = Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).distinct().order_by('level_number')
        progress_grid = []
        for level in levels:
            progress_grid.append({
                'level': level,
                'strand_data': _build_strand_data(student, level),
            })

        return render(request, 'student/detail_progress.html', {
            'student': student,
            'progress_grid': progress_grid,
        })
