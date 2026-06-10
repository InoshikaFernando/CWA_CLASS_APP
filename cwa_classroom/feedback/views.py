from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db.models import Case, IntegerField, Value, When
from django.shortcuts import get_object_or_404, render
from django.views import View

from billing.entitlements import get_school_for_user

from .forms import FeedbackForm
from .models import Feedback
from .owner import get_feedback_owner, is_feedback_owner


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
    """

    def get(self, request):
        return render(
            request,
            'feedback/_partials/feedback_modal.html',
            {'form': FeedbackForm()},
        )

    def post(self, request):
        form = FeedbackForm(request.POST)
        if not form.is_valid():
            return render(
                request,
                'feedback/_partials/feedback_modal.html',
                {'form': form},
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
            ),
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
