from django.urls import path

from . import views

urlpatterns = [
    path(
        'admin-dashboard/usage/overview/',
        views.UsageOverviewView.as_view(),
        name='usage_admin_overview',
    ),
]
