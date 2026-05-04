from django.urls import path
from . import views
from . import views_upload
from . import views_quiz

app_name = 'brainbuzz'

urlpatterns = [
    # ── Teacher flows ────────────────────────────────────────────────────
    path('create/', views.create_session, name='create'),
    path('session/<str:join_code>/lobby/', views.teacher_lobby, name='teacher_lobby'),
    path('session/<str:join_code>/play/', views.teacher_ingame, name='teacher_ingame'),
    path('session/<str:join_code>/end/', views.teacher_end, name='teacher_end'),
    path('session/<str:join_code>/export/', views.export_csv, name='export_csv'),
    path('session/<str:join_code>/repeat/', views.repeat_session, name='repeat_session'),

    # ── Student flows ────────────────────────────────────────────────────
    path('join/', views.join, name='join'),
    path('play/<str:join_code>/', views.student_play, name='student_play'),

    # ── Quiz Builder ─────────────────────────────────────────────────────
    path('quizzes/', views_quiz.quiz_list, name='quiz_list'),
    path('quizzes/create/', views_quiz.quiz_create, name='quiz_create'),
    path('quizzes/<int:quiz_id>/build/', views_quiz.quiz_builder, name='quiz_builder'),
    path('quizzes/<int:quiz_id>/delete/', views_quiz.quiz_delete, name='quiz_delete'),
    path('quizzes/<int:quiz_id>/publish/', views_quiz.quiz_publish, name='quiz_publish'),
    path('quizzes/<int:quiz_id>/launch/', views_quiz.quiz_launch, name='quiz_launch'),

    # ── Question uploads ─────────────────────────────────────────────────
    path('upload/', views_upload.upload_questions, name='upload_questions'),
    path('upload/results/', views_upload.upload_results, name='upload_results'),
    path('upload/sample/<str:file_format>/', views_upload.download_sample_template, name='download_sample_template'),

    # ── JSON API — sessions ───────────────────────────────────────────────
    path('api/session/<str:join_code>/state/', views.api_session_state, name='api_session_state'),
    path('api/session/<str:join_code>/action/', views.api_teacher_action, name='api_teacher_action'),
    path('api/join/', views.api_join, name='api_join'),
    path('api/session/<str:join_code>/submit/', views.api_submit, name='api_submit'),
    path('api/session/<str:join_code>/leaderboard/', views.api_leaderboard, name='api_leaderboard'),
    path('api/upload/', views_upload.api_upload_questions, name='api_upload'),
    path('api/questions/', views_upload.api_questions_list, name='api_questions_list'),

    # ── JSON API — quiz builder ───────────────────────────────────────────
    path('api/quizzes/<int:quiz_id>/', views_quiz.api_quiz_detail, name='api_quiz_detail'),
    path('api/quizzes/<int:quiz_id>/meta/', views_quiz.api_quiz_meta, name='api_quiz_meta'),
    path('api/quizzes/<int:quiz_id>/questions/', views_quiz.api_quiz_questions, name='api_quiz_questions'),
    path('api/quizzes/<int:quiz_id>/questions/<int:q_id>/', views_quiz.api_quiz_question_detail, name='api_quiz_question_detail'),
    path('api/quizzes/<int:quiz_id>/reorder/', views_quiz.api_quiz_reorder, name='api_quiz_reorder'),
]
