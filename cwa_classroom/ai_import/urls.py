from django.urls import path

from . import views

app_name = 'ai_import'

urlpatterns = [
    path('upload/', views.UploadPDFView.as_view(), name='upload'),
    path('processing/<int:session_id>/', views.ProcessingView.as_view(), name='processing'),
    path('status/<int:session_id>/', views.ImportStatusView.as_view(), name='status'),
    path('preview/<int:session_id>/', views.PreviewQuestionsView.as_view(), name='preview'),
    path('preview/<int:session_id>/page-image/', views.PageImageView.as_view(), name='pdf_page_image'),
    path('preview/<int:session_id>/recrop/', views.RecropView.as_view(), name='pdf_recrop'),
    path('preview/<int:session_id>/question-preview/',
         views.QuestionPreviewView.as_view(), name='question_preview'),
    path('upload-image/<int:session_id>/', views.UploadImageView.as_view(), name='upload_image'),
    path('confirm/<int:session_id>/', views.ConfirmImportView.as_view(), name='confirm'),
    path('export/<int:session_id>/', views.ExportSessionView.as_view(), name='export'),
    path('plans/', views.TierSelectView.as_view(), name='tier_select'),
]
