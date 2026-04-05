from django.urls import path
from . import views

app_name = "maths"
urlpatterns = [
    # ── Dashboard & content browsing ──
    path("", views.dashboard, name="dashboard"),
    path("dashboard/", views.dashboard_detail, name="dashboard_detail"),
    path("topics/", views.topic_list, name="topics"),
    path("topic/<int:topic_id>/levels/", views.level_list, name="levels"),
    path("level/<int:level_number>/", views.level_detail, name="level_detail"),

    # ── Question management ──
    path("level/<int:level_number>/questions/", views.level_questions, name="level_questions"),
    path("level/<int:level_number>/add-question/", views.add_question, name="add_question"),

    # ── Profile & time tracking ──
    path("profile/", views.user_profile, name="user_profile"),
    path("api/update-time-log/", views.update_time_log, name="update_time_log"),

    # ── Registration (legacy) ──
    path("signup/student/", views.signup_student, name="signup_student"),
    path("signup/teacher/", views.signup_teacher, name="signup_teacher"),
    path("register/teacher-center/", views.teacher_center_registration, name="teacher_center_registration"),
    path("register/individual-student/", views.individual_student_registration, name="individual_student_registration"),
    path("bulk-student-registration/", views.bulk_student_registration, name="bulk_student_registration"),

    # ── Quiz views REMOVED ──
    # All quiz functionality now lives in the quiz app (quiz/urls.py),
    # included under /maths/ in the root urlconf.
    # Removed: take_quiz, take_basic_facts_quiz, basic_facts_subtopic,
    #   multiplication_selection, division_selection, multiplication_quiz,
    #   division_quiz, practice_questions, topic_questions,
    #   submit_topic_answer, and all topic-specific quiz wrappers.
]
