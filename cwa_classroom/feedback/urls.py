from django.urls import path

from . import views

app_name = 'feedback'

urlpatterns = [
    # Capture (CPP-322)
    path('submit/', views.SubmitFeedbackView.as_view(), name='submit'),

    # Triage (CPP-323)
    path('triage/', views.TriageDashboardView.as_view(), name='triage'),
    path('triage/<int:pk>/update/', views.UpdateFeedbackView.as_view(), name='update'),
]
