from django.urls import path

from . import views

urlpatterns = [
    path(
        'admin-dashboard/ops/',
        views.OpsDashboardView.as_view(),
        name='ops_admin_dashboard',
    ),
    path(
        'admin-dashboard/ops/logs/',
        views.ErrorLogView.as_view(),
        name='ops_error_log',
    ),
]
