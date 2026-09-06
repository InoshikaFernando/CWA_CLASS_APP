import logging

from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Value, When
from django.http import Http404
from django.shortcuts import get_object_or_404, render
from django.views import View

from billing.entitlements import get_school_for_user

from .forms import FeedbackForm
from .models import Feedback, FeedbackImage
from .owner import get_feedback_owner, is_feedback_owner

logger = logging.getLogger(__name__)

# Screenshot upload limits (CPP-324). Screenshots are pasted/dragged into the
# feedback modal; keep the count and size bounded so a runaway paste can't fill
# storage or blow the request body limit.
MAX_FEEDBACK_IMAGES = 5
MAX_FEEDBACK_IMAGE_BYTES = 10 * 1024 * 1024  # 10 MB each


def _validate_images(files):
    """Return an error string for an invalid screenshot set, else ``''``.

    Rejects non-image uploads and oversized files loudly (the modal shows the
    message) rather than silently dropping them — a user who attached proof of
    a bug should never have it vanish without explanation.
    """
    if len(files) > MAX_FEEDBACK_IMAGES:
        return f'Please attach at most {MAX_FEEDBACK_IMAGES} screenshots.'
    for f in files:
        if not (f.content_type or '').startswith('image/'):
            return f'"{f.name}" is not an image. Only image screenshots can be attached.'
        if f.size > MAX_FEEDBACK_IMAGE_BYTES:
            return f'"{f.name}" is too large. Each screenshot must be under 10 MB.'
    return ''


def _reported_question(request, raw_id):
    """The maths Question a report is scoped to, or ``None``.

    A question is reportable when the submitter could already be looking at it:
    a global (school-less) question, or one belonging to their own school.
    Anything else is treated as not found — the same 404-not-403 rule the rest
    of the app uses for cross-tenant access, so the modal never reveals that a
    question id exists in another school.
    """
    from maths.models import Question

    raw_id = (raw_id or '').strip()
    if not raw_id:
        return None
    try:
        question_id = int(raw_id)
    except (TypeError, ValueError):
        return None

    school = get_school_for_user(request.user)
    question = (Question.objects
                .select_related('topic', 'level')
                .filter(id=question_id)
                .first())
    if question is None:
        return None
    if question.school_id is not None and question.school_id != getattr(
            school, 'id', None):
        return None
    return question


def _safe_page_url(url):
    """Sanitise a submitter-supplied page URL before storing it.

    The value is rendered as a clickable link in the triage queue, so only
    same-origin relative paths and http(s) absolute URLs are kept. This blocks
    ``javascript:``/``data:`` scheme links (stored XSS when the owner clicks)
    and protocol-relative ``//host`` URLs.
    """
    url = (url or '').strip()
    if not url:
        return ''
    low = url.lower()
    if low.startswith('http://') or low.startswith('https://'):
        return url[:500]
    if url.startswith('/') and not url.startswith('//'):
        return url[:500]
    return ''


class SubmitFeedbackView(LoginRequiredMixin, View):
    """Capture surface (CPP-322).

    GET  → returns the modal form partial (loaded over HTMX).
    POST → validates and creates a Feedback record assigned to the product
           owner, returning a success partial; invalid submissions re-render
           the form partial with inline errors (HTTP 400).

    A ``question`` parameter scopes the report to one maths question (CPP-398).
    The same modal is reused rather than a second one being grown alongside it,
    so the screenshot handling, the Jira filing and the validation messages all
    stay in one place.
    """

    def get(self, request):
        question = _reported_question(request, request.GET.get('question'))
        if request.GET.get('question') and question is None:
            # An id that names nothing this user can see. Saying so beats
            # rendering the plain modal, which would look like the report had
            # been scoped when it had not.
            raise Http404('No such question.')
        initial = ({'category': Feedback.CATEGORY_BUG} if question else {})
        return render(
            request,
            'feedback/_partials/feedback_modal.html',
            {'form': FeedbackForm(initial=initial), 'question': question},
        )

    def post(self, request):
        form = FeedbackForm(request.POST)
        images = request.FILES.getlist('screenshots')
        image_error = _validate_images(images)
        raw_question_id = request.POST.get('question_id', '')
        question = _reported_question(request, raw_question_id)
        if not form.is_valid() or image_error:
            return render(
                request,
                'feedback/_partials/feedback_modal.html',
                {'form': form, 'image_error': image_error,
                 'question': question},
                status=400,
            )

        feedback = form.save(commit=False)
        feedback.submitted_by = request.user
        feedback.role = request.user.primary_role or ''
        feedback.school = get_school_for_user(request.user)
        feedback.page_url = _safe_page_url(
            request.POST.get('page_url', '')
            or request.META.get('HTTP_REFERER', '')
        )
        feedback.status = Feedback.STATUS_NEW
        feedback.assignee = get_feedback_owner()
        feedback.save()

        # Persist screenshots before enqueueing so the Jira task (which attaches
        # them) sees a complete set.
        for f in images:
            FeedbackImage.objects.create(feedback=feedback, image=f)

        # Scoped to a question (CPP-398) — record which one, so the question
        # health dashboard can raise it for review instead of the complaint
        # resting in a Jira queue while the question stays live.
        if question is not None:
            from maths.models import QuestionReport
            QuestionReport.objects.create(
                question=question,
                school=feedback.school,
                reported_by=request.user,
                feedback=feedback,
                note=feedback.description,
            )
        elif raw_question_id:
            # The id did not survive validation between opening the modal and
            # sending it. The feedback is still saved — losing what somebody
            # typed is worse than losing the link — but nothing false is
            # recorded against the bank, and the mismatch is not swallowed.
            logger.warning(
                'Feedback %s arrived with unusable question id %r from user '
                '%s — saved without a question report.',
                feedback.id, raw_question_id[:50], request.user.id,
            )

        # Bug reports get auto-filed to Jira (+ Discord) in the background. The
        # task is config-gated and idempotent, so enqueue unconditionally for
        # bugs; a queue-unavailable error must never fail the submission.
        if feedback.category == Feedback.CATEGORY_BUG:
            from taskqueue.services import enqueue_task
            from .tasks import report_bug_to_jira
            try:
                enqueue_task(
                    school=feedback.school,
                    user=request.user,
                    task_type='feedback_bug_report',
                    func=report_bug_to_jira,
                    args=[feedback.id],
                    queue='default',
                )
            except Exception:
                logger.exception(
                    'Failed to enqueue Jira bug report for feedback %s',
                    feedback.id,
                )

        return render(
            request,
            'feedback/_partials/feedback_success.html',
            {'feedback': feedback},
        )


class OwnerRequiredMixin(LoginRequiredMixin):
    """Restrict a view to the platform feedback owner (admin/superuser)."""

    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return self.handle_no_permission()
        if not is_feedback_owner(request.user):
            raise PermissionDenied("You don't have access to the feedback queue.")
        return super().dispatch(request, *args, **kwargs)


class TriageDashboardView(OwnerRequiredMixin, View):
    """Owner-facing review & triage queue (CPP-323).

    Lists all non-deleted feedback with category/status/priority filters,
    untriaged ('new') items first, paginated.
    """

    PER_PAGE = 25

    def get(self, request):
        queryset = (
            Feedback.objects.active()
            .select_related('submitted_by', 'school', 'assignee')
            .prefetch_related('images')
        )

        category = request.GET.get('category', '')
        status = request.GET.get('status', '')
        priority = request.GET.get('priority', '')

        valid_categories = {c for c, _ in Feedback.CATEGORY_CHOICES}
        valid_statuses = {s for s, _ in Feedback.STATUS_CHOICES}
        valid_priorities = {p for p, _ in Feedback.PRIORITY_CHOICES}

        if category in valid_categories:
            queryset = queryset.filter(category=category)
        if status in valid_statuses:
            queryset = queryset.filter(status=status)
        if priority in valid_priorities:
            queryset = queryset.filter(priority=priority)

        # Default view: untriaged (new) items first, then most recent.
        queryset = queryset.annotate(
            _new_first=Case(
                When(status=Feedback.STATUS_NEW, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by('_new_first', '-created_at')

        paginator = Paginator(queryset, self.PER_PAGE)
        page_obj = paginator.get_page(request.GET.get('page'))

        context = {
            'page_obj': page_obj,
            'items': page_obj.object_list,
            'category_choices': Feedback.CATEGORY_CHOICES,
            'status_choices': Feedback.STATUS_CHOICES,
            'priority_choices': Feedback.PRIORITY_CHOICES,
            'selected_category': category,
            'selected_status': status,
            'selected_priority': priority,
        }
        return render(request, 'feedback/triage_dashboard.html', context)


class UpdateFeedbackView(OwnerRequiredMixin, View):
    """Inline status/priority update from the triage queue (CPP-323).

    POSTs the updated status and/or priority and returns the refreshed row
    partial for an HTMX swap. Missing or soft-deleted items return 404.
    """

    def post(self, request, pk):
        item = get_object_or_404(
            Feedback.objects.active().select_related(
                'submitted_by', 'school', 'assignee',
            ).prefetch_related('images'),
            pk=pk,
        )

        valid_statuses = {s for s, _ in Feedback.STATUS_CHOICES}
        valid_priorities = {p for p, _ in Feedback.PRIORITY_CHOICES}

        update_fields = ['updated_at']

        status = request.POST.get('status')
        if status is not None and status in valid_statuses:
            item.status = status
            update_fields.append('status')

        if 'priority' in request.POST:
            priority = request.POST.get('priority') or None
            if priority is None or priority in valid_priorities:
                item.priority = priority
                update_fields.append('priority')

        item.save(update_fields=update_fields)

        return render(
            request,
            'feedback/_partials/feedback_row.html',
            {'item': item},
        )
