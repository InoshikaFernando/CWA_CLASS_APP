import random
import time as time_module

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Max, Prefetch
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from audit.services import log_event
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

        log_event(
            user=request.user,
            school=classroom.school,
            category='data_change',
            action='homework_created',
            detail={
                'homework_id': homework.id,
                'title': homework.title,
                'classroom_id': classroom.id,
                'classroom_name': classroom.name,
                'subject_slug': homework.subject_slug,
                'num_questions': count,
                'due_date': str(homework.due_date) if homework.due_date else None,
                'max_attempts': homework.max_attempts,
            },
            request=request,
        )

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
# Assign existing homework to another class
# ---------------------------------------------------------------------------

class HomeworkAssignToClassView(LoginRequiredMixin, View):
    """
    Copy an existing homework to one or more additional classrooms.
    Reuses the exact same HomeworkQuestion records (same question PKs)
    so the AIGradingCache is shared — answers from any class help
    grade all other classes using the same homework.
    """

    def get(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)

        # Classrooms this teacher owns, excluding the homework's current class
        my_classrooms = _teacher_classrooms(request.user).exclude(
            id=homework.classroom_id
        )
        # Which ones already have this homework assigned?
        already_assigned = set(
            Homework.objects
            .filter(
                title=homework.title,
                classroom__in=my_classrooms,
            )
            .values_list('classroom_id', flat=True)
        )

        return render(request, 'homework/assign_to_class.html', {
            'homework': homework,
            'my_classrooms': my_classrooms,
            'already_assigned': already_assigned,
        })

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)

        classroom_ids = request.POST.getlist('classroom_ids')
        if not classroom_ids:
            messages.error(request, 'Please select at least one class.')
            return redirect('homework:assign_to_class', homework_id=homework_id)

        my_classroom_ids = set(
            _teacher_classrooms(request.user).values_list('id', flat=True)
        )
        existing_questions = list(homework.homework_questions.all())
        created = []

        for cid in classroom_ids:
            cid = int(cid)
            if cid not in my_classroom_ids:
                continue
            classroom = ClassRoom.objects.get(pk=cid)

            # Skip if already assigned
            if Homework.objects.filter(title=homework.title, classroom=classroom).exists():
                continue

            # Create new Homework for this classroom, copying all settings
            new_hw = Homework.objects.create(
                classroom=classroom,
                created_by=request.user,
                title=homework.title,
                description=homework.description,
                homework_type=homework.homework_type,
                subject_slug=homework.subject_slug,
                num_questions=homework.num_questions,
                due_date=homework.due_date,
                max_attempts=homework.max_attempts,
            )
            new_hw.topics.set(homework.topics.all())

            # Reuse the SAME HomeworkQuestion records (same question PKs)
            # so AIGradingCache is shared across all classes
            for hq in existing_questions:
                HomeworkQuestion.objects.get_or_create(
                    homework=new_hw,
                    subject_slug=hq.subject_slug,
                    content_id=hq.content_id,
                    defaults={'question': hq.question, 'order': hq.order},
                )

            created.append(classroom.name)

        if created:
            messages.success(
                request,
                f'Homework assigned to: {", ".join(created)}. '
                'All classes share the same grading cache — answers improve accuracy for everyone.'
            )
        else:
            messages.info(request, 'No new classes were assigned.')

        return redirect('homework:teacher_detail', homework_id=homework_id)


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

        has_coding_item = any(item.get('subject_slug') == 'coding' for item in items)

        return render(request, self.template_name, {
            'homework': homework,
            'items': items,
            'attempt_number': attempt_count + 1,
            'has_coding_item': has_coding_item,
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

        # Grade all items OUTSIDE the DB transaction — for coding homework each
        # plugin.grade_answer() hits Piston over HTTP (2–10s per call). Running
        # them in parallel collapses the wall-clock cost to roughly the slowest
        # single call instead of the sum, and keeps the DB transaction short.
        post_data = request.POST
        plugin_lookup = {}
        for hwq in hw_questions:
            if hwq.subject_slug not in plugin_lookup:
                plugin_lookup[hwq.subject_slug] = get_plugin(hwq.subject_slug)

        def _grade(hwq):
            plugin = plugin_lookup.get(hwq.subject_slug)
            if plugin is None:
                return None
            try:
                return plugin.grade_answer(hwq.content_id, post_data)
            except Exception:
                # Never let a per-item failure lose the whole submission —
                # mark the item wrong with zero points so the student still
                # gets a result row.
                return {
                    'is_correct': False,
                    'points_earned': 0,
                    'text_answer': '',
                    'selected_answer_id': None,
                    'question_id': None,
                    'answer_data': {'error': 'grading failed'},
                }

        # Only spin up the thread pool when at least one item needs network
        # grading (coding via Piston). Pure-maths homework is CPU-only and
        # near-instant, so sequential grading is faster (no pool startup) and
        # avoids SQLite-in-memory test issues where each worker thread gets
        # its own empty DB connection.
        needs_threading = any(hwq.subject_slug == 'coding' for hwq in hw_questions)
        if needs_threading:
            # 4 concurrent Piston calls is plenty; more risks overwhelming the
            # local container.
            from concurrent.futures import ThreadPoolExecutor
            max_workers = min(4, max(1, len(hw_questions)))
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                graded_by_index = list(pool.map(_grade, hw_questions))
        else:
            graded_by_index = [_grade(hwq) for hwq in hw_questions]

        score = 0
        total = len(hw_questions)
        answer_records = []
        for hwq, graded in zip(hw_questions, graded_by_index):
            if graded is None:
                continue
            if graded.get('is_correct'):
                score += 1
            answer_records.append(HomeworkStudentAnswer(
                # legacy FK — only populated for maths rows that return a
                # ``question_id``; other subjects leave it as None.
                question_id=graded.get('question_id'),
                selected_answer_id=graded.get('selected_answer_id'),
                text_answer=graded.get('text_answer', ''),
                subject_slug=hwq.subject_slug,
                content_id=hwq.content_id,
                answer_data=graded.get('answer_data', {}),
                is_correct=graded.get('is_correct', False),
                points_earned=graded.get('points_earned', 0),
            ))

        with transaction.atomic():
            submission = HomeworkSubmission.objects.create(
                homework=homework,
                student=request.user,
                attempt_number=HomeworkSubmission.get_next_attempt_number(homework, request.user),
                total_questions=total,
                time_taken_seconds=time_taken,
            )

            # Attach the submission to the pre-built rows (graded outside the
            # transaction by the subject-plugin layer above).
            for row in answer_records:
                row.submission = submission

            # Mark rows that need AI or human grading based on validation_type
            # on the underlying maths.Question (only applicable to maths rows).
            _q_ids = [r.question_id for r in answer_records if r.question_id]
            if _q_ids:
                _vmap = dict(
                    Question.objects.filter(id__in=_q_ids)
                    .values_list('id', 'validation_type')
                )
                for row in answer_records:
                    if row.question_id:
                        vtype = _vmap.get(row.question_id, 'auto')
                        if vtype == Question.VALIDATION_AI:
                            row.review_status = HomeworkStudentAnswer.REVIEW_PENDING_AI
                        elif vtype == Question.VALIDATION_HUMAN:
                            row.review_status = HomeworkStudentAnswer.REVIEW_PENDING_TEACHER

            HomeworkStudentAnswer.objects.bulk_create(answer_records)

            pts = calculate_points(score, total, time_taken)
            submission.score = score
            submission.points = pts
            submission.save(update_fields=['score', 'points'])

        log_event(
            user=request.user,
            school=homework.classroom.school,
            category='data_change',
            action='homework_submitted',
            detail={
                'homework_id': homework.id,
                'homework_title': homework.title,
                'submission_id': submission.id,
                'attempt_number': submission.attempt_number,
                'score': submission.score,
                'total_questions': submission.total_questions,
                'points': float(submission.points) if submission.points else 0,
                'time_taken_seconds': time_taken,
            },
            request=request,
        )

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
        error = request.GET.get('error')
        if error:
            messages.error(request, f'Error processing PDF: {error}')
        return render(request, self.template_name, {'classrooms': classrooms})

    def post(self, request):
        import threading
        from billing.entitlements import get_school_for_user
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

        hw_title = pdf_file.name
        if hw_title.lower().endswith('.pdf'):
            hw_title = hw_title[:-4]

        from .models import HomeworkUploadSession
        from django.core.files.base import ContentFile

        # Read file bytes now — the InMemoryUploadedFile will be GC'd after the request
        pdf_bytes = pdf_file.read()

        existing_topics = list(Topic.objects.filter(
            subject__slug='mathematics',
        ).values('name', 'slug')[:100])
        existing_levels = list(Level.objects.filter(
            level_number__lte=12,
        ).values('level_number', 'display_name'))

        # Create session immediately so we can redirect to the polling page
        session = HomeworkUploadSession.objects.create(
            user=request.user,
            school=school,
            classroom=classroom,
            pdf_filename=pdf_file.name,
            homework_title=hw_title,
            status=HomeworkUploadSession.STATUS_PROCESSING,
        )
        session.pdf_file.save(pdf_file.name, ContentFile(pdf_bytes), save=True)

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='homework_pdf_upload_started',
            detail={
                'session_id': session.pk,
                'pdf_filename': pdf_file.name,
                'classroom_id': classroom.id if classroom else None,
            },
            request=request,
        )

        # Run AI extraction in a background thread so the HTTP response returns immediately
        def _process(session_id, pdf_bytes, existing_topics, existing_levels):
            import django.db
            from worksheets.services import extract_and_classify_worksheet
            from io import BytesIO
            try:
                pdf_io = BytesIO(pdf_bytes)
                pdf_io.name = session.pdf_filename
                output = extract_and_classify_worksheet(pdf_io, existing_topics, existing_levels)
                result = output['result']
                HomeworkUploadSession.objects.filter(pk=session_id).update(
                    extracted_data=result,
                    extracted_images=output['extracted_images'],
                    page_count=output['page_count'],
                    tokens_used=result.get('usage', {}).get('total_tokens', 0),
                    status=HomeworkUploadSession.STATUS_DONE,
                )
            except Exception as e:
                HomeworkUploadSession.objects.filter(pk=session_id).update(
                    status=HomeworkUploadSession.STATUS_ERROR,
                    error_message=str(e),
                )
            finally:
                django.db.connections.close_all()

        t = threading.Thread(target=_process, args=(session.pk, pdf_bytes, existing_topics, existing_levels), daemon=True)
        t.start()

        return redirect('homework:pdf_processing', session_id=session.pk)


class HomeworkPDFProcessingView(RoleRequiredMixin, View):
    """Polling page shown while AI extracts questions in the background."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/upload_processing.html'

    def get(self, request, session_id):
        from .models import HomeworkUploadSession
        session = get_object_or_404(HomeworkUploadSession, pk=session_id, user=request.user)
        return render(request, self.template_name, {'session': session})


class HomeworkPDFStatusView(RoleRequiredMixin, View):
    """HTMX polling endpoint — returns a redirect fragment when processing is done."""
    required_roles = TEACHER_ROLES

    def get(self, request, session_id):
        from .models import HomeworkUploadSession
        session = get_object_or_404(HomeworkUploadSession, pk=session_id, user=request.user)

        if session.status == HomeworkUploadSession.STATUS_DONE:
            # Tell HTMX to navigate to the preview page
            response = HttpResponse(status=204)
            response['HX-Redirect'] = reverse('homework:pdf_preview', args=[session_id])
            return response

        if session.status == HomeworkUploadSession.STATUS_ERROR:
            response = HttpResponse(status=204)
            response['HX-Redirect'] = (
                reverse('homework:pdf_upload') + f'?error={session.error_message[:200]}'
            )
            return response

        # Still processing — return 204 so HTMX keeps polling
        return HttpResponse(status=204)


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

            # Handle image replacement / removal
            if request.POST.get(f'{prefix}remove_image') == 'on':
                q['image_ref'] = None
            elif f'{prefix}image_upload' in request.FILES:
                import base64 as _base64
                import uuid as _uuid
                uploaded = request.FILES[f'{prefix}image_upload']
                new_ref = f'upload_{_uuid.uuid4().hex[:8]}_{uploaded.name}'
                img_b64 = _base64.b64encode(uploaded.read()).decode('utf-8')
                session.extracted_images[new_ref] = img_b64
                q['image_ref'] = new_ref

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
        session.save(update_fields=['extracted_data', 'extracted_images', 'homework_title', 'classroom'])

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
            # bulk_create bypasses save(), so set content_id and subject_slug explicitly
            # — otherwise the back-compat logic in save() never fires and every row
            # gets content_id=0, causing a unique-constraint violation on the second row.
            HomeworkQuestion.objects.bulk_create([
                HomeworkQuestion(
                    homework=homework,
                    question=q,
                    subject_slug='mathematics',
                    content_id=q.pk,
                    order=i,
                )
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

        log_event(
            user=request.user,
            school=school,
            category='data_change',
            action='homework_pdf_created',
            detail={
                'homework_id': homework.id,
                'title': hw_title,
                'session_id': session.pk,
                'classroom_id': classroom.id,
                'classroom_name': classroom.name,
                'question_count': len(saved_questions),
                'due_date': str(due_date),
                'max_attempts': max_attempts,
            },
            request=request,
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
        subject = Subject.objects.filter(name__iexact=subject_name).first()
        if not subject:
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
                'department_id': dept_id,
            },
        )

        if not created and validation_type != 'auto':
            # Update rubric in case teacher edited it
            mq.validation_type = validation_type
            mq.grading_rubric = grading_rubric
            mq.save(update_fields=['validation_type', 'grading_rubric'])

        # Save image to storage (DO Spaces / S3) via Django's ImageField.save()
        # Run when newly created OR when question exists but has no image yet
        # (covers re-uploads after previously broken confirm attempts).
        if (created or not mq.image):
            import logging as _img_log
            _img_logger = _img_log.getLogger('homework')
            image_ref = q.get('image_ref')
            image_b64 = session.extracted_images.get(image_ref) if image_ref else None
            if image_b64:
                try:
                    import base64
                    from django.core.files.base import ContentFile
                    topic_slug = topic.slug if hasattr(topic, 'slug') else str(topic.id)
                    img_bytes = base64.b64decode(image_b64)
                    img_filename = f'year{yl}/{topic_slug}/{image_ref}'
                    mq.image.save(img_filename, ContentFile(img_bytes), save=True)
                    _img_logger.info('Saved question image: %s', mq.image.name)
                except Exception as _exc:
                    _img_logger.error(
                        'Failed to save image for question %s (ref=%s): %s',
                        mq.pk, image_ref, _exc, exc_info=True,
                    )

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
                .exclude(text_answer__isnull=True)
                .exclude(text_answer='')
                .exclude(ai_score_fraction=1.0)
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

            log_event(
                user=request.user,
                school=school,
                category='data_change',
                action='homework_answer_ai_graded',
                detail={
                    'answer_id': answer.pk,
                    'submission_id': answer.submission_id,
                    'student_id': answer.submission.student_id,
                    'homework_id': answer.submission.homework_id,
                    'ai_score_fraction': answer.ai_score_fraction,
                    'is_correct': answer.is_correct,
                    'points_earned': float(answer.points_earned),
                },
                request=request,
            )

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

        # Capture old values for before/after audit trail
        old_data = {
            'review_status': answer.review_status,
            'points_earned': float(answer.points_earned) if answer.points_earned else 0,
            'is_correct': answer.is_correct,
            'ai_score_fraction': float(answer.ai_score_fraction) if answer.ai_score_fraction else 0,
            'teacher_feedback': answer.teacher_feedback or '',
        }

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

        log_event(
            user=request.user,
            school=answer.submission.homework.classroom.school,
            category='data_change',
            action='homework_answer_graded',
            detail={
                'answer_id': answer.pk,
                'submission_id': answer.submission_id,
                'student_id': answer.submission.student_id,
                'homework_id': answer.submission.homework_id,
                'before': old_data,
                'after': {
                    'review_status': answer.review_status,
                    'points_earned': float(answer.points_earned),
                    'is_correct': answer.is_correct,
                    'ai_score_fraction': float(answer.ai_score_fraction),
                    'teacher_feedback': answer.teacher_feedback or '',
                },
            },
            request=request,
        )

        # ── Seed cache + retroactively correct similar answers ────────────
        if answer.question_id and answer.text_answer and answer.text_answer.strip():
            try:
                from worksheets.grading_service import _normalise, _levenshtein_ratio
                from django.utils import timezone as tz

                normalised = _normalise(answer.text_answer)
                feedback = teacher_feedback or answer.ai_feedback or ''

                # 1. Store as golden cache entry
                AIGradingCache.objects.update_or_create(
                    question_id=answer.question_id,
                    normalised_answer=normalised[:500],
                    defaults={
                        'is_correct': answer.is_correct,
                        'score_fraction': score_frac,
                        'feedback': feedback[:500],
                        'human_verified': True,
                    },
                )

                # 2. Retroactively fix other AI-graded answers to the same
                #    question that are similar enough (ratio >= 0.85).
                #    Only update answers still marked ai_graded (not ones a
                #    teacher has already manually reviewed).
                siblings = (
                    HomeworkStudentAnswer.objects
                    .filter(
                        question_id=answer.question_id,
                        review_status=HomeworkStudentAnswer.REVIEW_AI_DONE,
                    )
                    .exclude(pk=answer.pk)
                    .select_related('submission')
                )
                retro_count = 0
                affected_submissions = set()
                for sibling in siblings:
                    if not sibling.text_answer or not sibling.text_answer.strip():
                        continue
                    sib_norm = _normalise(sibling.text_answer)
                    if _levenshtein_ratio(normalised, sib_norm) >= 0.85:
                        sibling.ai_score_fraction = score_frac
                        sibling.is_correct = score_frac >= 0.6
                        sibling.points_earned = round(
                            (sibling.question.points if sibling.question else 1) * score_frac, 2
                        )
                        sibling.ai_feedback = feedback
                        sibling.save(update_fields=[
                            'ai_score_fraction', 'is_correct',
                            'points_earned', 'ai_feedback',
                        ])
                        affected_submissions.add(sibling.submission_id)
                        retro_count += 1

                for sub_id in affected_submissions:
                    try:
                        _recalculate_submission_score(
                            HomeworkSubmission.objects.get(pk=sub_id)
                        )
                    except HomeworkSubmission.DoesNotExist:
                        pass

                if retro_count:
                    messages.info(
                        request,
                        f'{retro_count} other similar answer(s) automatically updated to match your grade.'
                    )
            except Exception:
                pass  # Never block grading if this fails
        # ──────────────────────────────────────────────────────────────────

        messages.success(request, 'Answer graded successfully.')
        next_url = request.POST.get('next', '')
        if next_url:
            return redirect(next_url)
        return redirect('homework:pending_review')
