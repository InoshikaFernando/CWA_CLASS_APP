from django.urls import path
from . import views

app_name = 'homework'

urlpatterns = [
    # Teacher
    path('homework/monitor/', views.HomeworkMonitorView.as_view(), name='teacher_monitor'),
    path('homework/class/<int:classroom_id>/create/', views.HomeworkCreateView.as_view(), name='teacher_create'),
    path('homework/<int:homework_id>/', views.HomeworkDetailView.as_view(), name='teacher_detail'),

    # Student
    path('homework/', views.StudentHomeworkListView.as_view(), name='student_list'),
    path('homework/<int:homework_id>/take/', views.StudentHomeworkTakeView.as_view(), name='student_take'),
    path('homework/result/<int:submission_id>/', views.StudentHomeworkResultView.as_view(), name='student_result'),
]
