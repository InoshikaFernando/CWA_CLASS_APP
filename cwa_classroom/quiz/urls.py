from django.urls import path
from . import views

urlpatterns = [
    # Basic Facts
    path('basic-facts/', views.BasicFactsHomeView.as_view(), name='basic_facts_home'),
    path('basic-facts/<str:subtopic>/', views.BasicFactsSelectView.as_view(), name='basic_facts_select'),
    path('basic-facts/<str:subtopic>/<int:level_number>/', views.BasicFactsQuizView.as_view(), name='basic_facts_quiz'),
    path('basic-facts/<str:subtopic>/<int:level_number>/results/', views.BasicFactsResultsView.as_view(), name='basic_facts_results'),

    # Times Tables (home + submit/results stay at root; level/ patterns live in level_urls.py under maths/)
    path('times-tables/', views.TimesTablesHomeView.as_view(), name='times_tables_home'),
    path('times-tables/submit/<str:session_id>/', views.TimesTablesSubmitView.as_view(), name='times_tables_submit'),
    path('times-tables/results/<str:session_id>/', views.TimesTablesResultsView.as_view(), name='times_tables_results_view'),

    # Attempt history (last 10 per quiz series) + per-attempt review. Own
    # history (no student id) or a specific student (teacher / parent), with
    # access checked in the view.
    path('quiz-history/', views.QuizAttemptHistoryView.as_view(), name='quiz_attempt_history'),
    path('quiz-history/<int:student_id>/', views.QuizAttemptHistoryView.as_view(), name='quiz_student_attempt_history'),
    path('quiz-attempt/<str:kind>/<int:pk>/review/', views.QuizAttemptReviewView.as_view(), name='quiz_attempt_review'),
]
# Topic and Mixed Quiz routes live in subject_urls.py (mounted at root with /<subject>/ prefix)
