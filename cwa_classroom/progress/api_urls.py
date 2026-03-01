from django.urls import path
from . import api_views

urlpatterns = [
    path('update-time-log/', api_views.UpdateTimeLogView.as_view(), name='api_update_time_log'),
]
