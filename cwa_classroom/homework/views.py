import json
import random
import time as time_module
from datetime import datetime, time as datetime_time, timedelta

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Max, Prefetch, Q
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

from .forms import HomeworkCreateForm, HomeworkEditForm
from .models import (
    Homework,
    HomeworkDraft,
    HomeworkQuestion,
    HomeworkStudentAnswer,
    HomeworkSubmission,
)
from .services import notify_students_homework_published


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _teacher_classrooms(user):
    """Classrooms a user manages for homework — view, monitor, assign, and grade.

    A plain class teacher manages the classes they personally teach. School
    admins (institute owner / head of institute / school admin) additionally
    manage every class in their school, and a head of department every class in
    the department(s) they head. This mirrors the school-scoping used elsewhere
    (see ``classroom.views_reports._get_all_school_ids``) so an owner who isn't
    listed as a ClassTeacher can still see and run homework for their school.

    Note the scope only *widens* for admin/HoD roles; a plain teacher still sees
    only their own classes.
    """
    from classroom.models import School, SchoolTeacher, Department

    if user.is_superuser:
        return ClassRoom.objects.filter(is_active=True)

    # Classes the user personally teaches.
    taught_ids = set(
        ClassTeacher.objects.filter(teacher=user).values_list('classroom_id', flat=True)
    )

    # Schools the user administers (owner / school admin via School.admin,
    # head of institute via SchoolTeacher.role).
    admin_school_ids = set(
        School.objects.filter(admin=user, is_active=True).values_list('id', flat=True)
    ) | set(
        SchoolTeacher.objects.filter(
            teacher=user, role='head_of_institute', is_active=True,
        ).values_list('school_id', flat=True)
    )

    # Departments the user heads.
    headed_dept_ids = set(
        Department.objects.filter(head=user, is_active=True).values_list('id', flat=True)
    )

    scope = Q(id__in=taught_ids)
    if admin_school_ids:
        scope |= Q(school_id__in=admin_school_ids)
    if headed_dept_ids:
        scope |= Q(department_id__in=headed_dept_ids)

    return ClassRoom.objects.filter(scope, is_active=True).distinct()


# Assigning homework uses the same scope as managing it. Kept as a named alias
# so the PDF-upload call sites read clearly.
def _assignable_classrooms(user):
    return _teacher_classrooms(user)


def _can_view_student_homework(user, student, homework):
    """Whether *user* may view *student*'s saved results for *homework*.

    Allowed for the student themselves, a teacher who manages the homework's
    class, and a parent with an active link to the student.
    """
    if user.is_superuser or user.pk == student.pk:
        return True
    if _teacher_classrooms(user).filter(pk=homework.classroom_id).exists():
        return True
    from classroom.models import ParentStudent
    return ParentStudent.objects.filter(
        parent=user, student=student, is_active=True,
    ).exists()


# NOTE: _topics_with_questions() and _build_topic_groups() used to live here.
# Phase 2 moved them to MathsPlugin so the same contract works for any subject.
# Call plugin.homework_topic_tree(classroom) instead.


def _select_and_save_questions(homework, selected_topic_ids, num_questions, question_type=None):
    """Ask the plugin for content ids, then persist HomeworkQuestion rows.

    Delegates the subject-specific selection to the plugin bound to
    ``homework.subject_slug`` so the same code path works for maths, coding,
    or any future subject. ``question_type`` optionally constrains the
    auto-selection to a single question type (None = any type).
    """
    plugin = get_plugin(homework.subject_slug)
    if plugin is None or not plugin.supports_homework:
        return 0

    content_ids = plugin.pick_homework_items(
        homework.classroom, selected_topic_ids, num_questions,
        question_type=question_type,
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
            'question_type_choices': plugin.homework_question_type_choices(),
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

        # Optional question-type constraint on the auto-selection.
        question_type = (request.POST.get('question_type') or '').strip() or None

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

            count = _select_and_save_questions(
                homework, topic_ids, homework.num_questions, question_type=question_type,
            )

        if count == 0:
            if question_type:
                warning = (
                    'No questions of the selected type were found for these topics. '
                    'Try “All types” or pick different topics.'
                )
            else:
                warning = 'No items found for the selected topics. Please add content first.'
            messages.warning(request, warning)
            homework.delete()
            return render(request, self.template_name, self._base_context(request, classroom, plugin, form))

        # Publish now (blank or past publish_at) vs schedule for later. A
        # scheduled homework stays hidden from students and sends no email
        # until the publish_scheduled_homework command (or a manual "Publish
        # now" click) flips published_at.
        publish_at = form.cleaned_data.get('publish_at')
        publish_now = publish_at is None or publish_at <= timezone.now()
        if publish_now:
            homework.published_at = timezone.now()
            homework.save(update_fields=['published_at', 'updated_at'])
            notify_students_homework_published(homework)
            messages.success(
                request,
                f'Homework "{homework.title}" published with {count} questions.',
            )
        else:
            messages.success(
                request,
                f'Homework "{homework.title}" created with {count} questions — '
                f'scheduled to publish on {publish_at.strftime("%d %b %Y %H:%M")}.',
            )

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
                'publish_at': str(publish_at) if publish_at else None,
                'status': homework.status,
                'max_attempts': homework.max_attempts,
            },
            request=request,
        )

        return redirect('homework:teacher_detail', homework_id=homework.id)


class HomeworkMonitorView(RoleRequiredMixin, View):
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_monitor.html'

    def get(self, request):
        classrooms = _teacher_classrooms(request.user)
        selected_classroom_id = request.GET.get('classroom')

        # "All" is an explicit filter option that shows homework across every
        # class the teacher teaches, and is where the detail page's back button
        # lands (CPP-344). With no param we keep auto-selecting the first class
        # so the "New Homework" shortcut stays available on first visit.
        selected_classroom = None
        show_all = False
        if selected_classroom_id == 'all':
            show_all = True
        elif selected_classroom_id:
            try:
                selected_classroom = classrooms.get(id=selected_classroom_id)
            except (ClassRoom.DoesNotExist, ValueError, TypeError):
                selected_classroom = classrooms.first()
        else:
            selected_classroom = classrooms.first()

        if show_all:
            hw_qs = Homework.objects.filter(classroom__in=classrooms)
        elif selected_classroom:
            hw_qs = Homework.objects.filter(classroom=selected_classroom)
        else:
            hw_qs = Homework.objects.none()

        # Weekly filter. ``week`` is the Monday date (YYYY-MM-DD) of the week to
        # show; we normalise any date in that week back to its Monday so the
        # prev/next links and the published_at window always span a full
        # Monday-to-Sunday week. The week bar is always shown: with no/blank/
        # invalid param we default to the current week (filter active), and the
        # explicit sentinel ``week=all`` shows every week.
        today = timezone.localdate()
        current_week_start = today - timedelta(days=today.weekday())

        week_param = request.GET.get('week')
        all_weeks = week_param == 'all'
        week_start = None
        if not all_weeks:
            if week_param:
                try:
                    picked = datetime.strptime(week_param, '%Y-%m-%d').date()
                    week_start = picked - timedelta(days=picked.weekday())
                except (ValueError, TypeError):
                    week_start = None
            # No / blank / unparseable param defaults to the current week.
            if week_start is None:
                week_start = current_week_start

        # The week the bar displays and navigates from: the selected week, or the
        # current week while "All weeks" is active (so the arrows still work).
        display_week_start = week_start or current_week_start
        week_end = (week_start + timedelta(days=6)) if week_start else None  # Sun
        prev_week = (display_week_start - timedelta(days=7)).isoformat()
        next_week = (display_week_start + timedelta(days=7)).isoformat()

        if week_start is not None:
            # Filter on published_at within [Mon 00:00, next Mon 00:00). Build
            # timezone-aware bounds so the comparison matches stored UTC values.
            # Unpublished (Created/scheduled) homework has no published date, so
            # it isn't subject to the week window — it's always shown so teachers
            # can still find and publish it from the default current-week view.
            start_dt = timezone.make_aware(
                datetime.combine(week_start, datetime_time.min)
            )
            end_dt = timezone.make_aware(
                datetime.combine(week_start + timedelta(days=7), datetime_time.min)
            )
            hw_qs = hw_qs.filter(
                Q(published_at__gte=start_dt, published_at__lt=end_dt)
                | Q(published_at__isnull=True)
            )

        homework_list = (
            hw_qs
            .select_related('classroom')
            .prefetch_related(
                Prefetch('topics', queryset=Topic.objects.select_related('subject', 'parent'))
            )
            .annotate(
                student_count=Count('submissions__student', distinct=True)
            )
            .order_by('-created_at')
        )

        return render(request, self.template_name, {
            'classrooms': classrooms,
            'selected_classroom': selected_classroom,
            'show_all': show_all,
            'homework_list': homework_list,
            'all_weeks': all_weeks,
            'week_start': week_start,
            'week_end': week_end,
            'display_week_start': display_week_start.isoformat(),
            'prev_week': prev_week,
            'next_week': next_week,
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

            # Judge lateness/overdue relative to when this student joined the
            # class. A student who enrolled after the due date is never flagged
            # as late or overdue — the deadline passed before they were a member.
            if best:
                status = best.submission_status_for(cs.joined_at)
            elif homework.is_overdue_for(cs.joined_at):
                status = HomeworkSubmission.STATUS_NOT_SUBMITTED
            else:
                status = 'pending'

            student_rows.append({
                'student': student,
                'best_submission': best,
                'attempt_count': attempt_count,
                'status': status,
            })

        # Order students alphabetically by display name.
        student_rows.sort(
            key=lambda r: (
                r['student'].get_full_name() or r['student'].username
            ).lower()
        )

        # Summary counts (computed here — Django templates can't tally a loop).
        # "Submitted" = anyone with a best submission (on-time or late);
        # "Overdue"   = overdue with nothing submitted.
        submitted_count = sum(1 for r in student_rows if r['best_submission'])
        overdue_count = sum(
            1 for r in student_rows
            if r['status'] == HomeworkSubmission.STATUS_NOT_SUBMITTED
        )

        return render(request, self.template_name, {
            'homework': homework,
            'student_rows': student_rows,
            'submitted_count': submitted_count,
            'overdue_count': overdue_count,
        })


class HomeworkPublishView(RoleRequiredMixin, View):
    """Teacher action to publish a Created/scheduled homework immediately.

    Flips ``published_at`` to now and notifies students via
    ``Homework.publish()``. Idempotent — an already-published homework is left
    alone with a friendly message.
    """
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)

        if homework.is_published:
            messages.info(request, f'"{homework.title}" is already published.')
            return redirect('homework:teacher_detail', homework_id=homework.id)

        homework.publish()

        log_event(
            user=request.user,
            school=homework.classroom.school,
            category='data_change',
            action='homework_published',
            detail={
                'homework_id': homework.id,
                'title': homework.title,
                'classroom_id': homework.classroom_id,
                'classroom_name': homework.classroom.name,
                'manual': True,
            },
            request=request,
        )

        messages.success(request, f'Homework "{homework.title}" published.')
        return redirect('homework:teacher_detail', homework_id=homework.id)


class HomeworkDeleteView(RoleRequiredMixin, View):
    """Soft-delete a homework the current user created.

    Scope is deliberately narrow — only the *creator* may delete, matching
    "as HoI/HoD/Teacher I can delete any homework I added". Anyone else (even a
    co-teacher or admin who can otherwise manage the class) gets a 404, so this
    never becomes a way to wipe another teacher's homework.

    The delete is soft: ``Homework.soft_delete`` only flips ``deleted_at`` so the
    homework vanishes from every list while student submissions and grades are
    preserved (they would cascade-delete on a hard delete).
    """
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']

    def post(self, request, homework_id):
        from django.http import Http404
        homework = get_object_or_404(
            Homework.objects.select_related('classroom'), id=homework_id,
        )
        if homework.created_by_id != request.user.id:
            raise Http404

        title = homework.title
        homework.soft_delete(user=request.user)

        log_event(
            user=request.user,
            school=homework.classroom.school,
            category='data_change',
            action='homework_deleted',
            detail={
                'homework_id': homework.id,
                'title': title,
                'classroom_id': homework.classroom_id,
                'classroom_name': homework.classroom.name,
                'soft_delete': True,
            },
            request=request,
        )

        messages.success(request, f'Homework "{title}" deleted.')
        return redirect('homework:teacher_monitor')


class HomeworkEditView(RoleRequiredMixin, View):
    """Edit a homework's schedule (publish date, due date) and metadata.

    Question selection is left untouched. While a homework is still unpublished
    the teacher can reschedule ``publish_at`` (or blank it to publish now); once
    published the publish field is hidden and only the due date / title / notes
    / attempt cap can change.
    """
    required_roles = ['teacher', 'senior_teacher', 'junior_teacher']
    template_name = 'homework/teacher_edit.html'

    def get(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)
        form = HomeworkEditForm(instance=homework)
        return render(request, self.template_name, {'form': form, 'homework': homework})

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_teacher_owns_class(request, homework.classroom)

        was_published = homework.is_published
        before = {
            'title': homework.title,
            'due_date': str(homework.due_date) if homework.due_date else None,
            'publish_at': str(homework.publish_at) if homework.publish_at else None,
            'max_attempts': homework.max_attempts,
        }

        form = HomeworkEditForm(request.POST, instance=homework)
        if not form.is_valid():
            return render(request, self.template_name, {'form': form, 'homework': homework})

        hw = form.save(commit=False)

        # Decide whether this edit publishes a still-unpublished homework. A
        # blank or past publish_at on an unpublished homework means "publish now";
        # a future publish_at reschedules it. Already-published homework keeps
        # published_at untouched (the publish_at field was dropped from the form).
        publish_now = False
        if not was_published:
            publish_at = form.cleaned_data.get('publish_at')
            publish_now = publish_at is None or publish_at <= timezone.now()
            if publish_now:
                hw.published_at = timezone.now()
                hw.publish_at = None

        hw.save()

        if publish_now:
            notify_students_homework_published(hw)

        log_event(
            user=request.user,
            school=hw.classroom.school,
            category='data_change',
            action='homework_edited',
            detail={
                'homework_id': hw.id,
                'before': before,
                'after': {
                    'title': hw.title,
                    'due_date': str(hw.due_date) if hw.due_date else None,
                    'publish_at': str(hw.publish_at) if hw.publish_at else None,
                    'max_attempts': hw.max_attempts,
                },
                'published_by_edit': publish_now,
                'status': hw.status,
            },
            request=request,
        )

        if publish_now:
            messages.success(request, f'Homework "{hw.title}" updated and published.')
        else:
            messages.success(request, f'Homework "{hw.title}" updated.')
        return redirect('homework:teacher_detail', homework_id=hw.id)


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

            # Create new Homework for this classroom, copying all settings.
            # Carry over the publish lifecycle (publish_at / published_at) so a
            # scheduled homework stays scheduled in the new class instead of
            # being auto-published by Homework.save()'s publish-on-create default.
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
                publish_at=homework.publish_at,
                published_at=homework.published_at,
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
        # Find classrooms the student belongs to, keeping the join date per
        # classroom so "overdue" can be judged relative to when this student
        # actually enrolled (a late joiner never sees pre-join work as overdue).
        memberships = ClassStudent.objects.filter(
            student=request.user, is_active=True
        ).values_list('classroom_id', 'joined_at')
        joined_at_by_class = {cid: joined for cid, joined in memberships}
        class_ids = list(joined_at_by_class.keys())

        homework_qs = (
            Homework.objects
            .filter(classroom_id__in=class_ids, published_at__isnull=False)
            .prefetch_related(
                Prefetch('topics', queryset=Topic.objects.select_related('subject', 'parent'))
            )
            .order_by('due_date')
        )

        # Homework this student has an in-progress (saved-but-not-submitted)
        # draft for, so the list can show a "Resume" affordance.
        draft_hw_ids = set(
            HomeworkDraft.objects
            .filter(student=request.user, homework_id__in=[hw.id for hw in homework_qs])
            .values_list('homework_id', flat=True)
        )

        rows = []
        for hw in homework_qs:
            joined_at = joined_at_by_class.get(hw.classroom_id)
            best = HomeworkSubmission.get_best_submission(hw, request.user)
            attempt_count = HomeworkSubmission.get_attempt_count(hw, request.user)
            # Overdue no longer blocks attempts — only the attempt cap does.
            can_attempt = (
                hw.attempts_unlimited or attempt_count < hw.max_attempts
            )
            is_overdue = hw.is_overdue_for(joined_at)

            if best:
                status = best.submission_status_for(joined_at)
            elif is_overdue:
                status = HomeworkSubmission.STATUS_NOT_SUBMITTED
            else:
                status = 'pending'

            rows.append({
                'homework': hw,
                'best_submission': best,
                'attempt_count': attempt_count,
                'can_attempt': can_attempt,
                'is_overdue': is_overdue,
                'status': status,
                'has_draft': hw.id in draft_hw_ids,
            })

        return render(request, self.template_name, {'rows': rows})


class StudentHomeworkTakeView(LoginRequiredMixin, View):
    template_name = 'homework/student_take.html'

    def get(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_student_enrolled(request, homework.classroom)

        if not homework.is_published:
            messages.error(request, 'This homework is not available yet.')
            return redirect('homework:student_list')

        attempt_count = HomeworkSubmission.get_attempt_count(homework, request.user)
        if not homework.attempts_unlimited and attempt_count >= homework.max_attempts:
            messages.error(request, 'You have used all your attempts for this homework.')
            return redirect('homework:student_list')
        # Past-due homework is intentionally still attemptable — students can
        # complete overdue work; lateness is reflected in the submission status,
        # not enforced as a hard block. Only the attempt cap gates access.

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
        has_maths_item = any(item.get('subject_slug') == 'mathematics' for item in items)

        # If the student saved progress earlier, hand the take page their saved
        # answers + elapsed time so it can restore them client-side. A draft is
        # ungraded and does not consume an attempt — it's purely resume state.
        draft = HomeworkDraft.objects.filter(
            homework=homework, student=request.user,
        ).first()

        return render(request, self.template_name, {
            'homework': homework,
            'items': items,
            'attempt_number': attempt_count + 1,
            'has_coding_item': has_coding_item,
            'has_maths_item': has_maths_item,
            'draft_answers': draft.answers_data if draft else {},
            'draft_time_taken': draft.time_taken_seconds if draft else 0,
            'draft_saved_at': draft.updated_at.isoformat() if draft else '',
        })

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_student_enrolled(request, homework.classroom)

        if not homework.is_published:
            messages.error(request, 'This homework is not available yet.')
            return redirect('homework:student_list')

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

            # The work is now a real submission — drop any saved draft so the
            # student isn't offered a stale "resume" for finished homework.
            HomeworkDraft.objects.filter(
                homework=homework, student=request.user,
            ).delete()

            # Keep only the most recent attempts (with their answers) per the
            # shared attempt-history limit.
            HomeworkSubmission.prune_old_attempts(homework, request.user)

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


class SaveHomeworkProgressView(LoginRequiredMixin, View):
    """AJAX endpoint: checkpoint a student's in-progress answers as a draft.

    Saving progress is deliberately cheap and side-effect-free: it does NOT
    grade anything and does NOT consume an attempt. It upserts the single
    :class:`HomeworkDraft` for (homework, student) so the student can close the
    page and resume later from exactly where they stopped.

    The client posts the answer form fields (the ``answer_<id>`` and
    ``code_<content_id>`` inputs) plus ``time_taken_seconds``; we persist them
    verbatim as a flat JSON map and the take page restores them on next load.
    """

    def post(self, request, homework_id):
        homework = get_object_or_404(Homework, id=homework_id)
        _check_student_enrolled(request, homework.classroom)

        if not homework.is_published:
            return JsonResponse({'ok': False, 'error': 'not_available'}, status=400)

        # Saving a draft is allowed even when the attempt cap is reached — a
        # draft never becomes a submission on its own, so it can't exceed the
        # cap. (The final submit re-checks the cap before grading.)
        try:
            payload = json.loads(request.body or '{}')
        except (ValueError, TypeError):
            return JsonResponse({'ok': False, 'error': 'bad_json'}, status=400)

        answers = payload.get('answers') or {}
        if not isinstance(answers, dict):
            return JsonResponse({'ok': False, 'error': 'bad_answers'}, status=400)

        try:
            time_taken = int(payload.get('time_taken_seconds', 0) or 0)
        except (ValueError, TypeError):
            time_taken = 0

        draft, _ = HomeworkDraft.objects.update_or_create(
            homework=homework,
            student=request.user,
            defaults={
                'answers_data': answers,
                'time_taken_seconds': max(0, time_taken),
            },
        )

        return JsonResponse({
            'ok': True,
            'saved_at': draft.updated_at.isoformat(),
        })


class HomeworkAttemptHistoryView(LoginRequiredMixin, View):
    """List the saved attempts (kept to the last 10) for one homework.

    A student sees their own history; a teacher who manages the class or a
    parent with an active link to the student can view it by passing the
    student id in the URL.
    """
    template_name = 'homework/attempt_history.html'

    def get(self, request, homework_id, student_id=None):
        from django.http import Http404
        homework = get_object_or_404(
            Homework.objects.select_related('classroom'), pk=homework_id,
        )
        if student_id is None:
            student = request.user
        else:
            from django.contrib.auth import get_user_model
            student = get_object_or_404(get_user_model(), pk=student_id)

        if not _can_view_student_homework(request.user, student, homework):
            raise Http404

        submissions = list(
            HomeworkSubmission.objects
            .filter(homework=homework, student=student)
            .order_by('-attempt_number')
        )
        joined_at = (
            ClassStudent.objects
            .filter(student=student, classroom=homework.classroom)
            .values_list('joined_at', flat=True)
            .first()
        )
        for sub in submissions:
            sub.status_for_student = sub.submission_status_for(joined_at)

        return render(request, self.template_name, {
            'homework': homework,
            'student': student,
            'submissions': submissions,
            'viewing_other': student.pk != request.user.pk,
        })


class StudentHomeworkResultView(LoginRequiredMixin, View):
    template_name = 'homework/student_result.html'

    def get(self, request, submission_id):
        from django.http import Http404
        submission = get_object_or_404(
            HomeworkSubmission.objects.select_related('homework__classroom', 'student'),
            id=submission_id,
        )
        if not _can_view_student_homework(request.user, submission.student, submission.homework):
            raise Http404
        viewing_other = submission.student_id != request.user.pk
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

        # Lateness is judged relative to when this student joined the class, and
        # retrying overdue homework is allowed (only the attempt cap gates it) —
        # mirror StudentHomeworkListView so the result page stays consistent.
        hw = submission.homework
        joined_at = (
            ClassStudent.objects
            .filter(student=submission.student, classroom=hw.classroom)
            .values_list('joined_at', flat=True)
            .first()
        )
        attempt_count = HomeworkSubmission.get_attempt_count(hw, submission.student)
        # Only the student who owns the attempt can retry from here.
        can_retry = (not viewing_other) and (
            hw.attempts_unlimited or attempt_count < hw.max_attempts
        )

        return render(request, self.template_name, {
            'submission': submission,
            'submission_status': submission.submission_status_for(joined_at),
            'can_retry': can_retry,
            'review_items': review_items,
            'viewing_other': viewing_other,
            'student': submission.student,
            'attempt_count': attempt_count,
            # Legacy context var kept so any consumer that still iterates
            # `answers` keeps working.
            'answers': answers,
        })


# ---------------------------------------------------------------------------
# Guards
# ---------------------------------------------------------------------------

def _check_teacher_owns_class(request, classroom):
    """Gate managing a class's homework (view, monitor, grade) to its class
    teacher plus school admins/owner/HoI and the department head, matching the
    :func:`_teacher_classrooms` scope.
    """
    if request.user.is_superuser:
        return
    if not _teacher_classrooms(request.user).filter(pk=classroom.pk).exists():
        from django.http import Http404
        raise Http404


# Assigning homework uses the same scope as managing it.
def _check_can_assign_homework(request, classroom):
    return _check_teacher_owns_class(request, classroom)


def _check_student_enrolled(request, classroom):
    if not ClassStudent.objects.filter(student=request.user, classroom=classroom, is_active=True).exists():
        from django.http import Http404
        raise Http404


# Above this many pending AI answers, grading is pushed to a background worker
# so the student isn't blocked while several Claude calls run. Small batches
# (mostly cache hits) stay synchronous for an instant result.
AI_GRADE_ASYNC_THRESHOLD = 3


def _trigger_ai_grading_for_submission(submission, request=None):
    """
    After a submission is saved, grade any answers with review_status='pending_ai'
    using the AI grading service (with caching).

    Small batches grade inline; larger batches are enqueued on the 'high' queue
    so the student's request returns immediately (CPP-307d).
    """
    from billing.entitlements import get_school_for_user

    pending_count = (
        submission.answers
        .filter(review_status=HomeworkStudentAnswer.REVIEW_PENDING_AI)
        .count()
    )
    if not pending_count:
        return

    school = None
    try:
        if request:
            school = get_school_for_user(request.user)
    except Exception:
        pass

    if pending_count > AI_GRADE_ASYNC_THRESHOLD:
        from taskqueue.services import enqueue_task
        from .tasks import grade_submission_answers
        try:
            enqueue_task(
                school=school,
                user=submission.student,
                task_type='ai_grade',
                func=grade_submission_answers,
                args=[submission.pk, school.pk if school else None],
                queue='high',
            )
            return
        except Exception:
            # Queue unavailable — fall back to inline grading rather than
            # 500-ing the student's submission or losing the pending answers.
            import logging
            logging.getLogger(__name__).exception(
                'Failed to enqueue AI grading for submission %s; grading inline',
                submission.pk,
            )

    grade_pending_answers(submission, school)


def grade_pending_answers(submission, school):
    """Grade all pending-AI answers on a submission inline (shared by sync + worker)."""
    from worksheets.grading_service import grade_extended_answer
    from django.utils import timezone

    pending = list(
        submission.answers
        .filter(review_status=HomeworkStudentAnswer.REVIEW_PENDING_AI)
        .select_related('question')
    )
    if not pending:
        return

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
        classrooms = _assignable_classrooms(request.user)
        error = request.GET.get('error')
        if error:
            messages.error(request, f'Error processing PDF: {error}')
        return render(request, self.template_name, {'classrooms': classrooms})

    def post(self, request):
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
                _check_can_assign_homework(request, classroom)
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

        shape_naming = request.POST.get('shape_naming') == 'on'

        # Create session immediately so we can redirect to the polling page
        session = HomeworkUploadSession.objects.create(
            user=request.user,
            school=school,
            classroom=classroom,
            pdf_filename=pdf_file.name,
            homework_title=hw_title,
            shape_naming=shape_naming,
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

        # Enqueue AI extraction on the RQ queue so the response returns immediately
        # and the job survives gunicorn worker restarts (CPP-307c). If the queue
        # is unavailable, surface the error instead of leaving a stuck session.
        from taskqueue.services import enqueue_task
        from .tasks import process_homework_pdf
        try:
            enqueue_task(
                school=school,
                user=request.user,
                task_type='homework_pdf',
                func=process_homework_pdf,
                args=[session.pk, existing_topics, existing_levels],
                queue='default',
            )
        except Exception:
            import logging
            logging.getLogger(__name__).exception(
                'Failed to enqueue homework PDF for session %s', session.pk,
            )
            session.delete()
            messages.error(
                request,
                'The background processing service is temporarily unavailable. '
                'Please try again in a few minutes.',
            )
            return redirect('homework:pdf_upload')

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
        classrooms = _assignable_classrooms(request.user)

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
                ('long_division', 'Long Division'),
                ('column_operation', 'Column Arithmetic'),
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
                _check_can_assign_homework(request, classroom)
                session.classroom = classroom
            except (ClassRoom.DoesNotExist, Exception):
                pass

        data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))
        data['topic'] = request.POST.get('topic', data.get('topic', ''))
        data['strand'] = request.POST.get('strand', data.get('strand', ''))
        data['subject'] = request.POST.get('subject', data.get('subject', 'Mathematics'))

        original_questions = data.get('questions', [])

        def _apply_question_fields(q, idx):
            """Apply this question's posted form fields onto the dict q (in place)."""
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

            # Long-division fields (only relevant for long_division)
            if q['question_type'] == 'long_division':
                for fld in ('dividend', 'divisor'):
                    raw = request.POST.get(f'{prefix}{fld}', '').strip()
                    if raw:
                        try:
                            q[fld] = int(raw)
                        except ValueError:
                            pass

            # Column-arithmetic fields (only relevant for column_operation)
            if q['question_type'] == 'column_operation':
                raw_operands = request.POST.get(f'{prefix}operands', '').strip()
                if raw_operands:
                    try:
                        q['operands'] = [
                            int(tok) for tok in raw_operands.replace(',', ' ').split()
                        ]
                    except ValueError:
                        pass
                op = request.POST.get(f'{prefix}operator', '').strip()
                if op in ('+', '-', '*'):
                    q['operator'] = op

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
            return q

        # `question_order` (CSV of indices) is present when the teacher inserted
        # questions via "Add question below" — it carries the display order and any
        # new indices (>= len(original)). Without it, fall back to the simple 1:1 pass.
        order_raw = request.POST.get('question_order', '').strip()
        if order_raw:
            order = [int(x) for x in order_raw.split(',') if x.strip().isdigit()]
            rebuilt = []
            for i in order:
                base = original_questions[i] if 0 <= i < len(original_questions) else {}
                _apply_question_fields(base, i)
                # Drop a newly-added question the teacher left blank.
                if not (0 <= i < len(original_questions)) and not base.get('question_text', '').strip():
                    continue
                rebuilt.append(base)
            questions = rebuilt
        else:
            questions = original_questions
            for idx, q in enumerate(questions):
                _apply_question_fields(q, idx)

        data['questions'] = questions
        session.extracted_data = data
        session.save(update_fields=['extracted_data', 'extracted_images', 'homework_title', 'classroom'])

        return redirect('homework:pdf_confirm', session_id=session.pk)


class HomeworkPDFConfirmView(RoleRequiredMixin, View):
    """Step 3 — create Homework + questions in DB and notify students."""
    required_roles = TEACHER_ROLES
    template_name = 'homework/upload_confirm.html'

    def _session_or_redirect(self, request, session_id):
        """Fetch the upload session, or redirect if it was already submitted.

        Re-submitting (back button / double-click) an already-confirmed session
        otherwise 404s on the ``is_confirmed=False`` filter. Send the user to the
        homework that was created instead of showing a raw 404.
        """
        from .models import HomeworkUploadSession
        session = get_object_or_404(HomeworkUploadSession, pk=session_id, user=request.user)
        if session.is_confirmed:
            messages.info(request, 'This upload has already been submitted.')
            if session.homework_id:
                return None, redirect('homework:teacher_detail', homework_id=session.homework_id)
            return None, redirect('homework:teacher_monitor')
        return session, None

    def get(self, request, session_id):
        session, redirect_response = self._session_or_redirect(request, session_id)
        if redirect_response:
            return redirect_response
        data = session.extracted_data
        included = [q for q in data.get('questions', []) if q.get('include', True)]
        excluded_count = len(data.get('questions', [])) - len(included)

        # Count by validation type for the summary
        auto_count = sum(1 for q in included if q.get('validation_type', 'auto') == 'auto')
        ai_count = sum(1 for q in included if q.get('validation_type') == 'ai_graded')
        human_count = sum(1 for q in included if q.get('validation_type') == 'human_graded')

        from classroom.models import ClassRoom
        classrooms = _assignable_classrooms(request.user)

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
        from billing.entitlements import get_school_for_user

        session, redirect_response = self._session_or_redirect(request, session_id)
        if redirect_response:
            return redirect_response

        hw_title = request.POST.get('homework_title', '').strip() or session.homework_title or session.pdf_filename
        due_date_str = request.POST.get('due_date', '')
        max_attempts_str = request.POST.get('max_attempts', '')

        # Classroom(s) — required. The confirm step is a multi-select
        # (name="classroom_ids"); fall back to the legacy single field and the
        # session's pre-selected classroom so older requests still work.
        submitted_ids = request.POST.getlist('classroom_ids')
        if not submitted_ids:
            single = request.POST.get('classroom_id', '')
            if single:
                submitted_ids = [single]

        id_set = set()
        for cid in submitted_ids:
            try:
                id_set.add(int(cid))
            except (TypeError, ValueError):
                continue

        assignable = _assignable_classrooms(request.user)
        if id_set:
            # Filter to classes the user may actually assign to, so tampered or
            # stale ids are dropped rather than trusted.
            classrooms = list(assignable.filter(id__in=id_set))
        elif session.classroom and assignable.filter(pk=session.classroom_id).exists():
            # Legacy fallback — still re-checked against current scope in case the
            # user lost access between upload and confirm.
            classrooms = [session.classroom]
        else:
            classrooms = []

        if not classrooms:
            messages.error(request, 'Please select at least one classroom.')
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
        # datetime-local has no tz; the parse_date fallback already made its
        # value aware, but a successful parse_datetime can still be naive.
        if tz.is_naive(due_date):
            due_date = tz.make_aware(due_date)

        max_attempts = None
        if max_attempts_str.strip():
            try:
                max_attempts = int(max_attempts_str)
            except ValueError:
                pass

        # Publish scheduling — blank means publish immediately; a future value
        # schedules it (hidden + no email until the publish_scheduled_homework
        # cron, or a manual "Publish now", flips it live).
        publish_at_str = request.POST.get('publish_at', '').strip()
        publish_at = None
        if publish_at_str:
            publish_at = parse_datetime(publish_at_str)
            if publish_at and tz.is_naive(publish_at):
                publish_at = tz.make_aware(publish_at)
            if publish_at is None:
                messages.error(request, 'Invalid publish date format.')
                return redirect('homework:pdf_confirm', session_id=session.pk)
            if publish_at <= tz.now():
                messages.error(request, 'Publish date must be in the future. Leave it blank to publish now.')
                return redirect('homework:pdf_confirm', session_id=session.pk)
            if publish_at >= due_date:
                messages.error(request, 'Publish date must be before the due date.')
                return redirect('homework:pdf_confirm', session_id=session.pk)

        data = session.extracted_data
        questions_data = [q for q in data.get('questions', []) if q.get('include', True)]

        if not questions_data:
            messages.error(request, 'No questions included. Please go back and include at least one question.')
            return redirect('homework:pdf_preview', session_id=session.pk)

        school = get_school_for_user(request.user)

        created = []  # (homework, classroom) pairs, one per selected class
        with transaction.atomic():
            # 1. Save questions once — they are shared across every class's homework.
            saved_questions = _save_homework_pdf_questions(questions_data, data, request.user, school, session)

            if not saved_questions:
                messages.error(request, 'Failed to save questions. Please try again.')
                return redirect('homework:pdf_preview', session_id=session.pk)

            # Two extracted questions can resolve to the same maths.Question via
            # get_or_create (identical text/topic/level). Drop duplicates so we
            # don't insert two HomeworkQuestion rows with the same content_id,
            # which violates the (homework, subject_slug, content_id) unique key.
            seen_ids = set()
            unique_questions = []
            for q in saved_questions:
                if q.pk not in seen_ids:
                    seen_ids.add(q.pk)
                    unique_questions.append(q)
            saved_questions = unique_questions

            # 2. One Homework per selected class, each linking the same questions.
            for classroom in classrooms:
                homework = Homework.objects.create(
                    classroom=classroom,
                    created_by=request.user,
                    title=hw_title,
                    homework_type='pdf_upload',
                    num_questions=len(saved_questions),
                    due_date=due_date,
                    max_attempts=max_attempts,
                    publish_at=publish_at,  # None → auto-published by save(); future → scheduled
                )
                # bulk_create bypasses save(), so set content_id and subject_slug
                # explicitly — otherwise the back-compat logic never fires and every
                # row gets content_id=0, violating the unique constraint.
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
                created.append((homework, classroom))

            # 3. Mark session confirmed, linking the first homework created.
            session.is_confirmed = True
            session.homework = created[0][0]
            session.save(update_fields=['is_confirmed', 'homework'])

        # Notify students and log an audit entry, per class. Scheduled (not yet
        # published) homework is silent until it goes live — the cron notifies then.
        for homework, classroom in created:
            if homework.is_published:
                notify_students_homework_published(homework)

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
                    'publish_at': str(publish_at) if publish_at else None,
                    'status': homework.status,
                    'max_attempts': max_attempts,
                },
                request=request,
            )

        schedule_note = (
            '' if publish_at is None
            else f' Scheduled to publish on {publish_at.strftime("%d %b %Y %H:%M")}.'
        )

        if len(created) == 1:
            homework, classroom = created[0]
            messages.success(
                request,
                f'Homework "{homework.title}" created with {len(saved_questions)} questions '
                f'and assigned to {classroom.name}.{schedule_note}',
            )
            return redirect('homework:teacher_detail', homework_id=homework.id)

        class_names = ', '.join(classroom.name for _, classroom in created)
        messages.success(
            request,
            f'Homework "{hw_title}" created with {len(saved_questions)} questions and '
            f'assigned to {len(created)} classes: {class_names}.{schedule_note}',
        )
        return redirect('homework:teacher_monitor')


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
            'long_division': MQ.LONG_DIVISION,
            'column_operation': MQ.COLUMN_OPERATION,
        }
        mapped_type = type_map.get(q_type, MQ.SHORT_ANSWER)

        # Long-division: parse dividend/divisor; the answer is computed (not AI-supplied)
        # and the layout is drawn by the app, so any attached image would be noise.
        dividend = divisor = None
        if mapped_type == MQ.LONG_DIVISION:
            try:
                dividend = int(q.get('dividend'))
                divisor = int(q.get('divisor'))
            except (TypeError, ValueError):
                dividend = divisor = None
            if not dividend or not divisor or divisor <= 0:
                # Can't build a valid long-division question — skip it rather than
                # import a broken one with no usable answer.
                continue

        # Column arithmetic: parse operands/operator; the answer is computed (not
        # AI-supplied) and the stacked grid is drawn by the app, so any attached
        # image would be noise.
        operands = None
        operator = ''
        if mapped_type == MQ.COLUMN_OPERATION:
            raw_operands = q.get('operands') or []
            try:
                operands = [int(o) for o in raw_operands]
            except (TypeError, ValueError):
                operands = None
            operator = q.get('operator', '')
            if not operands or len(operands) < 2 or operator not in ('+', '-', '*'):
                # Can't build a valid column-arithmetic question — skip it rather
                # than import a broken one with no usable answer.
                continue

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
                'dividend': dividend,
                'divisor': divisor,
                'operands': operands,
                'operator': operator,
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
        # Long division / column arithmetic draw their own layout from the stored
        # numbers — never attach an image.
        if mapped_type not in (MQ.LONG_DIVISION, MQ.COLUMN_OPERATION) and (created or not mq.image):
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
        if mapped_type == MQ.LONG_DIVISION:
            # Answer is computed from dividend/divisor — ignore any AI-supplied answers.
            if created:
                MA.objects.create(
                    question=mq,
                    answer_text=mq.long_division_answer or '',
                    is_correct=True,
                )
        elif mapped_type == MQ.COLUMN_OPERATION:
            # Answer is computed from operands/operator — ignore any AI-supplied answers.
            if created and mq.column_result is not None:
                MA.objects.create(
                    question=mq,
                    answer_text=str(mq.column_result),
                    is_correct=True,
                )
        elif mapped_type != MQ.EXTENDED_ANSWER:
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
