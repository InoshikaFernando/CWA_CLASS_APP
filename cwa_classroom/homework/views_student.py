"""
homework/views_student.py
=========================
Student views for homework: dashboard, detail, submit.
"""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Q, Avg
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from classroom.models import ClassStudent

from .forms import HomeworkSubmissionForm
from .models import Homework, HomeworkSubmission


class HomeworkDashboardView(LoginRequiredMixin, View):

    def get(self, request):
        tab = request.GET.get('tab', 'assigned')

        # All active homework from classes the student is enrolled in
        enrolled_class_ids = ClassStudent.objects.filter(
            student=request.user,
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
                filter=Q(submissions__student=request.user),
            ),
            best_score=Max(
                'submissions__score',
                filter=Q(
                    submissions__student=request.user,
                    submissions__is_published=True,
                ),
            ),
            best_max_score=Max(
                'submissions__max_score',
                filter=Q(
                    submissions__student=request.user,
                    submissions__is_published=True,
                ),
            ),
        )

        now = timezone.now()

        if tab == 'assigned':
            homeworks = base_qs.filter(
                due_date__gte=now,
            ).exclude(
                # Exclude if student has submitted and homework has max_attempts
                # that have been reached
            ).order_by('due_date')
        elif tab == 'completed':
            homeworks = base_qs.filter(student_attempts__gt=0).order_by('-due_date')
        elif tab == 'overdue':
            homeworks = base_qs.filter(
                due_date__lt=now,
                student_attempts=0,
            ).order_by('due_date')
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
                filter=Q(submissions__student=request.user),
            ),
        )
        todo_count = all_hw.filter(due_date__gte=now, student_attempts=0).count()
        completed_count = all_hw.filter(student_attempts__gt=0).count()
        overdue_count = all_hw.filter(due_date__lt=now, student_attempts=0).count()

        avg_score = HomeworkSubmission.objects.filter(
            student=request.user,
            is_published=True,
            score__isnull=False,
            max_score__isnull=False,
            max_score__gt=0,
        ).aggregate(
            avg=Avg('score') * 100 / Avg('max_score'),
        )['avg']

        # Group by subject
        grouped = {}
        for hw in homeworks:
            subj = hw.classroom.subject
            if subj not in grouped:
                grouped[subj] = []
            grouped[subj].append(hw)

        return render(request, 'homework/student/dashboard.html', {
            'tab': tab,
            'grouped_homeworks': grouped,
            'todo_count': todo_count,
            'completed_count': completed_count,
            'overdue_count': overdue_count,
            'avg_score': avg_score,
        })


class HomeworkDetailView(LoginRequiredMixin, View):

    def get(self, request, hw_id):
        homework = get_object_or_404(
            Homework.objects.select_related('classroom', 'classroom__subject', 'topic', 'assigned_by'),
            pk=hw_id, is_active=True, status=Homework.STATUS_ACTIVE,
        )

        # Check enrollment (active or inactive for read-only)
        enrollment = ClassStudent.objects.filter(
            classroom=homework.classroom,
            student=request.user,
        ).first()
        if not enrollment:
            messages.error(request, "You're not enrolled in this class.")
            return redirect('homework:dashboard')

        can_submit = enrollment.is_active
        submissions = HomeworkSubmission.objects.filter(
            homework=homework,
            student=request.user,
        ).order_by('attempt_number')

        attempt_count = submissions.count()
        max_reached = (
            homework.max_attempts > 0
            and attempt_count >= homework.max_attempts
        )

        form = HomeworkSubmissionForm() if can_submit and not max_reached else None

        return render(request, 'homework/student/detail.html', {
            'homework': homework,
            'submissions': submissions,
            'form': form,
            'can_submit': can_submit,
            'max_reached': max_reached,
            'attempt_count': attempt_count,
        })


class HomeworkSubmitView(LoginRequiredMixin, View):

    def post(self, request, hw_id):
        homework = get_object_or_404(
            Homework, pk=hw_id, is_active=True, status=Homework.STATUS_ACTIVE,
        )

        enrollment = ClassStudent.objects.filter(
            classroom=homework.classroom,
            student=request.user,
            is_active=True,
        ).first()
        if not enrollment:
            messages.error(request, "You're not enrolled in this class.")
            return redirect('homework:dashboard')

        attempt_count = HomeworkSubmission.objects.filter(
            homework=homework, student=request.user,
        ).count()

        if homework.max_attempts > 0 and attempt_count >= homework.max_attempts:
            messages.error(request, 'Maximum attempts reached.')
            return redirect('homework:detail', hw_id=hw_id)

        form = HomeworkSubmissionForm(request.POST, request.FILES)
        if form.is_valid():
            submission = form.save(commit=False)
            submission.homework = homework
            submission.student = request.user
            submission.attempt_number = attempt_count + 1
            submission.save()

            if submission.is_late:
                messages.warning(request, 'Homework submitted (late).')
            else:
                messages.success(request, 'Homework submitted successfully.')
            return redirect('homework:detail', hw_id=hw_id)

        messages.error(request, 'Please fix the errors below.')
        return redirect('homework:detail', hw_id=hw_id)
