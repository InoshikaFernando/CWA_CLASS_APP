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
from billing.entitlements import get_school_for_user, has_module, has_module_any_school, check_ai_import_quota
from classroom.views import RoleRequiredMixin, _get_question_scope

from worksheets.services import (
    answer_review_warning, preview_question_type_choices, question_source_page,
    spec_panel_for_type,
)

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
    return check_ai_import_quota(school)


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

        # Superusers get unlimited access
        if request.user.is_superuser:
            tier_name = 'Unlimited (Admin)'
            remaining, limit, used = (999999, 999999, 0)
        else:
            tier = _get_ai_import_tier(school) if school else None
            tier_name = AI_IMPORT_TIER_NAMES.get(tier, 'None')
            remaining, limit, used = _get_remaining_pages(school) if school else (0, 0, 0)

        # Get classrooms for teachers
        classrooms = []
        if not request.user.is_superuser:
            _, _, classroom_ids = _get_question_scope(request.user)
            if classroom_ids:
                from classroom.models import ClassRoom
                classrooms = ClassRoom.objects.filter(id__in=classroom_ids, is_active=True)

        from billing.page_quota import quota_status
        return render(request, 'ai_import/upload.html', {
            'tier': tier_name,
            'remaining_pages': remaining,
            'page_limit': limit,
            'pages_used': used,
            'usage_percent': round((used / limit * 100) if limit else 0),
            'classrooms': classrooms,
            'page_quota': quota_status(
                school, unlimited=request.user.is_superuser,
            ),
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

        # Which pages to extract ("2-7, 9"; blank = all). Validated before the
        # quota check so a bad range is an immediate form error, and so an upload
        # that skips a cover sheet or a marking scheme is only charged for the
        # pages it actually reads.
        from worksheets.page_selection import (
            PageSelectionError, clean_upload_selection,
        )
        try:
            page_selection, selected_pages, _total = clean_upload_selection(
                request.POST.get('page_selection'), pdf_file,
            )
        except PageSelectionError as exc:
            messages.error(request, str(exc))
            return redirect('ai_import:upload')

        try:
            # Step 1: Cheap page count for the quota check (no rendering). Only
            # the selected pages are extracted, so only those are charged.
            from .services import get_pdf_page_count
            page_count = (len(selected_pages) if selected_pages is not None
                          else get_pdf_page_count(pdf_file))

            # The monthly allowance is shared with homework and worksheet
            # uploads and charged at upload, not at confirm: the classification
            # job below spends the money whether or not the teacher ever
            # reaches the confirm step. See billing/page_quota.py.
            from billing.page_quota import (
                check_page_budget, consume_pages, refund_pages,
            )
            is_unlimited = request.user.is_superuser
            allowed, quota_message, _quota = check_page_budget(
                school, page_count, unlimited=is_unlimited,
            )
            if not allowed:
                messages.error(request, quota_message)
                return redirect('ai_import:upload')

            # Step 2: Persist the upload + create a PROCESSING session.
            pre_data = {}
            classroom_id = request.POST.get('classroom_id')
            if classroom_id:
                pre_data['classroom_id'] = int(classroom_id)

            session = AIImportSession.objects.create(
                user=request.user,
                school=school,
                pdf_filename=pdf_file.name,
                pdf_file=pdf_file,
                page_selection=page_selection,
                page_count=page_count,
                extracted_data=pre_data,
                status=AIImportSession.STATUS_PROCESSING,
            )

            # Charge now, not when the worker finishes: two uploads landing
            # together would otherwise both pass the check above and overshoot.
            consume_pages(school, page_count, unlimited=is_unlimited)

            # Step 3: Enqueue background classification (default queue). If the
            # queue is unavailable, don't leave an orphaned PROCESSING session.
            from taskqueue.services import enqueue_task
            from .tasks import process_pdf_import
            try:
                enqueue_task(
                    school=school,
                    user=request.user,
                    task_type='ai_import_pdf',
                    func=process_pdf_import,
                    args=[session.pk],
                    queue='default',
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception(
                    'Failed to enqueue AI import for session %s', session.pk,
                )
                # Nothing will be classified, so the pages charged above were
                # never spent — hand them back.
                refund_pages(school, page_count, unlimited=is_unlimited)
                session.delete()
                messages.error(
                    request,
                    'The background processing service is temporarily unavailable. '
                    'Please try again in a few minutes.',
                )
                return redirect('ai_import:upload')

            return redirect('ai_import:processing', session_id=session.pk)

        except ImportError:
            messages.error(request, 'PDF processing library not installed. Please contact the administrator.')
            return redirect('ai_import:upload')
        except Exception as e:
            messages.error(request, f'Error processing PDF: {str(e)}')
            return redirect('ai_import:upload')


class ProcessingView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """Interstitial page shown while the PDF is classified in the background."""
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, session_id):
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        # Already done — skip straight to the relevant page.
        if session.status == AIImportSession.STATUS_READY:
            return redirect('ai_import:preview', session_id=session.pk)
        return render(request, 'ai_import/processing.html', {'session': session})


class ImportStatusView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """HTMX poll endpoint: returns the status partial for a processing session.

    When the session becomes READY the partial sends an HX-Redirect to the
    preview page; on FAILED it shows the error with a retry link.
    """
    required_roles = [
        Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
        Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
        Role.TEACHER, Role.JUNIOR_TEACHER,
    ]

    def get(self, request, session_id):
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        response = render(request, 'ai_import/_partials/status.html', {'session': session})
        if session.status == AIImportSession.STATUS_READY:
            response['HX-Redirect'] = reverse('ai_import:preview', args=[session.pk])
        return response


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
        # Not finished yet — bounce back to the processing page.
        if session.status == AIImportSession.STATUS_PROCESSING:
            return redirect('ai_import:processing', session_id=session.pk)
        if session.status == AIImportSession.STATUS_FAILED:
            messages.error(request, f'PDF processing failed: {session.error_message}')
            return redirect('ai_import:upload')
        data = session.extracted_data

        # Sessions classified before drawing questions were routed to the teacher
        # still hold them as auto-graded with an invented answer. Sweep once on
        # first open — the same sweep the worksheet and homework previews run —
        # and say what moved rather than re-grading silently.
        from worksheets.services import backfill_constructions
        routed = backfill_constructions(data)
        if routed is not None:
            session.extracted_data = data
            session.save(update_fields=['extracted_data'])
            if routed:
                messages.info(
                    request,
                    f'{routed} question(s) ask the student to draw something the app '
                    'cannot accept an answer for. They are set to teacher-graded and '
                    'left unticked — tick one to import it for marking by hand.')

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
            # Pre-format the structured-spec JSON for the editable textareas.
            if q.get('plane_spec'):
                q['plane_spec_json'] = json.dumps(q['plane_spec'], indent=2)
            if q.get('graph_spec'):
                q['graph_spec_json'] = json.dumps(q['graph_spec'], indent=2)
            if q.get('number_line_spec'):
                q['number_line_spec_json'] = json.dumps(q['number_line_spec'], indent=2)
            if q.get('sketch_spec'):
                q['sketch_spec_json'] = json.dumps(q['sketch_spec'], indent=2)
            # For the "Adjust image" crop modal: open the page this question maps
            # to (falls back through crop provenance, the ref filename, source_page).
            q['image_page'] = question_source_page(q)
            q['image_bbox_frac_json'] = json.dumps(q.get('image_bbox_frac') or None)
            # Flag a suspect answer key (explanation disagrees with / second-guesses
            # the ticked answer) so the teacher checks it before confirming.
            q['answer_warning'] = answer_review_warning(q)
            # Which structured-spec panel this card's type edits ('' for the
            # plain types). All eight panels are still rendered so the type
            # dropdown can reveal one without a reload, but the inactive ones are
            # DISABLED. Two reasons, both real: a browser posts every enabled
            # field whether or not it is shown, so a long import crossed Django's
            # request-parser field ceiling and "Save & Continue" came back as a
            # bare 400; and the graph and measure panels share three field names,
            # so the hidden one's stale copy was overwriting the visible one's
            # edit (a QueryDict keeps the LAST value for a repeated key).
            q['spec_panel'] = spec_panel_for_type(q.get('question_type'))

        from worksheets.page_selection import describe_page_selection

        return render(request, 'ai_import/preview.html', {
            'session': session,
            'data': data,
            'questions': questions,
            'topics': topics,
            'levels': levels,
            # Pages the teacher chose not to extract — stated, not silently absent.
            'page_selection': describe_page_selection(data),
            'image_list': image_list,
            'image_refs_json': json.dumps([img['ref'] for img in image_list]),
            # Shared with the worksheet/homework previews, and widened with any
            # type this session actually holds, so the dropdown always contains
            # the question's own type — see preview_question_type_choices.
            'question_types': preview_question_type_choices(questions),
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
            # "Reviewed" tick on a flagged question — keeps needs_review (and its
            # reason) for the record but stops the preview shouting about it, and
            # persists so coming back to the page does not re-raise the alarm.
            q['review_ack'] = request.POST.get(f'{prefix}review_ack') == 'on'
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

            # Column-arithmetic fields (only relevant for column_operation)
            if q['question_type'] == 'column_operation':
                raw_operands = request.POST.get(f'{prefix}operands', '')
                operands = []
                for tok in raw_operands.replace(',', ' ').split():
                    try:
                        operands.append(int(tok))
                    except ValueError:
                        pass
                if operands:
                    q['operands'] = operands
                operator = request.POST.get(f'{prefix}operator', q.get('operator', ''))
                if operator:
                    q['operator'] = operator

            # Long-division fields (only relevant for long_division)
            if q['question_type'] == 'long_division':
                for fld in ('dividend', 'divisor'):
                    raw = request.POST.get(f'{prefix}{fld}', '').strip()
                    if raw:
                        try:
                            q[fld] = int(raw)
                        except ValueError:
                            pass

            # Cartesian-plane spec (plot_points / plot_line / identify_coords).
            # Edited as raw JSON in the preview; a parse failure leaves the prior
            # spec untouched so the import-time validator surfaces the issue.
            if q['question_type'] in ('plot_points', 'plot_line', 'identify_coords'):
                raw = request.POST.get(f'{prefix}plane_spec', '').strip()
                if raw:
                    try:
                        q['plane_spec'] = json.loads(raw)
                    except (ValueError, TypeError):
                        pass

            # Read-a-graph fields: numeric answer (+ tolerance/unit) and optional
            # graph_spec JSON.
            if q['question_type'] == 'read_graph':
                for fld in ('numeric_answer', 'answer_tolerance'):
                    raw = request.POST.get(f'{prefix}{fld}', '').strip()
                    if raw:
                        q[fld] = raw
                unit = request.POST.get(f'{prefix}answer_unit', '').strip()
                if unit:
                    q['answer_unit'] = unit
                raw = request.POST.get(f'{prefix}graph_spec', '').strip()
                if raw:
                    try:
                        q['graph_spec'] = json.loads(raw)
                    except (ValueError, TypeError):
                        pass

            # Measure fields: numeric answer (+ tolerance/unit).
            if q['question_type'] == 'measure':
                for fld in ('numeric_answer', 'answer_tolerance'):
                    raw = request.POST.get(f'{prefix}{fld}', '').strip()
                    if raw:
                        q[fld] = raw
                unit = request.POST.get(f'{prefix}answer_unit', '').strip()
                if unit:
                    q['answer_unit'] = unit

            # Number-line spec — edited as raw JSON in the preview; a parse
            # failure leaves the prior spec untouched so the import-time validator
            # surfaces the issue.
            if q['question_type'] == 'number_line':
                raw = request.POST.get(f'{prefix}number_line_spec', '').strip()
                if raw:
                    try:
                        q['number_line_spec'] = json.loads(raw)
                    except (ValueError, TypeError):
                        pass

            # Prime factorisation: the one number the answer is computed from.
            # A non-numeric edit keeps the prior value, so the import-time check
            # reports it rather than this silently storing nothing.
            if q['question_type'] == 'prime_factorization':
                raw = request.POST.get(f'{prefix}target_number', '').strip()
                if raw:
                    try:
                        q['target_number'] = int(raw)
                    except (TypeError, ValueError):
                        pass

            # Sketch-a-graph spec — same contract as the number line: raw JSON,
            # and a parse failure keeps the prior spec so the import-time
            # validator is the one that reports it.
            if q['question_type'] == 'sketch_graph':
                raw = request.POST.get(f'{prefix}sketch_spec', '').strip()
                if raw:
                    try:
                        q['sketch_spec'] = json.loads(raw)
                    except (ValueError, TypeError):
                        pass

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


_IMPORT_ROLES = [
    Role.INSTITUTE_OWNER, Role.HEAD_OF_INSTITUTE,
    Role.HEAD_OF_DEPARTMENT, Role.SENIOR_TEACHER,
    Role.TEACHER, Role.JUNIOR_TEACHER,
]


class PageImageView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """AJAX: full source-page PNG for the 'Adjust image' crop modal."""
    required_roles = _IMPORT_ROLES

    def get(self, request, session_id):
        from worksheets.image_adjust import page_image_response
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        return page_image_response(session, request)


class RecropView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """AJAX: re-render a question image from a teacher-drawn box on the PDF."""
    required_roles = _IMPORT_ROLES

    def post(self, request, session_id):
        from worksheets.image_adjust import recrop_response
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        return recrop_response(session, request)


class QuestionPreviewView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """AJAX: one extracted question rendered as the student will meet it.

    ``promote_blanks=True`` — ``save_questions_from_session`` calls
    ``apply_blank_format``, so a "___" sentence imported from here really does
    become a sentence with a box in each gap.
    """
    required_roles = _IMPORT_ROLES

    def post(self, request, session_id):
        from worksheets.question_preview import preview_response
        session = get_object_or_404(
            AIImportSession, pk=session_id, user=request.user, is_confirmed=False,
        )
        return preview_response(
            request,
            extracted_data=session.extracted_data,
            extracted_images=session.extracted_images,
            promote_blanks=True,
        )


class UploadImageView(RoleRequiredMixin, AIImportModuleRequiredMixin, View):
    """AJAX endpoint: upload an image to the session's image gallery."""
    required_roles = _IMPORT_ROLES

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

        # Record token usage only. The pages were charged at upload (see
        # UploadPDFView.post) because the classification job spends them there
        # — charging again here would bill the same PDF twice, and charging
        # ONLY here is what let an uploaded-but-never-confirmed import run for
        # free while homework and worksheets went unmetered entirely.
        if school:
            from django.db.models import F
            usage = _get_usage_for_school(school)
            AIImportUsage.objects.filter(pk=usage.pk).update(
                tokens_used=F('tokens_used') + (session.tokens_used or 0),
            )

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
                'blanks_built': result['blanks_built'],
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
