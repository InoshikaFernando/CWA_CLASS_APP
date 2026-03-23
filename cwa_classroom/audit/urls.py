from django.urls import path
from . import views

urlpatterns = [
    path('audit/dashboard/', views.AuditDashboardView.as_view(), name='audit_dashboard'),
    path('audit/logs/', views.AuditLogListView.as_view(), name='audit_log_list'),
]
