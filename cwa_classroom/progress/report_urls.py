"""Period progress report routes (CPP-388).

A separate urlconf from ``progress.urls`` purely so these can live under the
``progress:`` namespace: adding ``app_name`` to the existing module would have
renamed ``student_dashboard`` and ``student_detail_progress``, which every
sidebar and half the templates reverse by their bare names.
"""

from django.urls import path

from . import views_preview, views_reports, views_settings

app_name = 'progress'

urlpatterns = [
    path('progress/reports/',
         views_reports.PeriodReportListView.as_view(), name='period_report_list'),
    # Staff-only configuration. Sits above the <int:report_id> routes so
    # "settings" is never parsed as a report id.
    path('progress/reports/settings/',
         views_settings.ReportSettingsView.as_view(), name='report_settings'),
    path('progress/reports/preview/',
         views_preview.ReportPreviewView.as_view(), name='report_preview'),
    # Both sit above the <int:report_id> routes for the same reason "settings"
    # does: a literal path segment must never be parsed as a report id.
    path('progress/reports/preview/report/',
         views_preview.ReportPreviewDetailView.as_view(),
         name='report_preview_detail'),
    path('progress/reports/preview/report/pdf/',
         views_preview.ReportPreviewPdfView.as_view(),
         name='report_preview_pdf'),
    path('progress/reports/<int:report_id>/',
         views_reports.PeriodReportDetailView.as_view(), name='period_report_detail'),
    path('progress/reports/<int:report_id>/pdf/',
         views_reports.PeriodReportPdfView.as_view(), name='period_report_pdf'),
]
