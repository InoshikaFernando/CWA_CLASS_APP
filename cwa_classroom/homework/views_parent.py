"""
homework/views_parent.py
========================
Parent read-only homework dashboard.
"""

from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Q, Avg
from django.shortcuts import render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from classroom.models import ClassStudent
from classroom.views import RoleRequiredMixin

from .models import Homework, HomeworkSubmission


class ParentHomeworkView(RoleRequiredMixin, View):
    required_roles = [Role.PARENT]

    def get(self, request):
        tab = request.GET.get('tab', 'assigned')

        # Get current child from session (set by parent portal)
        child_id = request.session.get('parent_current_child_id')
        if not child_id:
            from classroom.models import ParentStudent
            link = ParentStudent.objects.filter(
                parent=request.user, is_active=True,
            ).select_related('student').first()
            if link:
                child_id = link.student_id
                request.session['parent_current_child_id'] = child_id

        if not child_id:
            return render(request, 'homework/parent/dashboard.html', {
                'no_child': True,
            })

        enrolled_class_ids = ClassStudent.objects.filter(
            student_id=child_id,
        ).values_list('classroom_id', flat=True)

        base_qs = Homework.objects.filter(
            classroom_id__in=enrolled_class_ids,
            is_active=True,
            status=Homework.STATUS_ACTIVE,
        ).select_related(
            'classroom', 'classroom__subject', 'topic',
        ).annotate(
            student_attempts=Count(
                'submissions',
                filter=Q(submissions__student_id=child_id),
            ),
            best_score=Max(
                'submissions__score',
                filter=Q(
                    submissions__student_id=child_id,
                    submissions__is_published=True,
                ),
            ),
        )

        now = timezone.now()

        if tab == 'assigned':
            homeworks = base_qs.filter(due_date__gte=now).order_by('due_date')
        elif tab == 'completed':
            homeworks = base_qs.filter(student_attempts__gt=0).order_by('-due_date')
        elif tab == 'overdue':
            homeworks = base_qs.filter(due_date__lt=now, student_attempts=0).order_by('due_date')
        else:
            homeworks = base_qs.order_by('due_date')

        # Stats
        all_hw = Homework.objects.filter(
            classroom_id__in=enrolled_class_ids,
            is_active=True,
            status=Homework.STATUS_ACTIVE,
        ).annotate(
            student_attempts=Count(
                'submissions',
                filter=Q(submissions__student_id=child_id),
            ),
        )
        todo_count = all_hw.filter(due_date__gte=now, student_attempts=0).count()
        completed_count = all_hw.filter(student_attempts__gt=0).count()
        overdue_count = all_hw.filter(due_date__lt=now, student_attempts=0).count()

        grouped = {}
        for hw in homeworks:
            subj = hw.classroom.subject
            if subj not in grouped:
                grouped[subj] = []
            grouped[subj].append(hw)

        from accounts.models import CustomUser
        child = CustomUser.objects.filter(pk=child_id).first()

        return render(request, 'homework/parent/dashboard.html', {
            'tab': tab,
            'grouped_homeworks': grouped,
            'todo_count': todo_count,
            'completed_count': completed_count,
            'overdue_count': overdue_count,
            'child': child,
        })
