"""
homework/views_student.py
=========================
Student views for homework: dashboard, detail, submit, mark-done, quiz flow.
"""

import json
import time
import uuid

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db.models import Count, Max, Q, Avg
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views import View

from classroom.models import ClassStudent

from .forms import HomeworkSubmissionForm, PDFSubmissionForm
from .models import Homework, HomeworkSubmission, HomeworkQuestion


class HomeworkDashboardView(LoginRequiredMixin, View):

    def get(self, request):
        tab = request.GET.get('tab', 'assigned')

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

        # Type-specific form
        form = None
        if can_submit and not max_reached:
            if homework.homework_type == Homework.TYPE_PDF:
                form = PDFSubmissionForm()
            elif homework.homework_type == Homework.TYPE_QUIZ:
                form = None  # Quiz uses start button, not a form
            elif homework.homework_type == Homework.TYPE_NOTE:
                form = None  # Note uses mark-as-done button
            else:
                form = HomeworkSubmissionForm()

        # Quiz-specific: get homework questions
        hw_questions = None
        if homework.homework_type == Homework.TYPE_QUIZ:
            hw_questions = HomeworkQuestion.objects.filter(
                homework=homework,
            ).select_related('question').count()

        return render(request, 'homework/student/detail.html', {
            'homework': homework,
            'submissions': submissions,
            'form': form,
            'can_submit': can_submit,
            'max_reached': max_reached,
            'attempt_count': attempt_count,
            'hw_question_count': hw_questions,
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

        # Use type-specific form
        if homework.homework_type == Homework.TYPE_PDF:
            form = PDFSubmissionForm(request.POST, request.FILES)
        else:
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


class MarkDoneView(LoginRequiredMixin, View):
    """Mark note-type homework as done (no content required)."""

    def post(self, request, hw_id):
        homework = get_object_or_404(
            Homework, pk=hw_id, is_active=True, status=Homework.STATUS_ACTIVE,
            homework_type=Homework.TYPE_NOTE,
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

        HomeworkSubmission.objects.create(
            homework=homework,
            student=request.user,
            attempt_number=attempt_count + 1,
            is_auto_completed=True,
        )
        messages.success(request, 'Marked as done.')
        return redirect('homework:detail', hw_id=hw_id)


class HomeworkQuizView(LoginRequiredMixin, View):
    """Start or continue a homework quiz with pre-assigned questions."""

    def get(self, request, hw_id):
        homework = get_object_or_404(
            Homework.objects.select_related('classroom'),
            pk=hw_id, is_active=True, status=Homework.STATUS_ACTIVE,
            homework_type=Homework.TYPE_QUIZ,
        )

        enrollment = ClassStudent.objects.filter(
            classroom=homework.classroom,
            student=request.user,
            is_active=True,
        ).first()
        if not enrollment:
            messages.error(request, "You're not enrolled in this class.")
            return redirect('homework:dashboard')

        # Check attempts
        attempt_count = HomeworkSubmission.objects.filter(
            homework=homework, student=request.user,
        ).count()
        if homework.max_attempts > 0 and attempt_count >= homework.max_attempts:
            messages.error(request, 'Maximum attempts reached.')
            return redirect('homework:detail', hw_id=hw_id)

        # Get pre-assigned questions
        hw_questions = HomeworkQuestion.objects.filter(
            homework=homework,
        ).select_related('question').order_by('order')

        if not hw_questions.exists():
            messages.error(request, 'No questions assigned to this homework.')
            return redirect('homework:detail', hw_id=hw_id)

        # Initialize or resume quiz session
        session_key = f'hw_quiz_{hw_id}'
        session_data = request.session.get(session_key)

        if not session_data:
            session_id = str(uuid.uuid4())
            questions_data = []
            for hwq in hw_questions:
                q = hwq.question
                answers = list(q.answers.order_by('order').values('id', 'answer_text', 'answer_image'))
                questions_data.append({
                    'id': q.id,
                    'order': hwq.order,
                    'answers': answers,
                })
            session_data = {
                'session_id': session_id,
                'questions': questions_data,
                'current': 0,
                'correct': 0,
                'start_time': time.time(),
                'answers': {},
            }
            request.session[session_key] = session_data

        # Get current question
        current_idx = session_data['current']
        if current_idx >= len(session_data['questions']):
            # Quiz already completed — shouldn't happen
            return redirect('homework:detail', hw_id=hw_id)

        q_data = session_data['questions'][current_idx]
        from maths.models import Question
        question = Question.objects.prefetch_related('answers').get(pk=q_data['id'])
        answers = list(question.answers.order_by('order'))

        return render(request, 'homework/student/quiz.html', {
            'homework': homework,
            'question': question,
            'answers': answers,
            'current': current_idx + 1,
            'total': len(session_data['questions']),
            'session_key': session_key,
        })


class SubmitHomeworkAnswerView(LoginRequiredMixin, View):
    """AJAX endpoint: submit an answer for a homework quiz question."""

    def post(self, request, hw_id):
        homework = get_object_or_404(
            Homework, pk=hw_id, is_active=True,
            homework_type=Homework.TYPE_QUIZ,
        )

        session_key = f'hw_quiz_{hw_id}'
        session_data = request.session.get(session_key)
        if not session_data:
            return JsonResponse({'error': 'No active quiz session'}, status=400)

        try:
            data = json.loads(request.body)
        except json.JSONDecodeError:
            return JsonResponse({'error': 'Invalid JSON'}, status=400)

        current_idx = session_data['current']
        questions = session_data['questions']
        if current_idx >= len(questions):
            return JsonResponse({'error': 'Quiz already completed'}, status=400)

        q_data = questions[current_idx]
        from maths.models import Question, Answer
        question = Question.objects.get(pk=q_data['id'])

        # Check answer
        is_correct = False
        correct_answer_text = ''

        if question.question_type in ('multiple_choice', 'true_false'):
            answer_id = data.get('answer_id')
            answer = Answer.objects.filter(id=answer_id, question=question).first()
            is_correct = bool(answer and answer.is_correct)
            correct_ans = question.answers.filter(is_correct=True).first()
            if correct_ans:
                correct_answer_text = correct_ans.answer_text
        else:
            raw = (data.get('text_answer') or '').strip()
            correct_ans = question.answers.filter(is_correct=True).first()
            if correct_ans:
                correct_answer_text = correct_ans.answer_text
                alts = [a.strip() for a in correct_ans.answer_text.split(',')]
                is_correct = raw.lower() in [a.lower() for a in alts]
                if not is_correct:
                    try:
                        is_correct = abs(float(raw) - float(alts[0])) <= 0.05
                    except (ValueError, IndexError):
                        pass

        if is_correct:
            session_data['correct'] += 1

        session_data['answers'][str(q_data['id'])] = {
            'is_correct': is_correct,
            'answer_id': data.get('answer_id'),
            'text_answer': data.get('text_answer', ''),
        }
        session_data['current'] += 1
        is_last = session_data['current'] >= len(questions)

        request.session[session_key] = session_data
        request.session.modified = True

        response_data = {
            'is_correct': is_correct,
            'correct_answer_text': correct_answer_text,
            'is_last_question': is_last,
        }

        if is_last:
            # Quiz completed — create submission
            score = session_data['correct']
            total = len(questions)
            time_taken = int(time.time() - session_data['start_time'])

            attempt_count = HomeworkSubmission.objects.filter(
                homework=homework, student=request.user,
            ).count()

            HomeworkSubmission.objects.create(
                homework=homework,
                student=request.user,
                attempt_number=attempt_count + 1,
                quiz_session_id=session_data['session_id'],
                score=score,
                max_score=total,
                is_auto_completed=True,
                is_graded=True,
                is_published=True,
            )

            # Clean up session
            del request.session[session_key]
            request.session.modified = True

            response_data['score'] = score
            response_data['total'] = total
            response_data['redirect_url'] = f'/homework/{hw_id}/'

        return JsonResponse(response_data)
