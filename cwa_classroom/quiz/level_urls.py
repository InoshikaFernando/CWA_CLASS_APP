"""
Quiz level/ URL patterns — included under the maths/ prefix in the main urlconf.
Resulting URLs:  /maths/level/<n>/...
"""
from django.urls import path
from . import views

urlpatterns = [
    # Times Tables selection (per level)
    path('level/<int:level_number>/multiplication/', views.TimesTablesSelectView.as_view(), {'operation': 'multiplication'}, name='multiplication_select'),
    path('level/<int:level_number>/division/', views.TimesTablesSelectView.as_view(), {'operation': 'division'}, name='division_select'),
    path('level/<int:level_number>/multiplication/<int:table>/', views.TimesTablesQuizView.as_view(), {'operation': 'multiplication'}, name='multiplication_quiz'),
    path('level/<int:level_number>/division/<int:table>/', views.TimesTablesQuizView.as_view(), {'operation': 'division'}, name='division_quiz'),

    # Topic Quiz
    path('level/<int:level_number>/topic/<int:topic_id>/quiz/', views.TopicQuizView.as_view(), name='topic_quiz'),
    path('level/<int:level_number>/topic/<int:topic_id>/results/', views.TopicResultsView.as_view(), name='topic_results'),

    # Mixed Quiz
    path('level/<int:level_number>/quiz/', views.MixedQuizView.as_view(), name='mixed_quiz'),
    path('level/<int:level_number>/quiz/results/', views.MixedResultsView.as_view(), name='mixed_results'),
]
