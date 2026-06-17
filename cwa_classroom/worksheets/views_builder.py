"""
Worksheet Builder views — CPP-282 / CPP-284 / CPP-285.

CPP-282: Teachers browse the global question bank with filter panel
         (subject, topic, level, free-text search). Results via HTMX.
CPP-284: WorksheetBuilderSaveView — POST to persist the selection as a
         Worksheet + WorksheetQuestion rows, then redirect to detail page.
CPP-285: WorksheetBuilderPreviewView — HTMX endpoint returning a question
         detail partial for display in a modal overlay.
"""

import json

from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse

from accounts.models import Role
from billing.entitlements import get_school_for_user
from classroom.models import Level, Subject, Topic
from classroom.views import RoleRequiredMixin
from django.views import View

from coding.models import CodingExercise, CodingLanguage, CodingTopic as CodingTopicModel
from maths.models import Answer, Question
from worksheets.models import Worksheet, WorksheetQuestion

# Coding level choices (from coding.TopicLevel.level_choice)
CODING_LEVELS = [
    ('beginner', 'Beginner'),
    ('intermediate', 'Intermediate'),
    ('advanced', 'Advanced'),
]

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

        # Maths parent topics (top-level only — subtopics fetched via HTMX cascade)
        maths_global = Subject.objects.filter(slug='mathematics', school__isnull=True).first()
        maths_parent_topics = (
            Topic.objects.filter(subject=maths_global, parent__isnull=True).order_by('name')
            if maths_global else []
        )

        # Coding: languages as top-level topics
        coding_languages = CodingLanguage.objects.filter(is_active=True).order_by('order', 'name')

        levels = Level.objects.filter(level_number__lte=12).order_by('level_number')

        return render(request, 'worksheets/builder.html', {
            'subjects': subjects,
            'maths_parent_topics': maths_parent_topics,
            'coding_languages': coding_languages,
            'coding_levels': CODING_LEVELS,
            'levels': levels,
            # Initial render is Mathematics; coding types are swapped in via cascade.
            'question_types': Question.QUESTION_TYPES,
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

        subject_slug = request.GET.get('subject', '').strip()
        topic_id = request.GET.get('topic', '').strip()
        subtopic_id = request.GET.get('subtopic', '').strip()
        level_filter = request.GET.get('level', '').strip()
        question_type = request.GET.get('question_type', '').strip()
        search = request.GET.get('q', '').strip()

        filter_params = {k: v for k, v in request.GET.items() if k != 'page'}

        if subject_slug == 'coding':
            return self._coding_response(request, topic_id, subtopic_id, level_filter, search, filter_params, question_type)

        # --- Maths (default) ---
        qs = Question.objects.filter(
            Q(school__isnull=True) | Q(school=school)
        ).select_related('topic__subject', 'level').order_by('level', 'difficulty', 'pk')

        qs = qs.filter(topic__subject__slug='mathematics')

        if subtopic_id:
            try:
                qs = qs.filter(topic_id=int(subtopic_id))
            except (ValueError, TypeError):
                pass
        elif topic_id:
            try:
                tid = int(topic_id)
                child_ids = list(Topic.objects.filter(parent_id=tid).values_list('pk', flat=True))
                qs = qs.filter(topic_id__in=[tid] + child_ids)
            except (ValueError, TypeError):
                pass

        if level_filter:
            try:
                qs = qs.filter(level__level_number=int(level_filter))
            except (ValueError, TypeError):
                pass

        if question_type:
            qs = qs.filter(question_type=question_type)

        if search:
            qs = qs.filter(question_text__icontains=search)

        paginator = Paginator(qs, PAGE_SIZE)
        page_number = request.GET.get('page', 1)
        try:
            page_number = int(page_number)
        except (ValueError, TypeError):
            page_number = 1
        page_obj = paginator.get_page(page_number)

        for q in page_obj:
            q.difficulty_label = DIFFICULTY_LABELS.get(q.difficulty, 'Unknown')

        return render(request, 'worksheets/partials/_builder_question_list.html', {
            'page_obj': page_obj,
            'filter_params': filter_params,
            'total_count': paginator.count,
        })

    def _coding_response(self, request, topic_id, subtopic_id, level_filter, search, filter_params, question_type=''):
        """Build and paginate a CodingExercise queryset for the given filters."""
        qs = CodingExercise.objects.filter(
            is_active=True,
        ).select_related(
            'topic_level__topic__language',
        ).order_by('topic_level__topic__language__order', 'topic_level__level_choice', 'order')

        # topic_id = CodingLanguage pk, subtopic_id = CodingTopic pk
        if subtopic_id:
            try:
                qs = qs.filter(topic_level__topic_id=int(subtopic_id))
            except (ValueError, TypeError):
                pass
        elif topic_id:
            try:
                qs = qs.filter(topic_level__topic__language_id=int(topic_id))
            except (ValueError, TypeError):
                pass

        if level_filter:
            qs = qs.filter(topic_level__level_choice=level_filter)

        if question_type:
            qs = qs.filter(question_type=question_type)

        if search:
            qs = qs.filter(
                Q(title__icontains=search) | Q(description__icontains=search)
            )

        paginator = Paginator(qs, PAGE_SIZE)
        page_number = request.GET.get('page', 1)
        try:
            page_number = int(page_number)
        except (ValueError, TypeError):
            page_number = 1
        page_obj = paginator.get_page(page_number)

        return render(request, 'worksheets/partials/_builder_question_list.html', {
            'page_obj': page_obj,
            'filter_params': filter_params,
            'total_count': paginator.count,
            'is_coding': True,
        })


class WorksheetBuilderCascadeView(RoleRequiredMixin, View):
    """
    GET /worksheets/builder/cascade/

    HTMX cascade endpoint — returns an OOB partial that updates the
    topic, subtopic, and level dropdowns when the subject or parent-topic
    selection changes.  The PRIMARY response body is the updated question
    list (same as builder_questions), so the caller targets #question-list.
    OOB elements update the filter dropdowns in-place.

    Query params: subject (slug), topic (parent topic pk), step (subject|topic)
    """
    required_roles = BUILDER_ROLES

    def get(self, request):
        school = get_school_for_user(request.user)
        subject_slug = request.GET.get('subject', '').strip()
        topic_id = request.GET.get('topic', '').strip()
        question_type = request.GET.get('question_type', '').strip()
        step = request.GET.get('step', 'subject')  # 'subject' or 'topic'

        # --- Build cascade data ---
        if subject_slug == 'coding':
            parent_items = list(CodingLanguage.objects.filter(is_active=True).order_by('order', 'name'))
            subtopic_items = []
            if topic_id:
                try:
                    subtopic_items = list(
                        CodingTopicModel.objects.filter(language_id=int(topic_id))
                        .order_by('order', 'name')
                    )
                except (ValueError, TypeError):
                    pass
            level_options = CODING_LEVELS
            level_type = 'coding'
            qtype_options = CodingExercise.QUESTION_TYPE_CHOICES
        else:
            # Mathematics (or default)
            maths_global = Subject.objects.filter(slug='mathematics', school__isnull=True).first()
            parent_items = (
                list(Topic.objects.filter(subject=maths_global, parent__isnull=True).order_by('name'))
                if maths_global else []
            )
            subtopic_items = []
            if topic_id:
                try:
                    subtopic_items = list(Topic.objects.filter(parent_id=int(topic_id)).order_by('name'))
                except (ValueError, TypeError):
                    pass
            level_options = list(Level.objects.filter(level_number__lte=12).order_by('level_number'))
            level_type = 'year'
            qtype_options = Question.QUESTION_TYPES

        # --- Question list (same logic as WorksheetBuilderQuestionsView) ---
        is_coding = (subject_slug == 'coding')
        if is_coding:
            qs = CodingExercise.objects.filter(is_active=True).select_related(
                'topic_level__topic__language',
            ).order_by('topic_level__topic__language__order', 'topic_level__level_choice', 'order')
            if topic_id:
                try:
                    qs = qs.filter(topic_level__topic__language_id=int(topic_id))
                except (ValueError, TypeError):
                    pass
            if question_type:
                qs = qs.filter(question_type=question_type)
            search = request.GET.get('q', '').strip()
            if search:
                qs = qs.filter(Q(title__icontains=search) | Q(description__icontains=search))
            paginator = Paginator(qs, PAGE_SIZE)
            page_obj = paginator.get_page(1)
            total_count = paginator.count
        else:
            qs = Question.objects.filter(
                Q(school__isnull=True) | Q(school=school)
            ).select_related('topic__subject', 'level').order_by('level', 'difficulty', 'pk')
            qs = qs.filter(topic__subject__slug='mathematics')
            if topic_id:
                try:
                    tid = int(topic_id)
                    child_ids = list(Topic.objects.filter(parent_id=tid).values_list('pk', flat=True))
                    qs = qs.filter(topic_id__in=[tid] + child_ids)
                except (ValueError, TypeError):
                    pass
            if question_type:
                qs = qs.filter(question_type=question_type)
            search = request.GET.get('q', '').strip()
            if search:
                qs = qs.filter(question_text__icontains=search)
            paginator = Paginator(qs, PAGE_SIZE)
            page_obj = paginator.get_page(1)
            for q in page_obj:
                q.difficulty_label = DIFFICULTY_LABELS.get(q.difficulty, 'Unknown')
            total_count = paginator.count

        return render(request, 'worksheets/partials/_builder_cascade.html', {
            'subject_slug': subject_slug,
            'topic_id': topic_id,
            'step': step,
            'parent_items': parent_items,
            'subtopic_items': subtopic_items,
            'level_options': level_options,
            'level_type': level_type,
            'qtype_options': qtype_options,
            'page_obj': page_obj,
            'filter_params': {k: v for k, v in request.GET.items() if k not in ('page', 'step')},
            'total_count': total_count,
            'is_coding': is_coding,
        })


class WorksheetBuilderSaveView(RoleRequiredMixin, View):
    """
    POST /worksheets/builder/save/

    Persists the teacher's builder selection as a Worksheet + WorksheetQuestion rows.

    Expected POST fields:
        name           — worksheet name (str, required, max 100 chars)
        level_id       — year level pk (int, optional)
        questions_json — JSON array of {subject_slug, content_id} (required, ≥1 item)

    Returns:
        On success: 200 with HX-Redirect header → worksheets:detail (HTMX navigates)
        On error:   400 with JSON {error: "..."} for inline display in sidebar

    Note: WorksheetQuestion.question FK is non-nullable in this sprint. All builder
    questions are maths questions (subject_slug='mathematics', content_id=question_id).
    TODO CPP-Sprint3: make question FK nullable to support coding questions.
    """
    required_roles = BUILDER_ROLES

    def post(self, request):
        school = get_school_for_user(request.user)

        # --- Parse and validate name ---
        name = request.POST.get('name', '').strip()
        if not name:
            return JsonResponse({'error': 'Worksheet name is required.'}, status=400)
        if len(name) > 100:
            return JsonResponse({'error': 'Worksheet name must be 100 characters or fewer.'}, status=400)

        # --- Parse and validate level (optional) ---
        level = None
        level_id_raw = request.POST.get('level_id', '').strip()
        if level_id_raw:
            try:
                level = Level.objects.get(level_number=int(level_id_raw))
            except (Level.DoesNotExist, ValueError, TypeError):
                pass  # Level is optional — ignore invalid values

        # --- Parse questions JSON ---
        try:
            questions = json.loads(request.POST.get('questions_json', '[]'))
        except (json.JSONDecodeError, TypeError):
            return JsonResponse({'error': 'Invalid question data. Please try again.'}, status=400)

        if not isinstance(questions, list) or len(questions) == 0:
            return JsonResponse({'error': 'Please select at least one question.'}, status=400)

        # --- Check for duplicates in submitted list ---
        seen = set()
        for item in questions:
            key = (item.get('subject_slug', ''), item.get('content_id', 0))
            if key in seen:
                return JsonResponse({'error': 'Duplicate questions detected. Please remove duplicates and try again.'}, status=400)
            seen.add(key)

        # --- Validate all questions are visible to this school ---
        maths_items = [item for item in questions if item.get('subject_slug', 'mathematics') != 'coding']
        coding_items = [item for item in questions if item.get('subject_slug') == 'coding']

        maths_ids = [item['content_id'] for item in maths_items]
        coding_ids = [item['content_id'] for item in coding_items]

        visible_maths = {}
        if maths_ids:
            visible_maths = {
                q.pk: q for q in Question.objects.filter(
                    pk__in=maths_ids
                ).filter(Q(school__isnull=True) | Q(school=school))
            }
            if len(visible_maths) != len(maths_ids):
                return JsonResponse({'error': 'One or more maths questions are not available for your school.'}, status=400)

        visible_coding = {}
        if coding_ids:
            visible_coding = {
                ex.pk: ex for ex in CodingExercise.objects.filter(
                    pk__in=coding_ids, is_active=True
                ).filter(Q(school__isnull=True) | Q(school=school))
            }
            if len(visible_coding) != len(coding_ids):
                return JsonResponse({'error': 'One or more coding exercises are not available.'}, status=400)

        # --- Create Worksheet + WorksheetQuestion rows atomically ---
        with transaction.atomic():
            worksheet = Worksheet.objects.create(
                school=school,
                name=name,
                level=level,
                original_filename='',
                pdf_file=None,
                created_by=request.user,
            )

            wq_rows = []
            for idx, item in enumerate(questions):
                slug = item.get('subject_slug', 'mathematics')
                cid = item['content_id']
                if slug == 'coding':
                    wq_rows.append(WorksheetQuestion(
                        worksheet=worksheet,
                        question=None,
                        coding_exercise=visible_coding[cid],
                        subject_slug='coding',
                        content_id=cid,
                        order=idx + 1,
                    ))
                else:
                    wq_rows.append(WorksheetQuestion(
                        worksheet=worksheet,
                        question=visible_maths[cid],
                        subject_slug=slug,
                        content_id=cid,
                        order=idx + 1,
                    ))
            WorksheetQuestion.objects.bulk_create(wq_rows)

            worksheet.refresh_question_count()

        messages.success(request, f'Worksheet "{name}" created successfully.')
        response = HttpResponse(status=200)
        response['HX-Redirect'] = reverse('worksheets:detail', args=[worksheet.pk])
        return response


class WorksheetBuilderPreviewView(RoleRequiredMixin, View):
    """
    GET /worksheets/builder/preview/<subject_slug>/<int:content_id>/

    HTMX endpoint — returns _builder_question_preview.html partial
    for display in the builder's modal overlay.
    """
    required_roles = BUILDER_ROLES

    def get(self, request, subject_slug, content_id):
        if subject_slug not in ('mathematics', 'coding'):
            raise Http404

        school = get_school_for_user(request.user)
        if school is None:
            raise Http404

        if subject_slug == 'coding':
            exercise = get_object_or_404(
                CodingExercise.objects.select_related(
                    'topic_level__topic__language',
                ),
                pk=content_id,
                is_active=True,
            )
            if exercise.school_id is not None and exercise.school_id != school.pk:
                raise Http404
            return render(request, 'worksheets/partials/_builder_question_preview.html', {
                'is_coding': True,
                'exercise': exercise,
                'subject_slug': 'coding',
                'content_id': content_id,
            })

        question = get_object_or_404(
            Question.objects.select_related('topic', 'level'),
            pk=content_id,
        )
        if question.school_id is not None and question.school_id != school.pk:
            raise Http404

        answers = Answer.objects.filter(question=question).order_by('order', 'pk')
        question.difficulty_label = DIFFICULTY_LABELS.get(question.difficulty, 'Unknown')

        return render(request, 'worksheets/partials/_builder_question_preview.html', {
            'is_coding': False,
            'question': question,
            'answers': answers,
            'subject_slug': 'mathematics',
            'content_id': content_id,
        })
