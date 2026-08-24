"""Period progress report routes (CPP-388).

A separate urlconf from ``progress.urls`` purely so these can live under the
``progress:`` namespace: adding ``app_name`` to the existing module would have
renamed ``student_dashboard`` and ``student_detail_progress``, which every
sidebar and half the templates reverse by their bare names.
"""

from django.urls import path

from . import views_reports

app_name = 'progress'

urlpatterns = [
    path('progress/reports/',
         views_reports.PeriodReportListView.as_view(), name='period_report_list'),
    path('progress/reports/<int:report_id>/',
         views_reports.PeriodReportDetailView.as_view(), name='period_report_detail'),
    path('progress/reports/<int:report_id>/pdf/',
         views_reports.PeriodReportPdfView.as_view(), name='period_report_pdf'),
]
