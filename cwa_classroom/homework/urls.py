from django.urls import path

from . import views_teacher
from . import views_student
from . import views_parent
from . import views_htmx

app_name = 'homework'

urlpatterns = [
    # Teacher
    path('create/<int:class_id>/', views_teacher.HomeworkCreateView.as_view(), name='create'),
    path('<int:hw_id>/edit/', views_teacher.HomeworkEditView.as_view(), name='edit'),
    path('<int:hw_id>/delete/', views_teacher.HomeworkDeleteView.as_view(), name='delete'),
    path('<int:hw_id>/publish/', views_teacher.HomeworkPublishView.as_view(), name='publish'),
    path('class/<int:class_id>/', views_teacher.ClassHomeworkListView.as_view(), name='class_list'),
    path('<int:hw_id>/submissions/', views_teacher.SubmissionListView.as_view(), name='submissions'),
    path('<int:hw_id>/grade/<int:sub_id>/', views_teacher.GradeSubmissionView.as_view(), name='grade'),
    path('<int:hw_id>/publish-all/', views_teacher.BulkPublishView.as_view(), name='publish_all'),
    path('<int:hw_id>/export-csv/', views_teacher.ExportCSVView.as_view(), name='export_csv'),

    # Student
    path('', views_student.HomeworkDashboardView.as_view(), name='dashboard'),
    path('<int:hw_id>/', views_student.HomeworkDetailView.as_view(), name='detail'),
    path('<int:hw_id>/submit/', views_student.HomeworkSubmitView.as_view(), name='submit'),
    path('<int:hw_id>/mark-done/', views_student.MarkDoneView.as_view(), name='mark_done'),
    path('<int:hw_id>/quiz/', views_student.HomeworkQuizView.as_view(), name='start_quiz'),
    path('<int:hw_id>/quiz/submit/', views_student.SubmitHomeworkAnswerView.as_view(), name='submit_answer'),

    # Parent
    path('parent/', views_parent.ParentHomeworkView.as_view(), name='parent_dashboard'),

    # HTMX partials
    path('htmx/subtopics/', views_htmx.subtopics_for_topic, name='htmx_subtopics'),
]
