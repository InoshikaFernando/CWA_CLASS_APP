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

        # Build image list for the gallery (embedded images only, not screenshots)
        image_list = []
        for ref, b64 in session.extracted_images.items():
            image_list.append({'ref': ref, 'name': ref, 'base64': b64})

        # Fill in per-question defaults from global classification
        questions = data.get('questions', [])
        for q in questions:
            if 'year_level' not in q or not q['year_level']:
                q['year_level'] = data.get('year_level')
            if 'subject' not in q or not q['subject']:
                q['subject'] = data.get('subject', 'Mathematics')
            if 'strand' not in q or not q['strand']:
                q['strand'] = data.get('strand', '')
            if 'topic' not in q or not q['topic']:
                q['topic'] = data.get('topic', '')

        return render(request, 'ai_import/preview.html', {
            'session': session,
            'data': data,
            'questions': questions,
            'topics': topics,
            'levels': levels,
            'image_list': image_list,
            'image_refs_json': json.dumps([img['ref'] for img in image_list]),
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
        import logging
        logger = logging.getLogger(__name__)

        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        data = session.extracted_data

        logger.warning(f'AI Import Preview POST: session={session_id}, POST keys={list(request.POST.keys())[:10]}')

        # Update default classification
        data['year_level'] = int(request.POST.get('year_level', data.get('year_level', 1)))
        data['topic'] = request.POST.get('topic', data.get('topic', ''))
        data['strand'] = request.POST.get('strand', data.get('strand', ''))
        data['subject'] = request.POST.get('subject', data.get('subject', 'Mathematics'))

        # Update individual questions with per-question overrides
        questions = data.get('questions', [])
        for idx, q in enumerate(questions):
            prefix = f'q_{idx}_'
            q['include'] = request.POST.get(f'{prefix}include') == 'on'
            q['question_text'] = request.POST.get(f'{prefix}text', q.get('question_text', ''))
            q['question_type'] = request.POST.get(f'{prefix}type', q.get('question_type', 'short_answer'))
            q['difficulty'] = int(request.POST.get(f'{prefix}difficulty', q.get('difficulty', 1)))
            q['points'] = int(request.POST.get(f'{prefix}points', q.get('points', 1)))
            q['explanation'] = request.POST.get(f'{prefix}explanation', q.get('explanation', ''))

            # Per-question classification
            q['year_level'] = int(request.POST.get(f'{prefix}year_level', q.get('year_level', data['year_level'])))
            q['subject'] = request.POST.get(f'{prefix}subject', q.get('subject', data['subject']))
            q['strand'] = request.POST.get(f'{prefix}strand', q.get('strand', data['strand']))
            q['topic'] = request.POST.get(f'{prefix}topic', q.get('topic', data['topic']))

            # Image ref
            img_ref = request.POST.get(f'{prefix}image_ref', '')
            q['image_ref'] = img_ref if img_ref and img_ref != 'none' else None

            # Dynamic answers — collect all answer fields
            answers = []
            for a_idx in range(20):  # support up to 20 answers
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


class UploadImageView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """AJAX endpoint: upload an image to the session's image gallery."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def post(self, request, session_id):
        import base64
        from django.http import JsonResponse

        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )

        image_file = request.FILES.get('image')
        if not image_file:
            return JsonResponse({'error': 'No image file provided'}, status=400)

        # Generate a ref name
        existing_count = len([k for k in session.extracted_images if k.startswith('uploaded_')])
        ext = image_file.name.rsplit('.', 1)[-1].lower() if '.' in image_file.name else 'png'
        ref = f'uploaded_{existing_count + 1}.{ext}'

        # Use original filename if provided
        custom_name = request.POST.get('name', '')
        if custom_name:
            ref = custom_name if '.' in custom_name else f'{custom_name}.{ext}'

        # Convert to base64 and store in session
        img_bytes = image_file.read()
        img_b64 = base64.b64encode(img_bytes).decode('utf-8')
        session.extracted_images[ref] = img_b64
        session.save(update_fields=['extracted_images'])

        return JsonResponse({
            'ref': ref,
            'name': ref,
            'size': len(img_bytes),
        })


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
        included_qs = [q for q in data.get('questions', []) if q.get('include', True)]
        excluded_count = len(data.get('questions', [])) - len(included_qs)

        # Summarise per-question year levels, topics, strands
        year_levels = sorted(set(
            q.get('year_level') or data.get('year_level') for q in included_qs
        ))
        topics = sorted(set(
            q.get('topic') or data.get('topic', '') for q in included_qs
        ))
        strands = sorted(set(
            q.get('strand') or data.get('strand', '') for q in included_qs
        ))
        images_count = sum(1 for q in included_qs if q.get('image_ref'))

        return render(request, 'ai_import/confirm.html', {
            'session': session,
            'data': data,
            'included_count': len(included_qs),
            'excluded_count': excluded_count,
            'total_count': len(data.get('questions', [])),
            'year_levels': year_levels,
            'topics': topics,
            'strands': strands,
            'images_count': images_count,
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


class ExportSessionView(RoleRequiredMixin, View):
    """Export a confirmed session as ZIP (JSON + images) compatible with UploadQuestionsView."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, session_id):
        import base64
        import io
        import zipfile
        from django.http import HttpResponse

        session = get_object_or_404(AIImportSession, pk=session_id, user=request.user)
        data = session.extracted_data
        questions = data.get('questions', [])
        included = [q for q in questions if q.get('include', True)]

        export = {
            'year_level': data.get('year_level'),
            'subject': data.get('subject', 'Mathematics'),
            'strand': data.get('strand', ''),
            'topic': data.get('topic', ''),
            'questions': [],
        }

        image_refs_used = set()
        for q in included:
            eq = {
                'question_text': q.get('question_text', ''),
                'question_type': q.get('question_type', 'short_answer'),
                'difficulty': q.get('difficulty', 1),
                'points': q.get('points', 1),
                'explanation': q.get('explanation', ''),
                'answers': q.get('answers', []),
            }
            if q.get('year_level') and q['year_level'] != data.get('year_level'):
                eq['year_level'] = q['year_level']
            if q.get('topic') and q['topic'] != data.get('topic'):
                eq['topic'] = q['topic']
            if q.get('strand') and q['strand'] != data.get('strand'):
                eq['strand'] = q['strand']
            if q.get('image_ref'):
                eq['image'] = q['image_ref']
                image_refs_used.add(q['image_ref'])
            export['questions'].append(eq)

        # Build ZIP with questions.json + images
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zf:
            # Add questions.json
            zf.writestr('questions.json', json.dumps(export, indent=2))

            # Add images from session (base64 stored)
            for ref in image_refs_used:
                if ref in session.extracted_images:
                    img_bytes = base64.b64decode(session.extracted_images[ref])
                    zf.writestr(ref, img_bytes)
                else:
                    # Try from media directory
                    for year_dir_name in [f'year{q.get("year_level", data.get("year_level", ""))}' for q in included if q.get('image_ref') == ref]:
                        topic_slug = (q.get('topic') or data.get('topic', 'general')).lower().replace(' ', '-')
                        img_path = os.path.join(
                            str(settings.MEDIA_ROOT), 'questions', year_dir_name, topic_slug, ref,
                        )
                        if os.path.exists(img_path):
                            with open(img_path, 'rb') as f:
                                zf.writestr(ref, f.read())
                            break

        zip_buffer.seek(0)
        filename = session.pdf_filename.rsplit('.', 1)[0] + '.zip'
        response = HttpResponse(zip_buffer.getvalue(), content_type='application/zip')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


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
