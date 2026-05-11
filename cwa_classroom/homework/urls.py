from django.urls import path
from . import views

app_name = 'homework'

urlpatterns = [
    # Teacher: topic-based homework
    path('homework/monitor/', views.HomeworkMonitorView.as_view(), name='teacher_monitor'),
    path('homework/class/<int:classroom_id>/create/', views.HomeworkCreateView.as_view(), name='teacher_create'),
    path('homework/<int:homework_id>/', views.HomeworkDetailView.as_view(), name='teacher_detail'),
    path('homework/<int:homework_id>/assign/', views.HomeworkAssignToClassView.as_view(), name='assign_to_class'),

    # Teacher: PDF upload flow
    path('homework/pdf/upload/', views.HomeworkPDFUploadView.as_view(), name='pdf_upload'),
    path('homework/pdf/processing/<int:session_id>/', views.HomeworkPDFProcessingView.as_view(), name='pdf_processing'),
    path('homework/pdf/status/<int:session_id>/', views.HomeworkPDFStatusView.as_view(), name='pdf_status'),
    path('homework/pdf/preview/<int:session_id>/', views.HomeworkPDFPreviewView.as_view(), name='pdf_preview'),
    path('homework/pdf/confirm/<int:session_id>/', views.HomeworkPDFConfirmView.as_view(), name='pdf_confirm'),

    # Teacher: grading review
    path('homework/review/', views.HomeworkPendingReviewView.as_view(), name='pending_review'),
    path('homework/review/<int:answer_id>/ai-grade/', views.HomeworkAIGradeView.as_view(), name='ai_grade_answer'),
    path('homework/review/<int:answer_id>/grade/', views.HomeworkGradeAnswerView.as_view(), name='grade_answer'),

    # Student
    path('homework/', views.StudentHomeworkListView.as_view(), name='student_list'),
    path('homework/<int:homework_id>/take/', views.StudentHomeworkTakeView.as_view(), name='student_take'),
    path('homework/result/<int:submission_id>/', views.StudentHomeworkResultView.as_view(), name='student_result'),
]
