from django.urls import path
from django.views.generic import RedirectView
from . import views

app_name = "maths"
urlpatterns = [
    # ── Active views (dashboard, content browsing, question management) ──
    path("", views.dashboard, name="dashboard"),
    path("dashboard/", views.dashboard_detail, name="dashboard_detail"),
    path("topics/", views.topic_list, name="topics"),
    path("topic/<int:topic_id>/levels/", views.level_list, name="levels"),
    path("level/<int:level_number>/", views.level_detail, name="level_detail"),
    path("level/<int:level_number>/questions/", views.level_questions, name="level_questions"),
    path("level/<int:level_number>/add-question/", views.add_question, name="add_question"),
    path("profile/", views.user_profile, name="user_profile"),
    path("api/update-time-log/", views.update_time_log, name="update_time_log"),

    # ── Registration (still active) ──
    path("signup/student/", views.signup_student, name="signup_student"),
    path("signup/teacher/", views.signup_teacher, name="signup_teacher"),
    path("register/teacher-center/", views.teacher_center_registration, name="teacher_center_registration"),
    path("register/individual-student/", views.individual_student_registration, name="individual_student_registration"),
    path("bulk-student-registration/", views.bulk_student_registration, name="bulk_student_registration"),

    # ── DEPRECATED: Old quiz views → redirect to quiz app equivalents ──
    # These keep the URL names alive (templates using {% url 'maths:take_quiz' %} still work)
    # but redirect to the new quiz app views under /maths/ (quiz.urls).
    path("level/<int:level_number>/quiz/", views.take_quiz, name="take_quiz"),
    path("level/<slug:basic_topic>/<int:display_level>/quiz/", views.take_basic_facts_quiz, name="take_basic_facts_quiz"),
    path("basic-facts/<str:subtopic_name>/", views.basic_facts_subtopic, name="basic_facts_subtopic"),
    path("level/<int:level_number>/multiplication/", views.multiplication_selection, name="multiplication_selection"),
    path("level/<int:level_number>/division/", views.division_selection, name="division_selection"),
    path("level/<int:level_number>/multiplication/<int:table_number>/", views.multiplication_quiz, name="multiplication_quiz"),
    path("level/<int:level_number>/division/<int:table_number>/", views.division_quiz, name="division_quiz"),

    # ── DEPRECATED: Old topic-specific quiz views (will be removed in future) ──
    path("level/<int:level_number>/practice/", views.practice_questions, name="practice_questions"),
    path("level/<int:level_number>/measurements/", views.measurements_questions, name="measurements_questions"),
    path("level/<int:level_number>/measurements-progress/", views.measurements_progress, name="measurements_progress"),
    path("level/<int:level_number>/place-values/", views.place_values_questions, name="place_values_questions"),
    path("level/<int:level_number>/fractions/", views.fractions_questions, name="fractions_questions"),
    path("level/<int:level_number>/finance/", views.finance_questions, name="finance_questions"),
    path("level/<int:level_number>/date-time/", views.date_time_questions, name="date_time_questions"),
    path("level/<int:level_number>/bodmas/", views.bodmas_questions, name="bodmas_questions"),
    path("level/<int:level_number>/whole-numbers/", views.whole_numbers_questions, name="whole_numbers_questions"),
    path("level/<int:level_number>/integers/", views.integers_questions, name="integers_questions"),
    path("level/<int:level_number>/trigonometry/", views.trigonometry_questions, name="trigonometry_questions"),
    path("level/<int:level_number>/factors/", views.factors_questions, name="factors_questions"),
    path("level/<int:level_number>/angles/", views.angles_questions, name="angles_questions"),

    # ── DEPRECATED: Old API (quiz app has /api/submit-topic-answer/ at root) ──
    path("api/submit-topic-answer/", views.submit_topic_answer, name="submit_topic_answer"),
]
