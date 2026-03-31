"""
homework/views_teacher.py
=========================
Teacher views for homework: create, list, edit, delete, submissions, grade.
"""

import csv

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Q, Max, Avg
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from accounts.models import Role
from classroom.models import ClassRoom, ClassTeacher, ClassStudent
from classroom.views import RoleRequiredMixin
from classroom.views_teacher import _user_can_access_classroom

from .forms import HomeworkForm, GradingForm
from .models import Homework, HomeworkSubmission


TEACHER_ROLES = [
    Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
    Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
]


def _get_classroom_or_403(request, class_id):
    classroom = get_object_or_404(ClassRoom, pk=class_id, is_active=True)
    if not _user_can_access_classroom(request.user, classroom):
        messages.error(request, "You don't have permission to access that class.")
        return None
    return classroom


class HomeworkCreateView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, class_id):
        classroom = _get_classroom_or_403(request, class_id)
        if not classroom:
            return redirect('teacher_dashboard')
        form = HomeworkForm(classroom=classroom)
        return render(request, 'homework/teacher/create.html', {
            'form': form,
            'classroom': classroom,
        })

    def post(self, request, class_id):
        classroom = _get_classroom_or_403(request, class_id)
        if not classroom:
            return redirect('teacher_dashboard')
        form = HomeworkForm(request.POST, classroom=classroom)
        if form.is_valid():
            homework = form.save(commit=False)
            homework.classroom = classroom
            homework.assigned_by = request.user

            publish_option = form.cleaned_data['publish_option']
            if publish_option == HomeworkForm.PUBLISH_IMMEDIATELY:
                homework.status = Homework.STATUS_ACTIVE
                homework.published_at = timezone.now()
            elif publish_option == HomeworkForm.SAVE_DRAFT:
                homework.status = Homework.STATUS_DRAFT
            elif publish_option == HomeworkForm.SCHEDULE:
                homework.status = Homework.STATUS_SCHEDULED

            homework.save()
            status_label = homework.get_status_display()
            messages.success(request, f'Homework "{homework.title}" created ({status_label}).')
            return redirect('homework:class_list', class_id=classroom.pk)

        return render(request, 'homework/teacher/create.html', {
            'form': form,
            'classroom': classroom,
        })


class ClassHomeworkListView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, class_id):
        classroom = _get_classroom_or_403(request, class_id)
        if not classroom:
            return redirect('teacher_dashboard')

        tab = request.GET.get('tab', 'active')
        qs = Homework.objects.filter(classroom=classroom, is_active=True)

        if tab == 'active':
            homeworks = qs.filter(status=Homework.STATUS_ACTIVE)
        elif tab == 'drafts':
            homeworks = qs.filter(status__in=[Homework.STATUS_DRAFT, Homework.STATUS_SCHEDULED])
        else:  # past
            homeworks = qs.filter(status=Homework.STATUS_CLOSED)

        homeworks = homeworks.select_related('topic').annotate(
            submission_count=Count(
                'submissions', filter=Q(submissions__attempt_number=1)
            ),
            graded_count=Count(
                'submissions',
                filter=Q(submissions__is_graded=True, submissions__attempt_number=1),
            ),
            published_count=Count(
                'submissions',
                filter=Q(submissions__is_published=True, submissions__attempt_number=1),
            ),
        )

        student_count = ClassStudent.objects.filter(
            classroom=classroom, is_active=True,
        ).count()

        return render(request, 'homework/teacher/class_list.html', {
            'classroom': classroom,
            'homeworks': homeworks,
            'tab': tab,
            'student_count': student_count,
        })


class HomeworkEditView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, hw_id):
        homework = get_object_or_404(Homework, pk=hw_id, is_active=True)
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')
        if not homework.can_edit():
            messages.warning(request, 'This homework cannot be edited (submissions exist or closed).')
            return redirect('homework:class_list', class_id=homework.classroom_id)

        form = HomeworkForm(instance=homework, classroom=homework.classroom)
        return render(request, 'homework/teacher/create.html', {
            'form': form,
            'classroom': homework.classroom,
            'editing': True,
            'homework': homework,
        })

    def post(self, request, hw_id):
        homework = get_object_or_404(Homework, pk=hw_id, is_active=True)
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')
        if not homework.can_edit():
            messages.warning(request, 'This homework cannot be edited.')
            return redirect('homework:class_list', class_id=homework.classroom_id)

        form = HomeworkForm(request.POST, instance=homework, classroom=homework.classroom)
        if form.is_valid():
            hw = form.save(commit=False)
            publish_option = form.cleaned_data['publish_option']
            if publish_option == HomeworkForm.PUBLISH_IMMEDIATELY:
                hw.status = Homework.STATUS_ACTIVE
                hw.published_at = hw.published_at or timezone.now()
            elif publish_option == HomeworkForm.SAVE_DRAFT:
                hw.status = Homework.STATUS_DRAFT
            elif publish_option == HomeworkForm.SCHEDULE:
                hw.status = Homework.STATUS_SCHEDULED
            hw.save()
            messages.success(request, f'Homework "{hw.title}" updated.')
            return redirect('homework:class_list', class_id=hw.classroom_id)

        return render(request, 'homework/teacher/create.html', {
            'form': form,
            'classroom': homework.classroom,
            'editing': True,
            'homework': homework,
        })


class HomeworkDeleteView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def post(self, request, hw_id):
        homework = get_object_or_404(Homework, pk=hw_id, is_active=True)
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        homework.is_active = False
        homework.save(update_fields=['is_active', 'updated_at'])
        messages.success(request, f'Homework "{homework.title}" deleted.')
        return redirect('homework:class_list', class_id=homework.classroom_id)


class HomeworkPublishView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def post(self, request, hw_id):
        homework = get_object_or_404(Homework, pk=hw_id, is_active=True)
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')
        if homework.status not in (Homework.STATUS_DRAFT, Homework.STATUS_SCHEDULED):
            messages.warning(request, 'This homework is already published.')
            return redirect('homework:class_list', class_id=homework.classroom_id)

        homework.publish()
        messages.success(request, f'Homework "{homework.title}" published.')
        return redirect('homework:class_list', class_id=homework.classroom_id)


class SubmissionListView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, hw_id):
        homework = get_object_or_404(
            Homework.objects.select_related('classroom', 'topic'),
            pk=hw_id, is_active=True,
        )
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        # All students in the class (including inactive for unenrolled visibility)
        class_students = ClassStudent.objects.filter(
            classroom=homework.classroom,
        ).select_related('student')

        # Get first-attempt submissions for each student
        first_submissions = HomeworkSubmission.objects.filter(
            homework=homework,
            attempt_number=1,
        ).select_related('student')
        sub_by_student = {s.student_id: s for s in first_submissions}

        # Latest submissions (highest attempt)
        latest_attempts = HomeworkSubmission.objects.filter(
            homework=homework,
        ).values('student_id').annotate(
            max_attempt=Max('attempt_number'),
            latest_at=Max('submitted_at'),
        )
        latest_by_student = {la['student_id']: la for la in latest_attempts}

        # Build student rows
        rows = []
        for cs in class_students:
            student = cs.student
            first_sub = sub_by_student.get(student.pk)
            latest = latest_by_student.get(student.pk, {})
            rows.append({
                'student': student,
                'is_enrolled': cs.is_active,
                'first_submission': first_sub,
                'is_late': first_sub.is_late if first_sub else False,
                'attempts': latest.get('max_attempt', 0),
                'latest_at': latest.get('latest_at'),
                'score': first_sub.score if first_sub and first_sub.is_published else None,
                'max_score': first_sub.max_score if first_sub and first_sub.is_published else None,
                'is_graded': first_sub.is_graded if first_sub else False,
                'is_published': first_sub.is_published if first_sub else False,
            })

        total = len(rows)
        submitted = sum(1 for r in rows if r['attempts'] > 0)
        graded = sum(1 for r in rows if r['is_graded'])
        published = sum(1 for r in rows if r['is_published'])
        scores = [r['score'] for r in rows if r['score'] is not None]
        avg_score = sum(scores) / len(scores) if scores else None

        return render(request, 'homework/teacher/submissions.html', {
            'homework': homework,
            'rows': rows,
            'total': total,
            'submitted': submitted,
            'graded': graded,
            'published': published,
            'avg_score': avg_score,
        })


class GradeSubmissionView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, hw_id, sub_id):
        submission = get_object_or_404(
            HomeworkSubmission.objects.select_related('homework', 'homework__classroom', 'student'),
            pk=sub_id, homework_id=hw_id,
        )
        if not _user_can_access_classroom(request.user, submission.homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        form = GradingForm(initial={
            'score': submission.score,
            'max_score': submission.max_score,
            'feedback': submission.feedback,
        })

        # Get all submissions for this student+homework
        all_submissions = HomeworkSubmission.objects.filter(
            homework_id=hw_id,
            student=submission.student,
        ).order_by('attempt_number')

        return render(request, 'homework/teacher/grade.html', {
            'submission': submission,
            'homework': submission.homework,
            'form': form,
            'all_submissions': all_submissions,
        })

    def post(self, request, hw_id, sub_id):
        submission = get_object_or_404(
            HomeworkSubmission.objects.select_related('homework', 'homework__classroom', 'student'),
            pk=sub_id, homework_id=hw_id,
        )
        if not _user_can_access_classroom(request.user, submission.homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        form = GradingForm(request.POST)
        if form.is_valid():
            submission.score = form.cleaned_data['score']
            submission.max_score = form.cleaned_data['max_score']
            submission.feedback = form.cleaned_data['feedback']
            submission.is_graded = True
            submission.graded_by = request.user
            submission.graded_at = timezone.now()

            publish = 'publish' in request.POST
            if publish:
                submission.is_published = True

            submission.save()
            action = 'Graded and published' if publish else 'Graded'
            messages.success(request, f'{action} submission by {submission.student.get_full_name() or submission.student.username}.')
            return redirect('homework:submissions', hw_id=hw_id)

        all_submissions = HomeworkSubmission.objects.filter(
            homework_id=hw_id,
            student=submission.student,
        ).order_by('attempt_number')

        return render(request, 'homework/teacher/grade.html', {
            'submission': submission,
            'homework': submission.homework,
            'form': form,
            'all_submissions': all_submissions,
        })


class BulkPublishView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def post(self, request, hw_id):
        homework = get_object_or_404(Homework, pk=hw_id, is_active=True)
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        count = HomeworkSubmission.objects.filter(
            homework=homework,
            is_graded=True,
            is_published=False,
        ).update(is_published=True)

        messages.success(request, f'Published grades for {count} submission(s).')
        return redirect('homework:submissions', hw_id=hw_id)


class ExportCSVView(RoleRequiredMixin, View):
    required_roles = TEACHER_ROLES

    def get(self, request, hw_id):
        homework = get_object_or_404(
            Homework.objects.select_related('classroom'),
            pk=hw_id, is_active=True,
        )
        if not _user_can_access_classroom(request.user, homework.classroom):
            messages.error(request, "You don't have permission.")
            return redirect('teacher_dashboard')

        response = HttpResponse(content_type='text/csv')
        filename = f'homework_{homework.pk}_{homework.title[:30]}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'

        writer = csv.writer(response)
        writer.writerow([
            'Student', 'Email', 'Attempts', 'First Submitted',
            'Late', 'Score', 'Max Score', 'Percentage', 'Graded', 'Published',
        ])

        submissions = HomeworkSubmission.objects.filter(
            homework=homework,
            attempt_number=1,
        ).select_related('student').order_by('student__last_name', 'student__first_name')

        for sub in submissions:
            pct = ''
            if sub.score is not None and sub.max_score:
                pct = f'{(sub.score / sub.max_score * 100):.1f}%'
            writer.writerow([
                sub.student.get_full_name() or sub.student.username,
                sub.student.email,
                HomeworkSubmission.objects.filter(
                    homework=homework, student=sub.student,
                ).count(),
                sub.submitted_at.strftime('%Y-%m-%d %H:%M'),
                'Yes' if sub.is_late else 'No',
                sub.score or '',
                sub.max_score or '',
                pct,
                'Yes' if sub.is_graded else 'No',
                'Yes' if sub.is_published else 'No',
            ])

        return response
