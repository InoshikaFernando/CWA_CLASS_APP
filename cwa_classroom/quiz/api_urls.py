from django.urls import path
from .views import (
    SubmitTopicAnswerView,
    TopicNextQuestionView,
    TimesTablesAnswerView,
    TimesTablesNextView,
)

urlpatterns = [
    path('submit-topic-answer/', SubmitTopicAnswerView.as_view(), name='api_submit_topic_answer'),
    path('topic-next/<str:session_id>/', TopicNextQuestionView.as_view(), name='api_topic_next'),
    path('tt-answer/', TimesTablesAnswerView.as_view(), name='api_tt_answer'),
    path('tt-next/<str:session_id>/', TimesTablesNextView.as_view(), name='api_tt_next'),
]
