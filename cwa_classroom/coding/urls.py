from django.urls import path
from . import views

app_name = 'coding'

urlpatterns = [

    # ── Home: language selector ──────────────────────────────────────────────
    path('', views.language_selector, name='home'),

    # ── Topic browsing ───────────────────────────────────────────────────────
    # e.g. /coding/python/
    path('<slug:lang_slug>/', views.topic_list, name='topic_list'),

    # e.g. /coding/python/variables/
    path('<slug:lang_slug>/topics/<slug:topic_slug>/', views.level_list, name='level_list'),

    # ── Exercises  (topic-based structured learning) ─────────────────────────
    # Canonical: /coding/python/topics/variables/beginner/
    path('<slug:lang_slug>/topics/<slug:topic_slug>/<str:level>/', views.exercise_list, name='exercise_list'),

    # Short form per CPP-119 spec: /coding/python/variables/beginner/
    path('<slug:lang_slug>/<slug:topic_slug>/<str:level>/', views.exercise_list, name='exercise_list_short'),

    # e.g. /coding/python/exercise/42/
    path('<slug:lang_slug>/exercise/<int:exercise_id>/', views.exercise_detail, name='exercise_detail'),

    # ── Problem Solving  (algorithm / logic problems) ────────────────────────
    # e.g. /coding/python/problems/
    path('<slug:lang_slug>/problems/', views.problem_list, name='problem_list'),

    # e.g. /coding/python/problems/7/
    path('<slug:lang_slug>/problems/<int:problem_id>/', views.problem_detail, name='problem_detail'),

    # ── Dashboard / progress ─────────────────────────────────────────────────
    path('<slug:lang_slug>/dashboard/', views.dashboard, name='dashboard'),

    # ── API endpoints ────────────────────────────────────────────────────────
    # Run code (topic exercises — output only, no test cases)
    path('api/run/', views.api_run_code, name='api_run_code'),

    # Submit against test cases (problem solving)
    path('api/submit/<int:problem_id>/', views.api_submit_problem, name='api_submit_problem'),

    # Time tracking (mirrors maths api/update-time-log/)
    path('api/update-time-log/', views.api_update_time_log, name='api_update_time_log'),

    # Piston health check — admin/staff only
    path('api/piston-health/', views.api_piston_health, name='api_piston_health'),
]