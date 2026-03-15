from django.urls import path
from . import views
from . import views_admin
from . import views_department
from . import views_teacher
from . import views_student
from . import views_progress
from . import views_hierarchy

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
    path('class/<int:class_id>/edit/', views.EditClassView.as_view(), name='edit_class'),
    path('class/<int:class_id>/assign-students/', views.AssignStudentsView.as_view(), name='assign_students'),
    path('class/<int:class_id>/assign-teachers/', views.AssignTeachersView.as_view(), name='assign_teachers'),
    path('class/<int:class_id>/attendance/', views.ClassAttendanceView.as_view(), name='class_attendance'),
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

    # Admin dashboard & school management
    path('admin-dashboard/', views_admin.AdminDashboardView.as_view(), name='admin_dashboard'),
    path('admin-dashboard/schools/create/', views_admin.SchoolCreateView.as_view(), name='admin_school_create'),
    path('admin-dashboard/manage-teachers/', views_admin.ManageTeachersRedirectView.as_view(), name='admin_manage_teachers'),
    path('admin-dashboard/manage-students/', views_admin.ManageStudentsRedirectView.as_view(), name='admin_manage_students'),
    path('admin-dashboard/schools/<int:school_id>/', views_admin.SchoolDetailView.as_view(), name='admin_school_detail'),
    path('admin-dashboard/schools/<int:school_id>/teachers/', views_admin.SchoolTeacherManageView.as_view(), name='admin_school_teachers'),
    path('admin-dashboard/schools/<int:school_id>/teachers/<int:teacher_id>/edit/', views_admin.SchoolTeacherEditView.as_view(), name='admin_school_teacher_edit'),
    path('admin-dashboard/schools/<int:school_id>/teachers/<int:teacher_id>/remove/', views_admin.SchoolTeacherRemoveView.as_view(), name='admin_school_teacher_remove'),
    path('admin-dashboard/schools/<int:school_id>/academic-year/create/', views_admin.AcademicYearCreateView.as_view(), name='admin_academic_year_create'),

    # Student management (school-level)
    path('admin-dashboard/schools/<int:school_id>/students/', views_admin.SchoolStudentManageView.as_view(), name='admin_school_students'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/edit/', views_admin.SchoolStudentEditView.as_view(), name='admin_school_student_edit'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/remove/', views_admin.SchoolStudentRemoveView.as_view(), name='admin_school_student_remove'),

    # Custom level management (school-level)
    path('admin-dashboard/schools/<int:school_id>/levels/', views_admin.SchoolLevelManageView.as_view(), name='admin_school_levels'),
    path('admin-dashboard/schools/<int:school_id>/levels/<int:level_id>/edit/', views_admin.SchoolLevelEditView.as_view(), name='admin_school_level_edit'),
    path('admin-dashboard/schools/<int:school_id>/levels/<int:level_id>/remove/', views_admin.SchoolLevelRemoveView.as_view(), name='admin_school_level_remove'),

    # Department management (within a school)
    path('admin-dashboard/schools/<int:school_id>/departments/', views_department.DepartmentListView.as_view(), name='admin_school_departments'),
    path('admin-dashboard/schools/<int:school_id>/departments/create/', views_department.DepartmentCreateView.as_view(), name='admin_department_create'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/', views_department.DepartmentDetailView.as_view(), name='admin_department_detail'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/edit/', views_department.DepartmentEditView.as_view(), name='admin_department_edit'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/assign-hod/', views_department.DepartmentAssignHoDView.as_view(), name='admin_department_assign_hod'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/teachers/', views_department.DepartmentManageTeachersView.as_view(), name='admin_department_teachers'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/assign-classes/', views_department.DepartmentAssignClassesView.as_view(), name='admin_department_assign_classes'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/levels/', views_department.DepartmentManageLevelsView.as_view(), name='admin_department_levels'),

    # Teacher dashboard & management
    path('teacher/', views_teacher.TeacherDashboardView.as_view(), name='teacher_dashboard'),
    path('teacher/switch-school/', views_teacher.SchoolSwitcherView.as_view(), name='school_switcher'),
    path('teacher/enrollment-requests/', views_teacher.EnrollmentRequestsView.as_view(), name='enrollment_requests'),
    path('teacher/enrollment/<int:enrollment_id>/approve/', views_teacher.EnrollmentApproveView.as_view(), name='enrollment_approve'),
    path('teacher/enrollment/<int:enrollment_id>/reject/', views_teacher.EnrollmentRejectView.as_view(), name='enrollment_reject'),
    path('teacher/session/<int:session_id>/attendance/', views_teacher.SessionAttendanceView.as_view(), name='session_attendance'),
    path('teacher/session/<int:session_id>/self-attendance/', views_teacher.TeacherSelfAttendanceView.as_view(), name='teacher_self_attendance'),
    path('teacher/attendance-approvals/', views_teacher.StudentAttendanceApprovalListView.as_view(), name='attendance_approvals'),
    path('teacher/attendance/<int:attendance_id>/approve/', views_teacher.StudentAttendanceApproveView.as_view(), name='attendance_approve'),
    path('teacher/attendance/<int:attendance_id>/reject/', views_teacher.StudentAttendanceRejectView.as_view(), name='attendance_reject'),
    path('teacher/attendance/bulk-approve/', views_teacher.StudentAttendanceBulkApproveView.as_view(), name='attendance_bulk_approve'),

    # Session management
    path('teacher/class/<int:class_id>/start-session/', views_teacher.StartSessionView.as_view(), name='start_session'),
    path('teacher/class/<int:class_id>/create-session/', views_teacher.CreateSessionView.as_view(), name='create_session'),
    path('teacher/session/<int:session_id>/complete/', views_teacher.CompleteSessionView.as_view(), name='complete_session'),
    path('teacher/session/<int:session_id>/cancel/', views_teacher.CancelSessionView.as_view(), name='cancel_session'),

    # Student enrollment & classes
    path('student/join/', views_student.JoinClassByCodeView.as_view(), name='student_join_class'),
    path('student/my-classes/', views_student.MyClassesView.as_view(), name='student_my_classes'),
    path('student/class/<int:class_id>/', views_student.StudentClassDetailView.as_view(), name='student_class_detail'),
    path('student/attendance/', views_student.StudentAttendanceHistoryView.as_view(), name='student_attendance_history'),
    path('student/session/<int:session_id>/mark-attendance/', views_student.StudentSelfMarkAttendanceView.as_view(), name='student_mark_attendance'),
    path('student/enroll-global/<int:class_id>/', views_student.EnrollGlobalClassView.as_view(), name='student_enroll_global_class'),

    # Progress criteria & tracking
    path('progress/criteria/', views_progress.ProgressCriteriaListView.as_view(), name='progress_criteria_list'),
    path('progress/criteria/create/', views_progress.ProgressCriteriaCreateView.as_view(), name='progress_criteria_create'),
    path('progress/criteria/<int:criteria_id>/submit/', views_progress.ProgressCriteriaSubmitView.as_view(), name='progress_criteria_submit'),
    path('progress/criteria/approvals/', views_progress.ProgressCriteriaApprovalListView.as_view(), name='progress_criteria_approvals'),
    path('progress/criteria/<int:criteria_id>/approve/', views_progress.ProgressCriteriaApproveView.as_view(), name='progress_criteria_approve'),
    path('progress/criteria/<int:criteria_id>/reject/', views_progress.ProgressCriteriaRejectView.as_view(), name='progress_criteria_reject'),
    path('progress/class/<int:class_id>/record/', views_progress.RecordProgressView.as_view(), name='record_progress'),
    path('progress/student/<int:student_id>/', views_progress.StudentProgressView.as_view(), name='student_progress'),

    # API
    path('api/department/<int:dept_id>/levels/', views.DepartmentLevelsAPIView.as_view(), name='api_department_levels'),

    # School hierarchy
    path('school-hierarchy/', views_hierarchy.SchoolHierarchyView.as_view(), name='school_hierarchy_auto'),
    path('school-hierarchy/<int:school_id>/', views_hierarchy.SchoolHierarchyView.as_view(), name='school_hierarchy'),

    # HoD
    path('department/', views.HoDOverviewView.as_view(), name='hod_overview'),
    path('department/manage-classes/', views.HoDManageClassesView.as_view(), name='hod_manage_classes'),
    path('department/create-class/', views.HoDCreateClassView.as_view(), name='hod_create_class'),
    path('department/assign-class/', views.HoDAssignClassView.as_view(), name='hod_assign_class'),
    path('department/workload/', views.HoDWorkloadView.as_view(), name='hod_workload'),
    path('department/reports/', views.HoDReportsView.as_view(), name='hod_reports'),
    path('department/attendance/', views.HoDAttendanceReportView.as_view(), name='hod_attendance_report'),

    # Accounting
    path('accounting/', views.AccountingDashboardView.as_view(), name='accounting_dashboard'),
    path('accounting/packages/', views.AccountingPackagesView.as_view(), name='accounting_packages'),
    path('accounting/users/', views.AccountingUsersView.as_view(), name='accounting_users'),
    path('accounting/export/', views.AccountingExportView.as_view(), name='accounting_export'),
    path('accounting/refunds/', views.AccountingRefundsView.as_view(), name='accounting_refunds'),
    path('accounting/refund/<int:payment_id>/', views.ProcessRefundView.as_view(), name='process_refund'),
]
