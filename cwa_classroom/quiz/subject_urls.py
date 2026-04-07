"""
Subject-generic quiz routes — mounted at root so the subject slug is part of the URL.

  /<subject>/level/<n>/topic/<id>/quiz/
  /<subject>/level/<n>/topic/<id>/results/
  /<subject>/level/<n>/quiz/
  /<subject>/level/<n>/quiz/results/

Examples:
  /maths/level/4/topic/7/quiz/
  /coding/level/2/topic/3/quiz/
  /science/level/5/topic/1/results/
"""

from django.urls import path
from . import views

urlpatterns = [
    path('<slug:subject>/level/<int:level_number>/topic/<int:topic_id>/quiz/',
         views.TopicQuizView.as_view(), name='topic_quiz'),
    path('<slug:subject>/level/<int:level_number>/topic/<int:topic_id>/results/',
         views.TopicResultsView.as_view(), name='topic_results'),
    path('<slug:subject>/level/<int:level_number>/quiz/',
         views.MixedQuizView.as_view(), name='mixed_quiz'),
    path('<slug:subject>/level/<int:level_number>/quiz/results/',
         views.MixedResultsView.as_view(), name='mixed_results'),
]
