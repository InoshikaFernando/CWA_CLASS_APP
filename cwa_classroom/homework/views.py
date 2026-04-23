import random
import time as time_module

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Max, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from classroom.models import ClassRoom, ClassStudent, ClassTeacher, Topic
from classroom.notifications import create_notification
from classroom.subject_registry import (
    get as get_plugin,
    homework_plugins,
    homework_subject_choices,
)
from classroom.views import RoleRequiredMixin
from maths.models import Answer, Question, calculate_points
from maths.views import select_questions_stratified

from .forms import HomeworkCreateForm
from .models import Homework, HomeworkQuestion, HomeworkStudentAnswer, HomeworkSubmission


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _teacher_classrooms(user):
    """Return classrooms where the user is a teacher."""
    class_ids = ClassTeacher.objects.filter(teacher=user).values_list('classroom_id', flat=True)
    return ClassRoom.objects.filter(id__in=class_ids, is_active=True)


# NOTE: _topics_with_questions() and _build_topic_groups() used to live here.
# Phase 2 moved them to MathsPlugin so the same contract works for any subject.
# Call plugin.homework_topic_tree(classroom) instead.


def _select_and_save_questions(homework, selected_topic_ids, num_questions):
    """Ask the plugin for content ids, then persist HomeworkQuestion rows.

    Delegates the subject-specific selection to the plugin bound to
    ``homework.subject_slug`` so the same code path works for maths, coding,
    or any future subject.
    """
    plugin = get_plugin(homework.subject_slug)
    if plugin is None or not plugin.supports_homework:
        return 0

    content_ids = plugin.pick_homework_items(
        homework.classroom, selected_topic_ids, num_questions,
    )
    if not content_ids:
        return 0

    # Legacy maths rows keep the FK populated for admin/reporting compatibility;
    # non-maths rows leave it None.
    legacy_fk_populator = {}
    if homework.subject_slug == 'mathematics':
        legacy_fk_populator = {
            q.pk: q for q in Question.objects.filter(pk__in=content_ids)
        }

    HomeworkQuestion.objects.bulk_create([
        HomeworkQuestion(
            homework=homework,
            question=legacy_fk_populator.get(cid),
            subject_slug=homework.subject_slug,
            content_id=cid,
            order=i,
        )
        for i, cid in enumerate(content_ids)
    ])
    return len(content_ids)


# ---------------------------------------------------------------------------
# Teacher Views
# ---------------------------------------------------------------------------

class HomeworkCreateView(RoleRequiredMixin, View):
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_create.html'

    def _resolve_plugin(self, request):
        """Pick the SubjectPlugin for this request.

        POST carries ``subject_slug`` (default 'mathematics'); GET falls back
        to the default so the page renders with Mathematics selected.
        """
        slug = (request.POST.get('subject_slug')
                if request.method == 'POST'
                else request.GET.get('subject_slug')) or 'mathematics'
        plugin = get_plugin(slug)
        if plugin is None or not plugin.supports_homework:
            # Fall back to maths — we always ship with it registered.
            plugin = get_plugin('mathematics')
        return plugin

    def _base_context(self, request, classroom, plugin, form):
        return {
            'form': form,
            'classroom': classroom,
            'topic_groups': plugin.homework_topic_tree(classroom),
            'homework_subject_choices': homework_subject_choices(),
            'selected_subject_slug': plugin.slug,
            'topic_field_name': plugin.homework_topic_field_name(),
        }

    def get(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, id=classroom_id)
        _check_teacher_owns_class(request, classroom)
        plugin = self._resolve_plugin(request)
        form = HomeworkCreateForm()
        # For maths, the form's ``topics`` ModelMultipleChoiceField still
        # needs a queryset so ``form.cleaned_data['topics']`` works; we set
        # it to the plugin's topic tree flattened.
        if plugin.slug == 'mathematics':
            form.fields['topics'].queryset = plugin._topics_with_questions(classroom)
        return render(request, self.template_name, self._base_context(request, classroom, plugin, form))

    def post(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, id=classroom_id)
        _check_teacher_owns_class(request, classroom)
        plugin = self._resolve_plugin(request)
        form = HomeworkCreateForm(request.POST)
        if plugin.slug == 'mathematics':
            form.fields['topics'].queryset = plugin._topics_with_questions(classroom)

        if not form.is_valid():
            return render(request, self.template_name, self._base_context(request, classroom, plugin, form))

        # Topic ids come from the plugin-owned POST field name (maths → 'topics',
        # coding → 'coding_topics'). For maths we also accept the form-cleaned
        # list so existing ModelForm validation still runs.
        topic_ids = request.POST.getlist(plugin.homework_topic_field_name())
        if plugin.slug == 'mathematics' and form.cleaned_data.get('topics'):
            topic_ids = [str(t.pk) for t in form.cleaned_data['topics']]

        with transaction.atomic():
            homework = form.save(commit=False)
            homework.classroom = classroom
            homework.created_by = request.user
            homework.subject_slug = plugin.slug
            homework.save()
            # form.save_m2m will write to the legacy ``topics`` M2M regardless;
            # the plugin then reconciles to its own M2M.
            form.save_m2m()
            plugin.save_homework_topics(homework, topic_ids)

            count = _select_and_save_questions(homework, topic_ids, homework.num_questions)

        if count == 0:
            messages.warning(
                request,
                'No items found for the selected topics. Please add content first.',
            )
            homework.delete()
            return render(request, self.template_name, self._base_context(request, classroom, plugin, form))

        messages.success(request, f'Homework "{homework.title}" created with {count} questions.')

        # Notify all active students in the classroom
        homework_url = reverse('homework:student_take', kwargs={'homework_id': homework.id})
        due_str = homework.due_date.strftime('%d %b %Y') if homework.due_date else 'no deadline'
        active_students = (
            ClassStudent.objects
            .filter(classroom=classroom, is_active=True)
            .select_related('student')
        )
        for cs in active_students:
            create_notification(
                user=cs.student,
                message=(
                    f'New homework "{homework.title}" has been assigned in '
                    f'{classroom.name}. Due: {due_str}.'
                ),
                notification_type='homework_assigned',
                link=homework_url,
            )

        return redirect('homework:teacher_detail', homework_id=homework.id)


class HomeworkMonitorView(RoleRequiredMixin, View):
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_monitor.html'

    def get(self, request):
        classrooms = _teacher_classrooms(request.user)
        selected_classroom_id = request.GET.get('classroom')

        if selected_classroom_id:
            try:
                selected_classroom = classrooms.get(id=selected_classroom_id)
            except ClassRoom.DoesNotExist:
                selected_classroom = classrooms.first()
        else:
            selected_classroom = classrooms.first()

        homework_list = []
        if selected_classroom:
            homework_list = (
                Homework.objects
                .filter(classroom=selected_classroom)
                .prefetch_related(
                    Prefetch('topics', queryset=Topic.objects.select_related('subject', 'parent'))
                )
                .order_by('-created_at')
            )

        return render(request, self.template_name, {
            'classrooms': classrooms,
            'selected_classroom': selected_classroom,
            'homework_list': homework_list,
        })


class HomeworkDetailView(RoleRequiredMixin, View):
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_detail.html'

    def get(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)

        students = (
            ClassStudent.objects
            .filter(classroom=homework.classroom, is_active=True)
            .select_related('student')
        )

        student_rows = []
        for cs in students:
            student = cs.student
            best = HomeworkSubmission.get_best_submission(homework, student)
            attempt_count = HomeworkSubmission.get_attempt_count(homework, student)

            if best:
                status = best.submission_status
            elif homework.is_past_due:
                status = HomeworkSubmission.STATUS_NOT_SUBMITTED
            else:
                status = 'pending'

            student_rows.append({
                'student': student,
                'best_submission': best,
                'attempt_count': attempt_count,
                'status': status,
            })

        # Sort: on-time first, then late, then not-submitted/pending
        order = {'on_time': 0, 'late': 1, 'not_submitted': 2, 'pending': 3}
        student_rows.sort(key=lambda r: order.get(r['status'], 9))

        return render(request, self.template_name, {
            'homework': homework,
            'student_rows': student_rows,
        })


# ---------------------------------------------------------------------------
# Student Views
# ---------------------------------------------------------------------------

class StudentHomeworkListView(LoginRequiredMixin, View):
    template_name = 'homework/student_list.html'

    def get(self, request):
        # Find classrooms the student belongs to
        class_ids = ClassStudent.objects.filter(
            student=request.user, is_active=True
        ).values_list('classroom_id', flat=True)

        homework_qs = (
            Homework.objects
            .filter(classroom_id__in=class_ids)
            .prefetch_related(
                Prefetch('topics', queryset=Topic.objects.select_related('subject', 'parent'))
            )
            .order_by('due_date')
        )

        rows = []
        for hw in homework_qs:
            best = HomeworkSubmission.get_best_submission(hw, request.user)
            attempt_count = HomeworkSubmission.get_attempt_count(hw, request.user)
            can_attempt = (
                not hw.is_past_due and
                (hw.attempts_unlimited or attempt_count < hw.max_attempts)
            )

            if best:
                status = best.submission_status
            elif hw.is_past_due:
                status = HomeworkSubmission.STATUS_NOT_SUBMITTED
            else:
                status = 'pending'

            rows.append({
                'homework': hw,
                'best_submission': best,
                'attempt_count': attempt_count,
                'can_attempt': can_attempt,
                'status': status,
            })

        return render(request, self.template_name, {'rows': rows})


class StudentHomeworkTakeView(LoginRequiredMixin, View):
    template_name = 'homework/student_take.html'

    def get(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_student_enrolled(request, homework.classroom)

        attempt_count = HomeworkSubmission.get_attempt_count(homework, request.user)
        if not homework.attempts_unlimited and attempt_count >= homework.max_attempts:
            messages.error(request, 'You have used all your attempts for this homework.')
            return redirect('homework:student_list')
        if homework.is_past_due:
            messages.error(request, 'This homework is past its due date.')
            return redirect('homework:student_list')

        hw_questions = list(homework.homework_questions.order_by('order'))

        # Build one "item" per HomeworkQuestion by dispatching to the plugin
        # bound to its subject_slug. Each item carries the template path + the
        # plugin's context dict, so the take template can render any subject
        # via ``{% include item.template with ctx=item.ctx %}``.
        items = []
        for hwq in hw_questions:
            plugin = get_plugin(hwq.subject_slug)
            if plugin is None:
                continue
            items.append({
                'hwq': hwq,
                'template': plugin.take_item_template(),
                'ctx': plugin.take_item_context(hwq.content_id),
                'subject_slug': hwq.subject_slug,
                'content_id': hwq.content_id,
            })

        return render(request, self.template_name, {
            'homework': homework,
            'items': items,
            'attempt_number': attempt_count + 1,
        })

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_student_enrolled(request, homework.classroom)

        attempt_count = HomeworkSubmission.get_attempt_count(homework, request.user)
        if not homework.attempts_unlimited and attempt_count >= homework.max_attempts:
            messages.error(request, 'You have used all your attempts for this homework.')
            return redirect('homework:student_list')

        time_taken = int(request.POST.get('time_taken_seconds', 0))
        hw_questions = list(homework.homework_questions.order_by('order'))

        score = 0
        total = len(hw_questions)
        answer_records = []

        with transaction.atomic():
            submission = HomeworkSubmission.objects.create(
                homework=homework,
                student=request.user,
                attempt_number=HomeworkSubmission.get_next_attempt_number(homework, request.user),
                total_questions=total,
                time_taken_seconds=time_taken,
            )

            for hwq in hw_questions:
                plugin = get_plugin(hwq.subject_slug)
                if plugin is None:
                    continue
                graded = plugin.grade_answer(hwq.content_id, request.POST)
                is_correct = graded.get('is_correct', False)
                if is_correct:
                    score += 1
                answer_records.append(HomeworkStudentAnswer(
                    submission=submission,
                    # legacy FK — only populated for maths rows that return a
                    # ``question_id``; other subjects leave it as None.
                    question_id=graded.get('question_id'),
                    selected_answer_id=graded.get('selected_answer_id'),
                    text_answer=graded.get('text_answer', ''),
                    subject_slug=hwq.subject_slug,
                    content_id=hwq.content_id,
                    answer_data=graded.get('answer_data', {}),
                    is_correct=is_correct,
                    points_earned=graded.get('points_earned', 0),
                ))

            HomeworkStudentAnswer.objects.bulk_create(answer_records)

            pts = calculate_points(score, total, time_taken)
            submission.score = score
            submission.points = pts
            submission.save(update_fields=['score', 'points'])

        if request.POST.get('action') == 'save_exit':
            return redirect('homework:student_list')
        return redirect('homework:student_result', submission_id=submission.id)


class StudentHomeworkResultView(LoginRequiredMixin, View):
    template_name = 'homework/student_result.html'

    def get(self, request, submission_id):
        submission = get_object_or_404(HomeworkSubmission, id=submission_id, student=request.user)
        answers = list(
            submission.answers
            .select_related('question', 'selected_answer')
            .prefetch_related('question__answers')
        )

        # Dispatch each answer to its subject plugin for rendering.
        review_items = []
        for ans in answers:
            plugin = get_plugin(ans.subject_slug)
            if plugin is None:
                continue
            review_items.append({
                'ans': ans,
                'template': plugin.result_item_template(),
                'ctx': plugin.result_item_context(ans),
            })

        return render(request, self.template_name, {
            'submission': submission,
            'review_items': review_items,
            # Legacy context var kept so any consumer that still iterates
            # `answers` keeps working.
            'answers': answers,
        })


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _check_teacher_owns_class(request, classroom):
    if request.user.is_superuser:
        return
    if not ClassTeacher.objects.filter(teacher=request.user, classroom=classroom).exists():
        from django.http import Http404
        raise Http404


def _check_student_enrolled(request, classroom):
    if not ClassStudent.objects.filter(student=request.user, classroom=classroom, is_active=True).exists():
        from django.http import Http404
        raise Http404
