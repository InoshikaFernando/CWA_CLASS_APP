from django.urls import path
from . import views

urlpatterns = [
    path('audit/dashboard/', views.AuditDashboardView.as_view(), name='audit_dashboard'),
    path('audit/logs/', views.AuditLogListView.as_view(), name='audit_log_list'),
    path('audit/events/', views.EventsView.as_view(), name='audit_events'),
    path('audit/my-actions/', views.ActionHistoryView.as_view(), name='action_history'),
    path('audit/revert/<int:log_id>/', views.RevertActionView.as_view(), name='revert_action'),
]
