from django.urls import path
from . import views

urlpatterns = [
    path('dashboard/', views.StudentDashboardView.as_view(), name='student_dashboard'),
    path('student/<int:student_id>/progress/', views.StudentDetailProgressView.as_view(), name='student_detail_progress'),
]
