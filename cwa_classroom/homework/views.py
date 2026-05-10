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


def _build_topic_groups(topics_qs):
    """
    Return a 3-level hierarchy for the template:

        [(strand, [(mid, [leaves]), ...]), ...]

    - strand : top-level topic (parent=None) — rendered as a collapsible
               accordion header.  If it has NO mid_items it is shown as a
               plain selectable checkbox instead.
    - mid    : direct child of a strand — rendered as a plain checkbox
               inside the accordion.  If it has leaf children it also gets
               a small sub-group label above those leaves.
    - leaves : grandchildren of the strand — shown indented under their mid.

    Topics that are already at depth-0 with questions appear as standalone
    checkboxes (empty mid_items list).  Parents/grandparents that are not
    themselves in the queryset are still used as group headers.
    """
    from collections import OrderedDict

    # strands : {strand_id: (strand_topic, OrderedDict {mid_id: (mid_topic, [leaf_topics])})}
    strands = OrderedDict()

    for topic in topics_qs:
        parent = topic.parent          # may be None
        grandparent = parent.parent if parent else None  # may be None

        if parent is None:
            # depth-0 — strand itself has questions
            if topic.pk not in strands:
                strands[topic.pk] = (topic, OrderedDict())
            # No need to add it as a child of anything

        elif grandparent is None:
            # depth-1 — direct child of a strand
            strand = parent
            if strand.pk not in strands:
                strands[strand.pk] = (strand, OrderedDict())
            mids = strands[strand.pk][1]
            if topic.pk not in mids:
                mids[topic.pk] = (topic, [])

        else:
            # depth-2 — grandchild (e.g. "Multiplication (2x)" under Multiplication under Number)
            strand = grandparent
            mid = parent
            if strand.pk not in strands:
                strands[strand.pk] = (strand, OrderedDict())
            mids = strands[strand.pk][1]
            if mid.pk not in mids:
                mids[mid.pk] = (mid, [])
            mids[mid.pk][1].append(topic)

    # Flatten to list for the template
    result = [
        (strand, [(mid, leaves) for mid, leaves in mids.values()])
        for strand, mids in strands.values()
    ]
    return result


def _topics_with_questions(classroom):
    """
    Return a Topic queryset restricted to topics that have at least one
    Question at the classroom's levels.  If the classroom has no levels
    configured, fall back to any topic that has at least one question.
    """
    from django.db.models import Exists, OuterRef

    classroom_levels = classroom.levels.all()
    base_qs = Topic.objects.filter(is_active=True).select_related('subject', 'parent', 'parent__parent').order_by(
        'subject__name', 'parent__name', 'name'
    )

    if classroom_levels.exists():
        question_filter = Question.objects.filter(
            topic=OuterRef('pk'),
            level__in=classroom_levels,
        )
    else:
        question_filter = Question.objects.filter(topic=OuterRef('pk'))

    return base_qs.filter(Exists(question_filter))


def _select_and_save_questions(homework, topics, num_questions):
    """
    Select a stratified random set of questions from the given topics and
    persist them as HomeworkQuestion records so all students get the same set.
    Only questions at the classroom's configured levels are considered;
    falls back to all levels if the classroom has none set.
    """
    classroom_levels = homework.classroom.levels.all()
    qs = Question.objects.filter(topic__in=topics).select_related('topic')
    if classroom_levels.exists():
        qs = qs.filter(level__in=classroom_levels)
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
        topics = _topics_with_questions(classroom)
        form = HomeworkCreateForm()
        form.fields['topics'].queryset = topics
        return render(request, self.template_name, {
            'form': form,
            'classroom': classroom,
            'topic_groups': _build_topic_groups(topics),
        })

    def post(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, id=classroom_id)
        _check_teacher_owns_class(request, classroom)
        topics = _topics_with_questions(classroom)
        form = HomeworkCreateForm(request.POST)
        form.fields['topics'].queryset = topics

        if not form.is_valid():
            return render(request, self.template_name, {
                'form': form,
                'classroom': classroom,
                'topic_groups': _build_topic_groups(topics),
            })

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

        import random
        questions = list(
            homework.homework_questions
            .select_related('question')
            .prefetch_related('question__answers')
        )
        # Shuffle answer options per question so correct answer isn't always first
        for hwq in questions:
            hwq.shuffled_answers = list(hwq.question.answers.all())
            random.shuffle(hwq.shuffled_answers)

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
                review_status = HomeworkStudentAnswer.REVIEW_AUTO

                if q.question_type in (Question.MULTIPLE_CHOICE, Question.TRUE_FALSE):
                    answer_id = request.POST.get(f'answer_{q.id}')
                    if answer_id:
                        try:
                            selected_answer_obj = Answer.objects.get(id=answer_id, question=q)
                            is_correct = selected_answer_obj.is_correct
                        except Answer.DoesNotExist:
                            pass

                elif q.question_type == Question.EXTENDED_ANSWER or q.validation_type in (
                    Question.VALIDATION_AI, Question.VALIDATION_HUMAN
                ):
                    # Written answer — needs AI or human grading
                    text_ans = request.POST.get(f'answer_{q.id}', '').strip()
                    if q.validation_type == Question.VALIDATION_AI:
                        review_status = HomeworkStudentAnswer.REVIEW_PENDING_AI
                    else:
                        review_status = HomeworkStudentAnswer.REVIEW_PENDING_TEACHER
                    # Score/correctness deferred until reviewed; treat as 0 for now

                else:
                    # Auto short/calculation answer
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
                    review_status=review_status,
                ))

            HomeworkStudentAnswer.objects.bulk_create(answer_records)

            pts = calculate_points(score, total, time_taken)
            submission.score = score
            submission.points = pts
            submission.save(update_fields=['score', 'points'])

        # Trigger AI grading for any pending-AI answers (outside the atomic block
        # so a grading failure doesn't roll back the submission)
        _trigger_ai_grading_for_submission(submission, request)

        if request.POST.get('action') == 'save_exit':
            return redirect('homework:student_list')
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


def _trigger_ai_grading_for_submission(submission, request=None):
    """
    After a submission is saved, grade any answers with review_status='pending_ai'
    using the AI grading service (with caching).
    """
    from worksheets.grading_service import grade_extended_answer
    from billing.entitlements import get_school_for_user
    from django.utils import timezone

    pending = list(
        submission.answers
        .filter(review_status=HomeworkStudentAnswer.REVIEW_PENDING_AI)
        .select_related('question')
    )

    if not pending:
        return

    school = None
    try:
        if request:
            school = get_school_for_user(request.user)
    except Exception:
        pass

    for answer in pending:
        try:
            result = grade_extended_answer(answer.question, answer.text_answer, school=school)
            score_frac = result.get('score_fraction', 0.0)
            answer.is_correct = result.get('is_correct', False)
            answer.ai_score_fraction = score_frac
            answer.ai_feedback = result.get('feedback', '')
            answer.points_earned = round(answer.question.points * score_frac, 2)
            answer.review_status = HomeworkStudentAnswer.REVIEW_AI_DONE
            answer.graded_at = timezone.now()
            answer.save(update_fields=[
                'is_correct', 'ai_score_fraction', 'ai_feedback',
                'points_earned', 'review_status', 'graded_at',
            ])
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                f'AI grading failed for HomeworkStudentAnswer {answer.pk}'
            )

    # Recalculate submission score to include AI-graded points
    _recalculate_submission_score(submission)


def _recalculate_submission_score(submission):
    """Recount score and points from all answers (called after grading)."""
    answers = list(submission.answers.select_related('question'))
    score = sum(1 for a in answers if a.is_correct)
    pts = sum(a.points_earned for a in answers)
    submission.score = score
    submission.points = pts
    submission.save(update_fields=['score', 'points'])


# ---------------------------------------------------------------------------
# Teacher: PDF Homework Upload Flow (3 steps)
# ---------------------------------------------------------------------------

TEACHER_ROLES = ['teacher', 'senior_teacher', 'junior_teacher']


class HomeworkPDFUploadView(RoleRequiredMixin, View):
    """Step 1 — upload a PDF; AI extracts questions and stores in HomeworkUploadSession."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/upload.html'

    def get(self, request):
        classrooms = _teacher_classrooms(request.user)
        return render(request, self.template_name, {'classrooms': classrooms})

    def post(self, request):
        from billing.entitlements import get_school_for_user
        from worksheets.services import extract_and_classify_worksheet
        from classroom.models import Topic, Level

        pdf_file = request.FILES.get('pdf_file')
        classroom_id = request.POST.get('classroom_id')

        if not pdf_file:
            messages.error(request, 'Please select a PDF file.')
            return redirect('homework:pdf_upload')

        if not pdf_file.name.lower().endswith('.pdf'):
            messages.error(request, 'Only PDF files are supported.')
            return redirect('homework:pdf_upload')

        school = get_school_for_user(request.user)
        classroom = None
        if classroom_id:
            try:
                classroom = ClassRoom.objects.get(id=classroom_id)
                _check_teacher_owns_class(request, classroom)
            except (ClassRoom.DoesNotExist, Exception):
                classroom = None

        try:
            existing_topics = list(Topic.objects.filter(
                subject__slug='mathematics',
            ).values('name', 'slug')[:100])
            existing_levels = list(Level.objects.filter(
                level_number__lte=12,
            ).values('level_number', 'display_name'))

            output = extract_and_classify_worksheet(pdf_file, existing_topics, existing_levels)
            result = output['result']
            extracted_images = output['extracted_images']
            page_count = output['page_count']

            # Default homework title from filename
            hw_title = pdf_file.name
            if hw_title.lower().endswith('.pdf'):
                hw_title = hw_title[:-4]

            from .models import HomeworkUploadSession
            session = HomeworkUploadSession.objects.create(
                user=request.user,
                school=school,
                classroom=classroom,
                pdf_filename=pdf_file.name,
                homework_title=hw_title,
                extracted_data=result,
                extracted_images=extracted_images,
                page_count=page_count,
                tokens_used=result.get('usage', {}).get('total_tokens', 0),
            )

            return redirect('homework:pdf_preview', session_id=session.pk)

        except ImportError:
            messages.error(request, 'PDF processing library not installed. Please contact the administrator.')
            return redirect('homework:pdf_upload')
        except Exception as e:
            messages.error(request, f'Error processing PDF: {str(e)}')
            return redirect('homework:pdf_upload')


class HomeworkPDFPreviewView(RoleRequiredMixin, View):
    """Step 2 — preview AI-extracted questions; teacher edits, sets validation_type, confirms."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/upload_preview.html'

    def get(self, request, session_id):
        from .models import HomeworkUploadSession
        session = get_object_or_404(
            HomeworkUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data
        questions = data.get('questions', [])

        from classroom.models import Topic, Level
        topics = Topic.objects.filter(subject__slug='mathematics').order_by('name')
        levels = Level.objects.filter(level_number__lte=12).order_by('level_number')
        classrooms = _teacher_classrooms(request.user)

        for q in questions:
            q.setdefault('year_level', data.get('year_level'))
            q.setdefault('subject', data.get('subject', 'Mathematics'))
            q.setdefault('strand', data.get('strand', ''))
            q.setdefault('topic', data.get('topic', ''))
            q.setdefault('include', True)
            q.setdefault('validation_type', 'auto')
            q.setdefault('grading_rubric', '')
            ref = q.get('image_ref')
            q['image_b64'] = session.extracted_images.get(ref) if ref else None

        return render(request, self.template_name, {
            'session': session,
            'data': data,
            'questions': questions,
            'topics': topics,
            'levels': levels,
            'classrooms': classrooms,
            'question_types': [
                ('multiple_choice', 'Multiple Choice'),
                ('true_false', 'True / False'),
                ('short_answer', 'Short Answer'),
                ('fill_blank', 'Fill in the Blank'),
                ('calculation', 'Calculation'),
                ('extended_answer', 'Extended Answer (written)'),
            ],
            'validation_types': [
                ('auto', 'Auto (system checks)'),
                ('ai_graded', 'AI Graded (Claude evaluates)'),
                ('human_graded', 'Human Graded (teacher reviews)'),
            ],
        })

    def post(self, request, session_id):
        """Save teacher edits and redirect to confirm step."""
        from .models import HomeworkUploadSession
        session = get_object_or_404(
            HomeworkUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data

        # Homework title and classroom
        hw_title = request.POST.get('homework_title', '').strip()
        if hw_title:
            session.homework_title = hw_title

        classroom_id = request.POST.get('classroom_id', '')
        if classroom_id:
            try:
                classroom = ClassRoom.objects.get(id=classroom_id)
                _check_teacher_owns_class(request, classroom)
                session.classroom = classroom
            except (ClassRoom.DoesNotExist, Exception):
                pass

        data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))
        data['topic'] = request.POST.get('topic', data.get('topic', ''))
        data['strand'] = request.POST.get('strand', data.get('strand', ''))
        data['subject'] = request.POST.get('subject', data.get('subject', 'Mathematics'))

        questions = data.get('questions', [])
        for idx, q in enumerate(questions):
            prefix = f'q_{idx}_'
            q['include'] = request.POST.get(f'{prefix}include') == 'on'
            q['question_text'] = request.POST.get(f'{prefix}text', q.get('question_text', ''))
            q['question_type'] = request.POST.get(f'{prefix}type', q.get('question_type', 'short_answer'))
            q['validation_type'] = request.POST.get(f'{prefix}validation_type', q.get('validation_type', 'auto'))
            q['grading_rubric'] = request.POST.get(f'{prefix}grading_rubric', q.get('grading_rubric', ''))
            q['difficulty'] = int(request.POST.get(f'{prefix}difficulty', q.get('difficulty', 1)))
            q['points'] = int(request.POST.get(f'{prefix}points', q.get('points', 1)))
            q['explanation'] = request.POST.get(f'{prefix}explanation', q.get('explanation', ''))
            q['year_level'] = int(request.POST.get(f'{prefix}year_level', q.get('year_level', data['year_level'])))
            q['subject'] = request.POST.get(f'{prefix}subject', q.get('subject', data['subject']))
            q['strand'] = request.POST.get(f'{prefix}strand', q.get('strand', data['strand']))
            q['topic'] = request.POST.get(f'{prefix}topic', q.get('topic', data['topic']))

            img_ref = request.POST.get(f'{prefix}image_ref', '')
            q['image_ref'] = img_ref if img_ref and img_ref != 'none' else None

            answers = []
            for a_idx in range(20):
                a_text = request.POST.get(f'{prefix}answer_{a_idx}_text', '')
                if a_text.strip():
                    answers.append({
                        'text': a_text,
                        'is_correct': request.POST.get(f'{prefix}answer_{a_idx}_correct') == 'on',
                    })
            if answers:
                q['answers'] = answers

        data['questions'] = questions
        session.extracted_data = data
        session.save(update_fields=['extracted_data', 'homework_title', 'classroom'])

        return redirect('homework:pdf_confirm', session_id=session.pk)


class HomeworkPDFConfirmView(RoleRequiredMixin, View):
    """Step 3 — create Homework + questions in DB and notify students."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/upload_confirm.html'

    def get(self, request, session_id):
        from .models import HomeworkUploadSession
        session = get_object_or_404(
            HomeworkUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data
        included = [q for q in data.get('questions', []) if q.get('include', True)]
        excluded_count = len(data.get('questions', [])) - len(included)

        # Count by validation type for the summary
        auto_count = sum(1 for q in included if q.get('validation_type', 'auto') == 'auto')
        ai_count = sum(1 for q in included if q.get('validation_type') == 'ai_graded')
        human_count = sum(1 for q in included if q.get('validation_type') == 'human_graded')

        from classroom.models import ClassRoom
        classrooms = _teacher_classrooms(request.user)

        return render(request, self.template_name, {
            'session': session,
            'included_count': len(included),
            'excluded_count': excluded_count,
            'total_count': len(data.get('questions', [])),
            'auto_count': auto_count,
            'ai_count': ai_count,
            'human_count': human_count,
            'classrooms': classrooms,
        })

    def post(self, request, session_id):
        from .models import HomeworkUploadSession
        from billing.entitlements import get_school_for_user

        session = get_object_or_404(
            HomeworkUploadSession, pk=session_id, user=request.user, is_confirmed=False,
        )

        hw_title = request.POST.get('homework_title', '').strip() or session.homework_title or session.pdf_filename
        due_date_str = request.POST.get('due_date', '')
        max_attempts_str = request.POST.get('max_attempts', '')
        classroom_id = request.POST.get('classroom_id', '')

        # Classroom — required
        classroom = session.classroom
        if classroom_id:
            try:
                classroom = ClassRoom.objects.get(id=classroom_id)
                _check_teacher_owns_class(request, classroom)
            except (ClassRoom.DoesNotExist, Exception):
                pass

        if not classroom:
            messages.error(request, 'Please select a classroom.')
            return redirect('homework:pdf_confirm', session_id=session.pk)

        if not due_date_str:
            messages.error(request, 'Please enter a due date.')
            return redirect('homework:pdf_confirm', session_id=session.pk)

        from django.utils.dateparse import parse_datetime, parse_date
        from django.utils import timezone as tz
        due_date = parse_datetime(due_date_str)
        if due_date is None:
            d = parse_date(due_date_str)
            if d:
                from datetime import datetime
                due_date = datetime.combine(d, datetime.max.time().replace(hour=23, minute=59))
                due_date = tz.make_aware(due_date)
        if due_date is None:
            messages.error(request, 'Invalid due date format.')
            return redirect('homework:pdf_confirm', session_id=session.pk)

        max_attempts = None
        if max_attempts_str.strip():
            try:
                max_attempts = int(max_attempts_str)
            except ValueError:
                pass

        data = session.extracted_data
        questions_data = [q for q in data.get('questions', []) if q.get('include', True)]

        if not questions_data:
            messages.error(request, 'No questions included. Please go back and include at least one question.')
            return redirect('homework:pdf_preview', session_id=session.pk)

        school = get_school_for_user(request.user)

        with transaction.atomic():
            # 1. Save questions to maths.Question + maths.Answer
            saved_questions = _save_homework_pdf_questions(questions_data, data, request.user, school, session)

            if not saved_questions:
                messages.error(request, 'Failed to save questions. Please try again.')
                return redirect('homework:pdf_preview', session_id=session.pk)

            # 2. Create Homework record
            homework = Homework.objects.create(
                classroom=classroom,
                created_by=request.user,
                title=hw_title,
                homework_type='pdf_upload',
                num_questions=len(saved_questions),
                due_date=due_date,
                max_attempts=max_attempts,
            )

            # 3. Link HomeworkQuestions
            HomeworkQuestion.objects.bulk_create([
                HomeworkQuestion(homework=homework, question=q, order=i)
                for i, q in enumerate(saved_questions, 1)
            ])

            # 4. Mark session confirmed
            session.is_confirmed = True
            session.homework = homework
            session.save(update_fields=['is_confirmed', 'homework'])

        # Notify students
        homework_url = reverse('homework:student_take', kwargs={'homework_id': homework.id})
        due_str = homework.due_date.strftime('%d %b %Y')
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

        messages.success(
            request,
            f'Homework "{homework.title}" created with {len(saved_questions)} questions and assigned to {classroom.name}.',
        )
        return redirect('homework:teacher_detail', homework_id=homework.id)


def _save_homework_pdf_questions(questions_data, global_data, user, school, session):
    """
    Save AI-extracted homework questions as maths.Question + maths.Answer records.

    Returns a list of Question objects in order.
    """
    from maths.models import Question as MQ, Answer as MA
    from classroom.models import Topic, Level, Subject
    from classroom.views import _get_question_scope

    school_id, dept_id, _ = _get_question_scope(user)
    saved = []

    for q in questions_data:
        q_text = q.get('question_text', '').strip()
        if not q_text:
            continue

        # Resolve level
        yl = q.get('year_level') or global_data.get('year_level', 1)
        try:
            level = Level.objects.get(level_number=int(yl))
        except Level.DoesNotExist:
            level = Level.objects.order_by('level_number').first()
        if not level:
            continue

        # Resolve topic
        topic_name = (q.get('topic') or global_data.get('topic', '')).strip()
        subject_name = (q.get('subject') or global_data.get('subject', 'Mathematics')).strip()
        try:
            subject = Subject.objects.get(name__iexact=subject_name)
        except Subject.DoesNotExist:
            subject = Subject.objects.first()

        topic = None
        if topic_name:
            topic = Topic.objects.filter(name__iexact=topic_name, subject=subject).first()
        if not topic:
            topic = Topic.objects.filter(subject=subject).first()
        if not topic:
            continue

        # Determine validation type — downgrade to 'auto' for non-extended types
        q_type = q.get('question_type', 'short_answer')
        validation_type = q.get('validation_type', 'auto')
        if q_type != MQ.EXTENDED_ANSWER and validation_type != 'auto':
            # MCQ/T-F etc. should always be auto
            validation_type = 'auto'
        if q_type == MQ.EXTENDED_ANSWER and validation_type == 'auto':
            # Default extended answers to AI graded
            validation_type = 'ai_graded'

        grading_rubric = q.get('grading_rubric', '')

        # Map question_type to model constant
        type_map = {
            'multiple_choice': MQ.MULTIPLE_CHOICE,
            'true_false': MQ.TRUE_FALSE,
            'short_answer': MQ.SHORT_ANSWER,
            'fill_blank': MQ.FILL_BLANK,
            'calculation': MQ.CALCULATION if hasattr(MQ, 'CALCULATION') else MQ.SHORT_ANSWER,
            'extended_answer': MQ.EXTENDED_ANSWER,
        }
        mapped_type = type_map.get(q_type, MQ.SHORT_ANSWER)

        # Create or get question (avoid exact duplicates within same topic/level)
        mq, created = MQ.objects.get_or_create(
            question_text=q_text,
            topic=topic,
            level=level,
            school_id=school_id,
            defaults={
                'question_type': mapped_type,
                'validation_type': validation_type,
                'grading_rubric': grading_rubric,
                'difficulty': q.get('difficulty', 1),
                'points': q.get('points', 1),
                'explanation': q.get('explanation', ''),
                'is_active': True,
                'department_id': dept_id,
            },
        )

        if not created and validation_type != 'auto':
            # Update rubric in case teacher edited it
            mq.validation_type = validation_type
            mq.grading_rubric = grading_rubric
            mq.save(update_fields=['validation_type', 'grading_rubric'])

        # Save image file if this question has one and it was just created
        if created:
            image_ref = q.get('image_ref')
            image_b64 = session.extracted_images.get(image_ref) if image_ref else None
            if image_b64:
                try:
                    import base64
                    import os
                    from django.conf import settings
                    topic_slug = topic.slug if hasattr(topic, 'slug') else str(topic.id)
                    img_dir = os.path.join(
                        settings.MEDIA_ROOT, 'questions', f'year{yl}', topic_slug,
                    )
                    os.makedirs(img_dir, exist_ok=True)
                    img_path = os.path.join(img_dir, image_ref)
                    with open(img_path, 'wb') as f:
                        f.write(base64.b64decode(image_b64))
                    mq.image = os.path.join('questions', f'year{yl}', topic_slug, image_ref)
                    mq.save(update_fields=['image'])
                except Exception:
                    pass  # Image saving is best-effort

        # Save answers (skip for extended_answer)
        if mapped_type != MQ.EXTENDED_ANSWER:
            answers_data = q.get('answers', [])
            if answers_data and created:
                MA.objects.bulk_create([
                    MA(
                        question=mq,
                        answer_text=a.get('text', ''),
                        is_correct=a.get('is_correct', False),
                    )
                    for a in answers_data
                    if a.get('text', '').strip()
                ])

        saved.append(mq)

    return saved


# ---------------------------------------------------------------------------
# Teacher: AI Grading Review
# ---------------------------------------------------------------------------

class HomeworkPendingReviewView(RoleRequiredMixin, View):
    """Dashboard showing answers pending AI or teacher review."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/pending_review.html'

    def get(self, request):
        classrooms = _teacher_classrooms(request.user)
        classroom_id = request.GET.get('classroom')

        selected_classroom = None
        if classroom_id:
            try:
                selected_classroom = classrooms.get(id=classroom_id)
            except ClassRoom.DoesNotExist:
                pass
        if not selected_classroom:
            selected_classroom = classrooms.first()

        pending_answers = []
        if selected_classroom:
            homework_ids = Homework.objects.filter(
                classroom=selected_classroom,
            ).values_list('id', flat=True)

            pending_answers = (
                HomeworkStudentAnswer.objects
                .filter(
                    submission__homework_id__in=homework_ids,
                    review_status__in=[
                        HomeworkStudentAnswer.REVIEW_PENDING_AI,
                        HomeworkStudentAnswer.REVIEW_PENDING_TEACHER,
                        HomeworkStudentAnswer.REVIEW_AI_DONE,
                    ],
                )
                .select_related(
                    'submission__student',
                    'submission__homework',
                    'question',
                )
                .order_by('submission__homework__title', 'submission__student__first_name')
            )

        return render(request, self.template_name, {
            'classrooms': classrooms,
            'selected_classroom': selected_classroom,
            'pending_answers': pending_answers,
        })


class HomeworkAIGradeView(RoleRequiredMixin, View):
    """Trigger AI grading for a specific pending answer (HTMX or POST)."""
    required_roles = TEACHER_ROLES

    def post(self, request, answer_id):
        answer = get_object_or_404(HomeworkStudentAnswer, pk=answer_id)
        _check_teacher_owns_class(request, answer.submission.homework.classroom)

        from worksheets.grading_service import grade_extended_answer
        from billing.entitlements import get_school_for_user
        from django.utils import timezone

        school = get_school_for_user(request.user)
        try:
            result = grade_extended_answer(answer.question, answer.text_answer, school=school)
            answer.is_correct = result.get('is_correct', False)
            answer.ai_score_fraction = result.get('score_fraction', 0.0)
            answer.ai_feedback = result.get('feedback', '')
            answer.points_earned = round(answer.question.points * answer.ai_score_fraction, 2)
            answer.review_status = HomeworkStudentAnswer.REVIEW_AI_DONE
            answer.graded_at = timezone.now()
            answer.save(update_fields=[
                'is_correct', 'ai_score_fraction', 'ai_feedback',
                'points_earned', 'review_status', 'graded_at',
            ])
            _recalculate_submission_score(answer.submission)
            messages.success(request, 'AI grading complete.')
        except Exception as e:
            messages.error(request, f'AI grading failed: {e}')

        return redirect('homework:pending_review')


class HomeworkGradeAnswerView(RoleRequiredMixin, View):
    """Teacher manually overrides grade for a student answer."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/grade_answer.html'

    def get(self, request, answer_id):
        answer = get_object_or_404(HomeworkStudentAnswer, pk=answer_id)
        _check_teacher_owns_class(request, answer.submission.homework.classroom)
        return render(request, self.template_name, {'answer': answer})

    def post(self, request, answer_id):
        answer = get_object_or_404(HomeworkStudentAnswer, pk=answer_id)
        _check_teacher_owns_class(request, answer.submission.homework.classroom)

        from django.utils import timezone

        score_pct = float(request.POST.get('score_pct', 0))
        score_frac = max(0.0, min(1.0, score_pct / 100))
        teacher_feedback = request.POST.get('teacher_feedback', '').strip()

        answer.ai_score_fraction = score_frac
        answer.is_correct = score_frac >= 0.6
        answer.points_earned = round(answer.question.points * score_frac, 2)
        answer.teacher_feedback = teacher_feedback
        answer.review_status = HomeworkStudentAnswer.REVIEW_TEACHER_DONE
        answer.graded_by = request.user
        answer.graded_at = timezone.now()
        answer.save(update_fields=[
            'ai_score_fraction', 'is_correct', 'points_earned',
            'teacher_feedback', 'review_status', 'graded_by', 'graded_at',
        ])
        _recalculate_submission_score(answer.submission)

        messages.success(request, 'Answer graded successfully.')
        next_url = request.POST.get('next', '')
        if next_url:
            return redirect(next_url)
        return redirect('homework:pending_review')
