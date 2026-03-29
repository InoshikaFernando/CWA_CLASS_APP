"""
AI Question Import views: Upload PDF → Preview → Confirm.
"""
import json

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from accounts.models import Role
from billing.entitlements import get_school_for_user, has_module, has_module_any_school
from classroom.views import RoleRequiredMixin, _get_question_scope

from .models import AIImportSession, AIImportUsage


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

AI_IMPORT_MODULES = ['ai_import_starter', 'ai_import_professional', 'ai_import_enterprise']

AI_IMPORT_PAGE_LIMITS = {
    'ai_import_starter': 300,
    'ai_import_professional': 600,
    'ai_import_enterprise': 1000,
}

AI_IMPORT_TIER_NAMES = {
    'ai_import_starter': 'Starter',
    'ai_import_professional': 'Professional',
    'ai_import_enterprise': 'Enterprise',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_ai_import_tier(school):
    """Return the active AI import module slug for a school, or None."""
    from billing.entitlements import get_school_subscription
    sub = get_school_subscription(school)
    if not sub:
        return None
    for mod_slug in AI_IMPORT_MODULES:
        if sub.modules.filter(module=mod_slug, is_active=True).exists():
            return mod_slug
    return None


def _has_ai_import_access(user):
    """Check if the user has access to any AI import tier via any school."""
    from billing.entitlements import get_all_schools_for_user
    for school in get_all_schools_for_user(user):
        if _get_ai_import_tier(school):
            return True
    return False


def _get_usage_for_school(school):
    """Get or create usage record for the current billing period."""
    today = timezone.localdate()
    period_start = today.replace(day=1)
    usage, _ = AIImportUsage.objects.get_or_create(
        school=school, period_start=period_start,
        defaults={'pages_processed': 0, 'tokens_used': 0},
    )
    return usage


def _get_remaining_pages(school):
    """Return (remaining_pages, page_limit, pages_used) for the school."""
    tier = _get_ai_import_tier(school)
    if not tier:
        return (0, 0, 0)
    limit = AI_IMPORT_PAGE_LIMITS.get(tier, 0)
    usage = _get_usage_for_school(school)
    remaining = max(0, limit - usage.pages_processed)
    return (remaining, limit, usage.pages_processed)


# ---------------------------------------------------------------------------
# Mixin
# ---------------------------------------------------------------------------

class AIImportModuleRequiredMixin:
    """Check that the user's school has any AI import module active."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            if not _has_ai_import_access(request.user):
                from urllib.parse import urlencode
                from audit.services import log_event
                school = get_school_for_user(request.user)
                log_event(
                    user=request.user, school=school,
                    category='entitlement', action='ai_import_access_denied',
                    result='blocked', request=request,
                )
                url = reverse('ai_import:tier_select')
                return redirect(url)
        return super().dispatch(request, *args, **kwargs)


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

class UploadPDFView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """Step 1: Upload a PDF for AI classification."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request):
        school = get_school_for_user(request.user)
        tier = _get_ai_import_tier(school) if school else None
        remaining, limit, used = _get_remaining_pages(school) if school else (0, 0, 0)

        # Get classrooms for teachers
        classrooms = []
        if not request.user.is_superuser:
            _, _, classroom_ids = _get_question_scope(request.user)
            if classroom_ids:
                from classroom.models import ClassRoom
                classrooms = ClassRoom.objects.filter(id__in=classroom_ids, is_active=True)

        return render(request, 'ai_import/upload.html', {
            'tier': AI_IMPORT_TIER_NAMES.get(tier, 'None'),
            'remaining_pages': remaining,
            'page_limit': limit,
            'pages_used': used,
            'usage_percent': round((used / limit * 100) if limit else 0),
            'classrooms': classrooms,
        })

    def post(self, request):
        school = get_school_for_user(request.user)
        pdf_file = request.FILES.get('pdf_file')

        if not pdf_file:
            messages.error(request, 'Please select a PDF file.')
            return redirect('ai_import:upload')

        if not pdf_file.name.lower().endswith('.pdf'):
            messages.error(request, 'Only PDF files are supported.')
            return redirect('ai_import:upload')

        # Check usage limit
        remaining, limit, used = _get_remaining_pages(school) if school else (0, 0, 0)

        try:
            # Step 1: Extract PDF content
            from .services import extract_pdf_content
            extracted = extract_pdf_content(pdf_file)
            page_count = extracted['page_count']

            if remaining > 0 and page_count > remaining:
                messages.error(
                    request,
                    f'This PDF has {page_count} pages but you only have {remaining} pages remaining this month. '
                    f'Please upgrade your plan or upload a smaller file.',
                )
                return redirect('ai_import:upload')

            # Step 2: Get existing topics/levels for AI context
            from classroom.models import Topic, Level
            existing_topics = list(Topic.objects.filter(
                subject__slug='mathematics',
            ).values('name', 'slug')[:100])
            existing_levels = list(Level.objects.filter(
                level_number__lte=12,
            ).values('level_number', 'display_name'))

            # Step 3: Classify via AI
            from .services import classify_questions
            result = classify_questions(extracted, existing_topics, existing_levels)

            # Step 4: Collect extracted images
            extracted_images = {}
            for page in extracted['pages']:
                for img in page['images']:
                    extracted_images[img['ref']] = img['base64']

            # Step 5: Create session
            session = AIImportSession.objects.create(
                user=request.user,
                school=school,
                pdf_filename=pdf_file.name,
                extracted_data=result,
                extracted_images=extracted_images,
                page_count=page_count,
                tokens_used=result.get('usage', {}).get('total_tokens', 0),
            )

            # Store classroom selection in session data if teacher
            classroom_id = request.POST.get('classroom_id')
            if classroom_id:
                result['classroom_id'] = int(classroom_id)
                session.extracted_data = result
                session.save(update_fields=['extracted_data'])

            return redirect('ai_import:preview', session_id=session.pk)

        except ImportError:
            messages.error(request, 'PDF processing library not installed. Please contact the administrator.')
            return redirect('ai_import:upload')
        except Exception as e:
            messages.error(request, f'Error processing PDF: {str(e)}')
            return redirect('ai_import:upload')


class PreviewQuestionsView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """Step 2: Preview AI-classified questions. User can edit/include/exclude."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, session_id):
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data

        # Get available topics and levels for override dropdowns
        from classroom.models import Topic, Level
        topics = Topic.objects.filter(subject__slug='mathematics').order_by('name')
        levels = Level.objects.filter(level_number__lte=12).order_by('level_number')

        return render(request, 'ai_import/preview.html', {
            'session': session,
            'data': data,
            'questions': data.get('questions', []),
            'topics': topics,
            'levels': levels,
            'question_types': [
                ('multiple_choice', 'Multiple Choice'),
                ('true_false', 'True / False'),
                ('short_answer', 'Short Answer'),
                ('fill_blank', 'Fill in the Blank'),
                ('calculation', 'Calculation'),
            ],
        })

    def post(self, request, session_id):
        """Save user edits from the preview form and redirect to confirm."""
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data

        # Update top-level overrides
        data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))
        data['topic'] = request.POST.get('topic', data.get('topic', ''))
        data['strand'] = request.POST.get('strand', data.get('strand', ''))
        data['subject'] = request.POST.get('subject', data.get('subject', 'Mathematics'))

        # Update individual questions
        questions = data.get('questions', [])
        for idx, q in enumerate(questions):
            prefix = f'q_{idx}_'
            q['include'] = request.POST.get(f'{prefix}include') == 'on'
            q['question_text'] = request.POST.get(f'{prefix}text', q.get('question_text', ''))
            q['question_type'] = request.POST.get(f'{prefix}type', q.get('question_type', 'short_answer'))
            q['difficulty'] = int(request.POST.get(f'{prefix}difficulty', q.get('difficulty', 1)))
            q['points'] = int(request.POST.get(f'{prefix}points', q.get('points', 1)))
            q['explanation'] = request.POST.get(f'{prefix}explanation', q.get('explanation', ''))

            # Update answers
            answers = []
            for a_idx in range(4):
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
        session.save(update_fields=['extracted_data'])

        return redirect('ai_import:confirm', session_id=session.pk)


class ConfirmImportView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """Step 3: Confirm and save questions to the database."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, session_id):
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data
        included_count = sum(1 for q in data.get('questions', []) if q.get('include', True))

        return render(request, 'ai_import/confirm.html', {
            'session': session,
            'data': data,
            'included_count': included_count,
            'total_count': len(data.get('questions', [])),
        })

    def post(self, request, session_id):
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        school = get_school_for_user(request.user)

        from .services import save_questions_from_session
        from audit.services import log_event

        result = save_questions_from_session(session, request.user, session.extracted_data)

        # Record usage
        if school:
            usage = _get_usage_for_school(school)
            usage.pages_processed += session.page_count
            usage.tokens_used += session.tokens_used
            usage.save(update_fields=['pages_processed', 'tokens_used'])

        # Audit log
        log_event(
            user=request.user, school=school,
            category='data_change', action='ai_questions_imported',
            detail={
                'session_id': session.pk,
                'pdf_filename': session.pdf_filename,
                'page_count': session.page_count,
                'inserted': result['inserted'],
                'updated': result['updated'],
                'failed': result['failed'],
                'images_saved': result['images_saved'],
            },
            request=request,
        )

        return render(request, 'ai_import/results.html', {
            'session': session,
            'result': result,
        })


class TierSelectView(LoginRequiredMixin, View):
    """Package tier comparison and selection page."""

    def get(self, request):
        school = get_school_for_user(request.user)
        current_tier = _get_ai_import_tier(school) if school else None
        remaining, limit, used = _get_remaining_pages(school) if school and current_tier else (0, 0, 0)

        tiers = [
            {
                'slug': 'ai_import_starter',
                'name': 'Starter',
                'pages': 300,
                'price': 30,
                'year1_price': 15,
                'is_current': current_tier == 'ai_import_starter',
            },
            {
                'slug': 'ai_import_professional',
                'name': 'Professional',
                'pages': 600,
                'price': 60,
                'year1_price': 30,
                'is_current': current_tier == 'ai_import_professional',
            },
            {
                'slug': 'ai_import_enterprise',
                'name': 'Enterprise',
                'pages': 1000,
                'price': 99,
                'year1_price': 50,
                'is_current': current_tier == 'ai_import_enterprise',
            },
        ]

        return render(request, 'ai_import/tier_select.html', {
            'tiers': tiers,
            'current_tier': current_tier,
            'remaining_pages': remaining,
            'page_limit': limit,
            'pages_used': used,
        })
