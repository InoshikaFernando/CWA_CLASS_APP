from django.urls import path

from . import views

app_name = 'ai_import'

urlpatterns = [
    path('upload/', views.UploadPDFView.as_view(), name='upload'),
    path('preview/<int:session_id>/', views.PreviewQuestionsView.as_view(), name='preview'),
    path('upload-image/<int:session_id>/', views.UploadImageView.as_view(), name='upload_image'),
    path('confirm/<int:session_id>/', views.ConfirmImportView.as_view(), name='confirm'),
    path('export/<int:session_id>/', views.ExportSessionView.as_view(), name='export'),
    path('plans/', views.TierSelectView.as_view(), name='tier_select'),
]
