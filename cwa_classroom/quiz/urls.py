from django.urls import path
from . import views

urlpatterns = [
    # Basic Facts
    path('basic-facts/', views.BasicFactsHomeView.as_view(), name='basic_facts_home'),
    path('basic-facts/<str:subtopic>/', views.BasicFactsSelectView.as_view(), name='basic_facts_select'),
    path('basic-facts/<str:subtopic>/<int:level_number>/', views.BasicFactsQuizView.as_view(), name='basic_facts_quiz'),
    path('basic-facts/<str:subtopic>/<int:level_number>/results/', views.BasicFactsResultsView.as_view(), name='basic_facts_results'),

    # Times Tables
    path('times-tables/', views.TimesTablesHomeView.as_view(), name='times_tables_home'),
    path('level/<int:level_number>/multiplication/', views.TimesTablesSelectView.as_view(), {'operation': 'multiplication'}, name='multiplication_select'),
    path('level/<int:level_number>/division/', views.TimesTablesSelectView.as_view(), {'operation': 'division'}, name='division_select'),
    path('level/<int:level_number>/multiplication/<int:table>/', views.TimesTablesQuizView.as_view(), {'operation': 'multiplication'}, name='multiplication_quiz'),
    path('level/<int:level_number>/division/<int:table>/', views.TimesTablesQuizView.as_view(), {'operation': 'division'}, name='division_quiz'),
    path('times-tables/submit/<str:session_id>/', views.TimesTablesSubmitView.as_view(), name='times_tables_submit'),
    path('times-tables/results/<str:session_id>/', views.TimesTablesResultsView.as_view(), name='times_tables_results_view'),

    # Topic Quiz
    path('level/<int:level_number>/topic/<int:topic_id>/quiz/', views.TopicQuizView.as_view(), name='topic_quiz'),
    path('level/<int:level_number>/topic/<int:topic_id>/results/', views.TopicResultsView.as_view(), name='topic_results'),

    # Mixed Quiz
    path('level/<int:level_number>/quiz/', views.MixedQuizView.as_view(), name='mixed_quiz'),
    path('level/<int:level_number>/quiz/results/', views.MixedResultsView.as_view(), name='mixed_results'),
]
