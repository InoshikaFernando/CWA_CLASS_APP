"""
Worksheet Builder views — CPP-282.

Teachers browse the global question bank with filter panel (subject, topic,
level, free-text search). Question results are loaded via HTMX and paginated.
"""

from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponseBadRequest
from django.shortcuts import render

from accounts.models import Role
from billing.entitlements import get_school_for_user
from classroom.models import Level, Subject, Topic
from classroom.views import RoleRequiredMixin
from django.views import View

from maths.models import Question

PAGE_SIZE = 25

BUILDER_ROLES = [
    Role.INSTITUTE_OWNER,
    Role.HEAD_OF_INSTITUTE,
    Role.HEAD_OF_DEPARTMENT,
    Role.SENIOR_TEACHER,
    Role.TEACHER,
    Role.JUNIOR_TEACHER,
]

DIFFICULTY_LABELS = {1: 'Easy', 2: 'Medium', 3: 'Hard'}


class WorksheetBuilderView(RoleRequiredMixin, View):
    """
    GET /worksheets/builder/

    Renders the full builder page with filter panel.
    Subjects, topics, and levels are passed for client-side topic cascade.
    """
    required_roles = BUILDER_ROLES

    def get(self, request):
        school = get_school_for_user(request.user)

        # All subjects visible to this school (global + school-specific)
        subjects = Subject.objects.filter(
            Q(school__isnull=True) | Q(school=school)
        ).order_by('name')

        # All topics grouped — client-side JS filters by subject
        topics = Topic.objects.filter(
            subject__in=subjects
        ).select_related('subject').order_by('subject__name', 'name')

        levels = Level.objects.filter(level_number__lte=13).order_by('level_number')

        return render(request, 'worksheets/builder.html', {
            'subjects': subjects,
            'topics': topics,
            'levels': levels,
        })


class WorksheetBuilderQuestionsView(RoleRequiredMixin, View):
    """
    GET /worksheets/builder/questions/

    HTMX endpoint — returns _builder_question_list.html partial.
    Query params: subject (slug), topic (id), level (number), q (search), page.
    """
    required_roles = BUILDER_ROLES

    def get(self, request):
        school = get_school_for_user(request.user)

        # Tenant-scoped question queryset: global questions + school's own questions
        qs = Question.objects.filter(
            Q(school__isnull=True) | Q(school=school)
        ).select_related('topic__subject', 'level').order_by('level', 'difficulty', 'pk')

        # --- Filters ---
        subject_slug = request.GET.get('subject', '').strip()
        topic_id = request.GET.get('topic', '').strip()
        level_number = request.GET.get('level', '').strip()
        search = request.GET.get('q', '').strip()

        if subject_slug:
            qs = qs.filter(topic__subject__slug=subject_slug)

        if topic_id:
            try:
                qs = qs.filter(topic_id=int(topic_id))
            except (ValueError, TypeError):
                pass

        if level_number:
            try:
                qs = qs.filter(level__level_number=int(level_number))
            except (ValueError, TypeError):
                pass

        if search:
            qs = qs.filter(question_text__icontains=search)

        # --- Pagination ---
        paginator = Paginator(qs, PAGE_SIZE)
        page_number = request.GET.get('page', 1)
        try:
            page_number = int(page_number)
        except (ValueError, TypeError):
            page_number = 1
        page_obj = paginator.get_page(page_number)

        # Annotate difficulty labels
        for q in page_obj:
            q.difficulty_label = DIFFICULTY_LABELS.get(q.difficulty, 'Unknown')

        # Preserve filter params for pagination links
        filter_params = {k: v for k, v in request.GET.items() if k != 'page'}

        return render(request, 'worksheets/partials/_builder_question_list.html', {
            'page_obj': page_obj,
            'filter_params': filter_params,
            'total_count': paginator.count,
        })
