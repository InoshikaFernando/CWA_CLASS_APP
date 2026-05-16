from django.urls import path

from . import views, views_builder

app_name = 'worksheets'

urlpatterns = [
    # Teacher: worksheet builder (CPP-282 / CPP-283 / CPP-284)
    path('builder/', views_builder.WorksheetBuilderView.as_view(), name='builder'),
    path('builder/questions/', views_builder.WorksheetBuilderQuestionsView.as_view(), name='builder_questions'),
    path('builder/save/', views_builder.WorksheetBuilderSaveView.as_view(), name='builder_save'),

    # Teacher: worksheet library
    path('', views.WorksheetListView.as_view(), name='list'),
    path('upload/', views.WorksheetUploadView.as_view(), name='upload'),
    path('upload/<int:session_id>/preview/', views.WorksheetPreviewView.as_view(), name='preview'),
    path('upload/<int:session_id>/confirm/', views.WorksheetConfirmView.as_view(), name='confirm'),
    path('<int:pk>/', views.WorksheetDetailView.as_view(), name='detail'),
    path('<int:pk>/delete/', views.WorksheetDeleteView.as_view(), name='delete'),
    path('<int:pk>/assign/', views.WorksheetAssignView.as_view(), name='assign'),

    # Teacher: assignment management
    path('assignments/<int:pk>/', views.AssignmentDetailView.as_view(), name='assignment_detail'),
    path('assignments/<int:pk>/toggle/', views.AssignmentToggleView.as_view(), name='assignment_toggle'),

    # Student: assignment list + session
    path('my/', views.StudentWorksheetListView.as_view(), name='student_list'),
    path('assignments/<int:pk>/session/', views.WorksheetSessionView.as_view(), name='session'),
    path('assignments/<int:pk>/answer/', views.WorksheetAnswerView.as_view(), name='answer'),
    path('assignments/<int:pk>/results/', views.WorksheetResultsView.as_view(), name='results'),
]
