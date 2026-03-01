from django.urls import path
from . import views

urlpatterns = [
    path('submit-topic-answer/', views.SubmitTopicAnswerView.as_view(), name='api_submit_topic_answer'),
    path('topic-next/<str:session_id>/', views.TopicNextQuestionView.as_view(), name='api_topic_next'),
    path('tt-answer/', views.TimesTablesAnswerView.as_view(), name='api_tt_answer'),
    path('tt-next/<str:session_id>/', views.TimesTablesNextView.as_view(), name='api_tt_next'),
]
