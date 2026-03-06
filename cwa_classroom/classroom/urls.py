from django.urls import path
from . import views

urlpatterns = [
    # NOTE: The old HomeView at '/' has been replaced by PublicHomeView + SubjectsHubView
    # in the project-level urls.py. HomeView is kept at /app-home/ as a fallback.
    path('app-home/', views.HomeView.as_view(), name='home'),
    path('dashboard/', views.StudentDashboardView.as_view(), name='student_dashboard'),
    path('topics/', views.TopicsView.as_view(), name='topics'),
    path('topic/<int:topic_id>/levels/', views.TopicLevelsView.as_view(), name='topic_levels'),
    path('level/<int:level_number>/', views.LevelDetailView.as_view(), name='level_detail'),

    # Class management
    path('create-class/', views.CreateClassView.as_view(), name='create_class'),
    path('class/<int:class_id>/', views.ClassDetailView.as_view(), name='class_detail'),
    path('class/<int:class_id>/assign-students/', views.AssignStudentsView.as_view(), name='assign_students'),
    path('class/<int:class_id>/assign-teachers/', views.AssignTeachersView.as_view(), name='assign_teachers'),
    path('class/<int:class_id>/progress/', views.ClassProgressView.as_view(), name='class_progress'),
    path('class/progress/', views.ClassProgressListView.as_view(), name='class_progress_list'),
    path('class/manage-teachers/', views.ManageTeachersView.as_view(), name='manage_teachers'),

    # Bulk registration
    path('bulk-student-registration/', views.BulkStudentRegistrationView.as_view(), name='bulk_student_registration'),

    # Question management
    path('upload-questions/', views.UploadQuestionsView.as_view(), name='upload_questions'),
    path('level/<int:level_number>/questions/', views.QuestionListView.as_view(), name='question_list'),
    path('level/<int:level_number>/add-question/', views.AddQuestionView.as_view(), name='add_question'),
    path('question/<int:question_id>/edit/', views.EditQuestionView.as_view(), name='edit_question'),
    path('question/<int:question_id>/delete/', views.DeleteQuestionView.as_view(), name='delete_question'),

    # HoD
    path('department/', views.HoDOverviewView.as_view(), name='hod_overview'),
    path('department/manage-classes/', views.HoDManageClassesView.as_view(), name='hod_manage_classes'),
    path('department/workload/', views.HoDWorkloadView.as_view(), name='hod_workload'),
    path('department/reports/', views.HoDReportsView.as_view(), name='hod_reports'),

    # Accounting
    path('accounting/', views.AccountingDashboardView.as_view(), name='accounting_dashboard'),
    path('accounting/packages/', views.AccountingPackagesView.as_view(), name='accounting_packages'),
    path('accounting/users/', views.AccountingUsersView.as_view(), name='accounting_users'),
    path('accounting/export/', views.AccountingExportView.as_view(), name='accounting_export'),
    path('accounting/refunds/', views.AccountingRefundsView.as_view(), name='accounting_refunds'),
    path('accounting/refund/<int:payment_id>/', views.ProcessRefundView.as_view(), name='process_refund'),
]
