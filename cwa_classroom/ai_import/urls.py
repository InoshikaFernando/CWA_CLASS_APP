from django.urls import path

from . import views

app_name = 'ai_import'

urlpatterns = [
    path('upload/', views.UploadPDFView.as_view(), name='upload'),
    path('preview/<int:session_id>/', views.PreviewQuestionsView.as_view(), name='preview'),
    path('confirm/<int:session_id>/', views.ConfirmImportView.as_view(), name='confirm'),
    path('plans/', views.TierSelectView.as_view(), name='tier_select'),
]
