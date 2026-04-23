from django.urls import path
from . import views

app_name = 'brainbuzz'

urlpatterns = [
    # ── Teacher flows ────────────────────────────────────────────────────
    path('create/', views.create_session, name='create'),
    path('session/<str:join_code>/lobby/', views.teacher_lobby, name='teacher_lobby'),
    path('session/<str:join_code>/play/', views.teacher_ingame, name='teacher_ingame'),
    path('session/<str:join_code>/end/', views.teacher_end, name='teacher_end'),
    path('session/<str:join_code>/export/', views.export_csv, name='export_csv'),

    # ── Student flows ────────────────────────────────────────────────────
    path('join/', views.join, name='join'),
    path('play/<str:join_code>/', views.student_play, name='student_play'),

    # ── JSON API ─────────────────────────────────────────────────────────
    path('api/session/<str:join_code>/state/', views.api_session_state, name='api_session_state'),
    path('api/session/<str:join_code>/action/', views.api_teacher_action, name='api_teacher_action'),
    path('api/join/', views.api_join, name='api_join'),
    path('api/session/<str:join_code>/submit/', views.api_submit, name='api_submit'),
    path('api/session/<str:join_code>/leaderboard/', views.api_leaderboard, name='api_leaderboard'),
]
