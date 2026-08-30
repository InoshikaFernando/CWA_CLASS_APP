"""
Teacher-facing views for the question-automation schedule (CPP-399).

Access is the same scope as managing a class's homework — class teacher, head
of department, head of institute / school admin — by reusing
``homework.views._check_teacher_owns_class`` rather than re-deriving the rule.
A second, subtly different permission check is how a teacher ends up able to
edit a plan for a class whose homework they cannot see.
"""

from django.contrib import messages
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View

from audit.services import log_event
from classroom.models import ClassRoom
from classroom.subject_registry import get as get_plugin, homework_subject_choices
from classroom.views import RoleRequiredMixin

from . import schedule_services as svc
from .forms_schedule import QuestionScheduleForm, ScheduleWeekForm
from .models import QuestionSchedule, ScheduleWeek
from .views import _check_teacher_owns_class, _teacher_classrooms

TEACHER_ROLES = ['teacher', 'senior_teacher', 'junior_teacher']


def _get_schedule(request, schedule_id):
    """Fetch a schedule the requesting user is allowed to manage, or 404."""
    schedule = get_object_or_404(
        QuestionSchedule.objects.select_related('classroom', 'classroom__school'),
        pk=schedule_id,
    )
    _check_teacher_owns_class(request, schedule.classroom)
    return schedule


def _plugin_for(schedule_or_slug):
    slug = getattr(schedule_or_slug, 'subject_slug', schedule_or_slug)
    plugin = get_plugin(slug)
    if plugin is None or not plugin.supports_homework:
        plugin = get_plugin('mathematics')
    return plugin


class ClassScheduleListView(RoleRequiredMixin, View):
    """Every schedule a class has, across subjects."""

    required_roles = TEACHER_ROLES
    template_name = 'homework/schedule_list.html'

    def get(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        _check_teacher_owns_class(request, classroom)
        schedules = (
            QuestionSchedule.objects
            .filter(classroom=classroom)
            .prefetch_related('weeks')
        )
        return render(request, self.template_name, {
            'classroom': classroom,
            'schedules': schedules,
            'subject_choices': homework_subject_choices(),
        })


class ScheduleCreateView(RoleRequiredMixin, View):
    """Create a plan, then build its week rows straight away.

    The weeks are built on save rather than lazily, so the teacher lands on a
    grid they can fill in immediately instead of an empty page with a
    "generate weeks" button they have to know to press.
    """

    required_roles = TEACHER_ROLES
    template_name = 'homework/schedule_form.html'

    def _subject_slug(self, request):
        slug = (request.POST.get('subject_slug') if request.method == 'POST'
                else request.GET.get('subject_slug')) or 'mathematics'
        return _plugin_for(slug).slug

    def get(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        _check_teacher_owns_class(request, classroom)
        slug = self._subject_slug(request)
        plugin = _plugin_for(slug)
        form = QuestionScheduleForm(classroom=classroom, plugin=plugin)
        return render(request, self.template_name, {
            'classroom': classroom,
            'form': form,
            'selected_subject_slug': slug,
            'subject_choices': homework_subject_choices(),
            'is_create': True,
        })

    def post(self, request, classroom_id):
        classroom = get_object_or_404(ClassRoom, pk=classroom_id)
        _check_teacher_owns_class(request, classroom)
        slug = self._subject_slug(request)
        plugin = _plugin_for(slug)

        schedule = QuestionSchedule(classroom=classroom, subject_slug=slug)
        form = QuestionScheduleForm(
            request.POST, instance=schedule, classroom=classroom, plugin=plugin,
        )
        if not form.is_valid():
            return render(request, self.template_name, {
                'classroom': classroom,
                'form': form,
                'selected_subject_slug': slug,
                'subject_choices': homework_subject_choices(),
                'is_create': True,
            })

        with transaction.atomic():
            schedule = form.save(commit=False)
            schedule.classroom = classroom
            schedule.subject_slug = slug
            schedule.created_by = request.user
            schedule.start_date = form.cleaned_data['start_date']
            schedule.end_date = form.cleaned_data['end_date']
            schedule.save()
            built = svc.build_weeks(schedule)

        log_event(
            user=request.user, school=classroom.school, category='data_change',
            action='question_schedule_created',
            detail={
                'schedule_id': schedule.pk, 'name': schedule.name,
                'classroom_id': classroom.pk, 'subject_slug': slug,
                'scope': schedule.scope,
                'start_date': str(schedule.start_date),
                'end_date': str(schedule.end_date),
                'weeks_built': built['created'], 'weeks_skipped': built['skipped'],
            },
            request=request,
        )
        note = f'Schedule "{schedule.name}" created with {built["created"]} week(s).'
        if built['skipped']:
            note += (f' {built["skipped"]} week(s) fall in holidays and were '
                     f'switched off — turn any of them back on if you do teach then.')
        messages.success(request, note)
        return redirect('homework:schedule_detail', schedule_id=schedule.pk)


class ScheduleEditView(RoleRequiredMixin, View):
    """Edit a plan's period or cadence, then rebuild its weeks non-destructively."""

    required_roles = TEACHER_ROLES
    template_name = 'homework/schedule_form.html'

    def get(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        form = QuestionScheduleForm(
            instance=schedule, classroom=schedule.classroom,
            plugin=_plugin_for(schedule),
        )
        return render(request, self.template_name, {
            'classroom': schedule.classroom,
            'schedule': schedule,
            'form': form,
            'selected_subject_slug': schedule.subject_slug,
            'subject_choices': homework_subject_choices(),
            'is_create': False,
        })

    def post(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        form = QuestionScheduleForm(
            request.POST, instance=schedule, classroom=schedule.classroom,
            plugin=_plugin_for(schedule),
        )
        if not form.is_valid():
            return render(request, self.template_name, {
                'classroom': schedule.classroom,
                'schedule': schedule,
                'form': form,
                'selected_subject_slug': schedule.subject_slug,
                'subject_choices': homework_subject_choices(),
                'is_create': False,
            })
        with transaction.atomic():
            schedule = form.save(commit=False)
            schedule.start_date = form.cleaned_data['start_date']
            schedule.end_date = form.cleaned_data['end_date']
            schedule.save()
            built = svc.build_weeks(schedule)
        messages.success(
            request,
            f'Schedule updated — {built["created"]} week(s) added, '
            f'{built["removed"]} removed. Existing topic selections were kept.',
        )
        return redirect('homework:schedule_detail', schedule_id=schedule.pk)


class ScheduleDetailView(RoleRequiredMixin, View):
    """The week grid — the screen where the teaching plan is actually entered."""

    required_roles = TEACHER_ROLES
    template_name = 'homework/schedule_detail.html'

    def get(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        plugin = _plugin_for(schedule)
        weeks = list(
            schedule.weeks.select_related('generated_homework').all()
        )
        topic_groups = plugin.homework_topic_tree(schedule.classroom)

        # Every selectable topic on the page, plus anything a week already has
        # planned (a topic can drop out of the tree once its questions are
        # withdrawn, and that week still needs a truthful count of zero).
        selectable_ids = _selectable_topic_ids(topic_groups)
        planned_ids = {tid for w in weeks for tid in (w.topic_ids or [])}
        all_ids = selectable_ids | planned_ids

        # Two plugin calls for the whole grid rather than one per week — a
        # year-long plan is 40+ rows over the same topic tree.
        labels = plugin.topic_labels(all_ids) if all_ids else {}
        total_by_topic, fresh_by_topic = svc.topic_counts_for_schedule(
            schedule, all_ids,
        )

        for week in weeks:
            stored = dict(zip(week.topic_ids or [], week.topic_labels or []))
            week.display_labels = [
                labels.get(tid) or stored.get(tid) or f'Topic #{tid} (removed)'
                for tid in (week.topic_ids or [])
            ]
            week.release_on = svc.release_date_for(
                week.week_start_date, schedule.release_weekday,
            )
            week.coverage = svc.coverage_for(week, total_by_topic, fresh_by_topic)

        # Counts are attached to the tree's leaves so the template can label
        # each checkbox and the page's JS can re-total a week live as boxes are
        # ticked, without another request.
        _annotate_counts(topic_groups, total_by_topic, fresh_by_topic)

        return render(request, self.template_name, {
            'schedule': schedule,
            'classroom': schedule.classroom,
            'weeks': weeks,
            'topic_groups': topic_groups,
            'week_form': ScheduleWeekForm(),
            'repeat_window': schedule.avoid_repeat_weeks,
            'copy_targets': (
                _teacher_classrooms(request.user).exclude(pk=schedule.classroom_id)
            ),
        })


def _selectable_topic_ids(topic_groups):
    """Every pk a teacher can actually tick in the rendered topic tree.

    The tree is ``[(strand, [(mid, [leaf, ...]), ...]), ...]`` and a checkbox is
    rendered for a leaf, for a mid with no leaves, or for a strand with no mids
    — so all three shapes are collected here, matching the template exactly.
    """
    ids = set()
    for strand, mid_items in topic_groups:
        if not mid_items:
            ids.add(strand.pk)
            continue
        for mid, leaves in mid_items:
            if leaves:
                ids.update(leaf.pk for leaf in leaves)
            else:
                ids.add(mid.pk)
    return ids


def _annotate_counts(topic_groups, total_by_topic, fresh_by_topic):
    """Hang ``total_count`` / ``fresh_count`` on each selectable tree node."""
    def mark(node):
        node.total_count = total_by_topic.get(node.pk, 0)
        node.fresh_count = fresh_by_topic.get(node.pk, 0)

    for strand, mid_items in topic_groups:
        if not mid_items:
            mark(strand)
            continue
        for mid, leaves in mid_items:
            if leaves:
                for leaf in leaves:
                    mark(leaf)
            else:
                mark(mid)


class ScheduleWeekSaveView(RoleRequiredMixin, View):
    """Save one week's topic plan."""

    required_roles = TEACHER_ROLES

    def post(self, request, schedule_id, week_id):
        schedule = _get_schedule(request, schedule_id)
        week = get_object_or_404(ScheduleWeek, pk=week_id, schedule=schedule)

        raw = request.POST.getlist('topic_ids')
        week.topic_ids = [int(v) for v in raw if str(v).lstrip('-').isdigit()]
        week.topic_labels = svc.refresh_topic_labels(week)

        form = ScheduleWeekForm(request.POST, instance=week)
        if not form.is_valid():
            messages.error(request, 'Could not save that week — check the values.')
            return redirect('homework:schedule_detail', schedule_id=schedule.pk)
        week = form.save(commit=False)
        # A teacher who re-enables a holiday week has overridden the reason, so
        # drop it rather than leaving a stale "School holiday" label on a week
        # that is now running.
        if week.is_active and week.skip_reason:
            week.skip_reason = ''
        week.save()
        messages.success(
            request,
            f'Week {week.week_number} saved with {len(week.topic_ids)} topic(s).',
        )
        return redirect(
            reverse('homework:schedule_detail', kwargs={'schedule_id': schedule.pk})
            + f'#week-{week.week_number}'
        )


class ScheduleWeekGenerateView(RoleRequiredMixin, View):
    """Build one week's homework now, ahead of its lead time.

    Same service call the nightly command makes, with ``force`` set only for
    the lead-time check — the idempotency guard and the active flags still
    apply, so this can never produce a duplicate set.
    """

    required_roles = TEACHER_ROLES

    def post(self, request, schedule_id, week_id):
        schedule = _get_schedule(request, schedule_id)
        week = get_object_or_404(ScheduleWeek, pk=week_id, schedule=schedule)

        result = svc.generate_week(week, force=True)
        if result.created:
            messages.success(
                request,
                f'Week {week.week_number} generated — '
                f'"{result.homework.title}" will publish on '
                f'{result.homework.publish_at:%d %b %Y %H:%M}. '
                + (result.message or ''),
            )
            return redirect('homework:teacher_detail', homework_id=result.homework.pk)

        messages.warning(
            request,
            f'Week {week.week_number} was not generated: {result.message}',
        )
        return redirect('homework:schedule_detail', schedule_id=schedule.pk)


class ScheduleToggleView(RoleRequiredMixin, View):
    """Pause or resume a plan without deleting it."""

    required_roles = TEACHER_ROLES

    def post(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        schedule.is_active = not schedule.is_active
        schedule.save(update_fields=['is_active', 'updated_at'])
        messages.success(
            request,
            f'Schedule "{schedule.name}" '
            + ('resumed.' if schedule.is_active else 'paused — no new sets will be generated.'),
        )
        return redirect('homework:schedule_detail', schedule_id=schedule.pk)


class ScheduleDeleteView(RoleRequiredMixin, View):
    """Delete a plan. Homework it already generated is left alone.

    ``ScheduleWeek.generated_homework`` is ``SET_NULL`` on the homework side and
    the weeks cascade off the schedule, so deleting a plan removes the plan and
    nothing a student has ever seen.
    """

    required_roles = TEACHER_ROLES

    def post(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        classroom_id = schedule.classroom_id
        name = schedule.name
        log_event(
            user=request.user, school=schedule.classroom.school,
            category='data_change', action='question_schedule_deleted',
            detail={'schedule_id': schedule.pk, 'name': name,
                    'classroom_id': classroom_id},
            request=request,
        )
        schedule.delete()
        messages.success(
            request,
            f'Schedule "{name}" deleted. Homework it had already created is untouched.',
        )
        return redirect('homework:schedule_list', classroom_id=classroom_id)


class ScheduleCopyView(RoleRequiredMixin, View):
    """Copy a plan onto another class the teacher manages."""

    required_roles = TEACHER_ROLES

    def post(self, request, schedule_id):
        schedule = _get_schedule(request, schedule_id)
        target_id = request.POST.get('target_classroom')
        target = _teacher_classrooms(request.user).filter(pk=target_id).first()
        if target is None and request.user.is_superuser:
            target = ClassRoom.objects.filter(pk=target_id).first()
        if target is None:
            raise Http404

        clone = svc.copy_schedule(schedule, target, request.user)
        log_event(
            user=request.user, school=target.school, category='data_change',
            action='question_schedule_copied',
            detail={'source_schedule_id': schedule.pk, 'new_schedule_id': clone.pk,
                    'target_classroom_id': target.pk},
            request=request,
        )
        messages.success(
            request,
            f'Copied to {target.name} as "{clone.name}". It is paused — review '
            f'the weeks and resume it when you are ready.',
        )
        return redirect('homework:schedule_detail', schedule_id=clone.pk)
