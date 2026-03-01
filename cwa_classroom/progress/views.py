from django.shortcuts import render, redirect, get_object_or_404
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils import timezone
from datetime import date, timedelta

from classroom.models import Topic, Level
from .models import StudentFinalAnswer, BasicFactsResult, TopicLevelStatistics, TimeLog


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
        if user.is_student:
            classrooms = ClassRoom.objects.filter(students=user, is_active=True)
            levels = Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).distinct().order_by('level_number')
        else:
            classrooms = ClassRoom.objects.filter(students=user, is_active=True)
            levels = Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).distinct().order_by('level_number')

        # Build progress grid: level → topic → best result
        progress_grid = []
        for level in levels:
            topics = Topic.objects.filter(levels=level, is_active=True).order_by('name')
            row = {'level': level, 'topics': []}
            for topic in topics:
                best = StudentFinalAnswer.get_best_result(user, topic, level)
                latest = StudentFinalAnswer.get_latest_attempt(user, topic, level)
                attempts = StudentFinalAnswer.objects.filter(student=user, topic=topic, level=level).count()
                pct = best.percentage if best else None
                row['topics'].append({
                    'topic': topic,
                    'best': best,
                    'latest': latest,
                    'attempts': attempts,
                    'colour': _get_colour(pct),
                    'pct': pct,
                })
            progress_grid.append(row)

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

        # ── Recent activity ───────────────────────────────────────────
        recent_topic = StudentFinalAnswer.objects.filter(
            student=user
        ).select_related('topic', 'level').order_by('-completed_at')[:5]

        recent_bf = BasicFactsResult.objects.filter(
            student=user
        ).order_by('-completed_at')[:5]

        # ── Time log ─────────────────────────────────────────────────
        time_log = TimeLog.objects.filter(student=user).first()

        return render(request, 'student/dashboard.html', {
            'progress_grid': progress_grid,
            'bf_grid': bf_grid,
            'recent_topic': recent_topic,
            'recent_bf': recent_bf,
            'time_log': time_log,
        })


class StudentDetailProgressView(LoginRequiredMixin, View):
    """Teacher view: single student's full progress."""
    def get(self, request, student_id):
        if not (request.user.is_teacher or request.user.is_head_of_department):
            return redirect('home')
        from accounts.models import CustomUser
        student = get_object_or_404(CustomUser, id=student_id)

        from classroom.models import ClassRoom
        classrooms = ClassRoom.objects.filter(students=student, teachers=request.user, is_active=True)
        if not classrooms.exists() and not request.user.is_head_of_department:
            return redirect('home')

        levels = Level.objects.filter(classrooms__in=classrooms, level_number__lte=8).distinct().order_by('level_number')
        progress_grid = []
        for level in levels:
            topics = Topic.objects.filter(levels=level, is_active=True).order_by('name')
            row = {'level': level, 'topics': []}
            for topic in topics:
                best = StudentFinalAnswer.get_best_result(student, topic, level)
                pct = best.percentage if best else None
                row['topics'].append({
                    'topic': topic, 'best': best,
                    'colour': _get_colour(pct), 'pct': pct,
                })
            progress_grid.append(row)

        return render(request, 'student/detail_progress.html', {
            'student': student,
            'progress_grid': progress_grid,
        })
