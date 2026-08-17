"""Super-admin URLs for the maths app, mounted at the site root.

Kept separate from maths/urls.py because that module is included under the
/maths/ prefix, and admin dashboards live at /admin-dashboard/<name>/ —
the same convention as ops.urls.
"""
from django.urls import path

from . import views_admin

urlpatterns = [
    path(
        'admin-dashboard/question-health/',
        views_admin.QuestionHealthDashboardView.as_view(),
        name='question_health_admin_dashboard',
    ),
]
