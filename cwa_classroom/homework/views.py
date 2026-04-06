import random
import time as time_module

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Max, Prefetch
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from classroom.models import ClassRoom, ClassStudent, ClassTeacher, Topic
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


def _select_and_save_questions(homework, topics, num_questions):
    """
    Select a stratified random set of questions from the given topics and
    persist them as HomeworkQuestion records so all students get the same set.
    """
    qs = Question.objects.filter(topic__in=topics).select_related('topic')
    all_questions = list(qs)

    if not all_questions:
        return 0

    if len(all_questions) > num_questions:
        selected = select_questions_stratified(all_questions, num_questions)
    else:
        selected = all_questions

    HomeworkQuestion.objects.bulk_create([
        HomeworkQuestion(homework=homework, question=q, order=i)
        for i, q in enumerate(selected)
    ])
    return len(selected)


# ---------------------------------------------------------------------------
# Teacher Views
# ---------------------------------------------------------------------------

class HomeworkCreateView(RoleRequiredMixin, View):
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_create.html'

    def get(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, id=classroom_id)
        _check_teacher_owns_class(request, classroom)
        # Build topic queryset scoped to the classroom's subjects/levels
        topics = Topic.objects.filter(is_active=True).select_related('subject', 'parent').order_by('subject__name', 'parent__name', 'name')
        form = HomeworkCreateForm()
        form.fields['topics'].queryset = topics
        return render(request, self.template_name, {
            'form': form,
            'classroom': classroom,
        })

    def post(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, id=classroom_id)
        _check_teacher_owns_class(request, classroom)
        topics = Topic.objects.filter(is_active=True).select_related('subject', 'parent').order_by('subject__name', 'parent__name', 'name')
        form = HomeworkCreateForm(request.POST)
        form.fields['topics'].queryset = topics

        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'classroom': classroom})

        with transaction.atomic():
            homework = form.save(commit=False)
            homework.classroom = classroom
            homework.created_by = request.user
            homework.save()
            form.save_m2m()

            selected_topics = form.cleaned_data['topics']
            count = _select_and_save_questions(homework, selected_topics, homework.num_questions)

        if count == 0:
            messages.warning(request, 'No questions found for the selected topics. Please add questions first.')
            homework.delete()
            return render(request, self.template_name, {'form': form, 'classroom': classroom})

        messages.success(request, f'Homework "{homework.title}" created with {count} questions.')
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

        questions = list(
            homework.homework_questions
            .select_related('question')
            .prefetch_related('question__answers')
        )

        return render(request, self.template_name, {
            'homework': homework,
            'questions': questions,
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
        hw_questions = list(
            homework.homework_questions
            .select_related('question')
            .prefetch_related('question__answers')
        )

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
                q = hwq.question
                is_correct = False
                selected_answer_obj = None
                text_ans = ''

                if q.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
                    answer_id = request.POST.get(f'answer_{q.id}')
                    if answer_id:
                        try:
                            selected_answer_obj = Answer.objects.get(id=answer_id, question=q)
                            is_correct = selected_answer_obj.is_correct
                        except Answer.DoesNotExist:
                            pass
                else:
                    text_ans = request.POST.get(f'answer_{q.id}', '').strip()
                    correct_answer = q.answers.filter(is_correct=True).first()
                    if correct_answer and text_ans.lower() == correct_answer.answer_text.lower():
                        is_correct = True

                if is_correct:
                    score += 1

                answer_records.append(HomeworkStudentAnswer(
                    submission=submission,
                    question=q,
                    selected_answer=selected_answer_obj,
                    text_answer=text_ans,
                    is_correct=is_correct,
                    points_earned=q.points if is_correct else 0,
                ))

            HomeworkStudentAnswer.objects.bulk_create(answer_records)

            pts = calculate_points(score, total, time_taken)
            submission.score = score
            submission.points = pts
            submission.save(update_fields=['score', 'points'])

        return redirect('homework:student_result', submission_id=submission.id)


class StudentHomeworkResultView(LoginRequiredMixin, View):
    template_name = 'homework/student_result.html'

    def get(self, request, submission_id):
        submission = get_object_or_404(HomeworkSubmission, id=submission_id, student=request.user)
        answers = (
            submission.answers
            .select_related('question', 'selected_answer')
            .prefetch_related('question__answers')
        )
        return render(request, self.template_name, {
            'submission': submission,
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
