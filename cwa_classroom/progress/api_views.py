import json
from django.http import JsonResponse
from django.views import View
from django.contrib.auth.mixins import LoginRequiredMixin
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from datetime import date, timedelta
from maths.models import TimeLog


@method_decorator(csrf_exempt, name='dispatch')
class UpdateTimeLogView(LoginRequiredMixin, View):
    def post(self, request):
        try:
            data = json.loads(request.body)
        except (json.JSONDecodeError, ValueError):
            data = {}

        seconds = int(data.get('seconds', 30))
        if seconds < 1 or seconds > 300:
            return JsonResponse({'error': 'invalid'}, status=400)

        log, _ = TimeLog.objects.get_or_create(student=request.user)

        # Use built-in reset helpers (they handle auto_now field quirks)
        log.reset_daily_if_needed()
        log.reset_weekly_if_needed()

        log.daily_total_seconds += seconds
        log.weekly_total_seconds += seconds
        log.save(update_fields=['daily_total_seconds', 'weekly_total_seconds'])

        return JsonResponse({
            'daily_seconds': log.daily_total_seconds,
            'weekly_seconds': log.weekly_total_seconds,
        })


# ---------------------------------------------------------------------------
# Period progress reports (v1 API)
# ---------------------------------------------------------------------------
# Read-only on purpose. A report is a frozen snapshot generated once after a
# period closes and never recomputed (see PeriodReport's docstring) — that is
# what keeps the PDF a parent downloads months later saying the same thing the
# notification said. An API that could edit one would break that guarantee.

from django.db.models import Q  # noqa: E402
from drf_spectacular.utils import OpenApiParameter, extend_schema  # noqa: E402
from rest_framework import mixins, viewsets  # noqa: E402

from api.filters import int_param
from api.scoping import scope_by_student  # noqa: E402
from billing.entitlements import school_ids_with_module  # noqa: E402
from billing.models import ModuleSubscription  # noqa: E402
from progress.api_serializers import (  # noqa: E402
    PeriodReportDetailSerializer, PeriodReportSummarySerializer,
)
from progress.models import PeriodReport  # noqa: E402


class PeriodReportViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin,
                          viewsets.GenericViewSet):
    """Progress reports for students the caller may read."""

    ordering_fields = ('period_start', 'generated_at')

    def get_serializer_class(self):
        if self.action == 'retrieve':
            return PeriodReportDetailSerializer
        return PeriodReportSummarySerializer

    @extend_schema(parameters=[
        OpenApiParameter('student', int, description='Filter to one student id.'),
        OpenApiParameter('period_type', str, description='weekly | monthly | term'),
        OpenApiParameter('subject', int, description='Filter to one subject id.'),
    ])
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_queryset(self):
        queryset = scope_by_student(
            PeriodReport.objects.select_related('student', 'subject', 'school'),
            self.request.user,
        )
        # Entitlement, applied to the rows rather than the request: this list
        # can span several schools (a parent with children at two institutes),
        # so one allow/deny for the whole response would be wrong in both
        # directions. Filtering also gives retrieve() its 404 for free, which
        # is the answer progress.access already chose over 403 — a reader must
        # not learn that another family's report exists.
        # A report with no school belongs to an individual learner, whose
        # access is their own subscription's business, not an institute's.
        queryset = queryset.filter(
            Q(school__isnull=True)
            | Q(school_id__in=school_ids_with_module(
                ModuleSubscription.MODULE_PROGRESS_REPORTS)),
        )
        params = self.request.query_params
        student_id = int_param(params, 'student')
        if student_id is not None:
            queryset = queryset.filter(student_id=student_id)
        if params.get('period_type'):
            queryset = queryset.filter(period_type=params['period_type'])
        subject_id = int_param(params, 'subject')
        if subject_id is not None:
            queryset = queryset.filter(subject_id=subject_id)
        return queryset.order_by('-period_start', 'period_type', 'id')
