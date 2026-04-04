from django.urls import path
from . import views
from . import views_admin
from . import views_department
from . import views_email
from . import views_teacher
from . import views_student
from . import views_progress
from . import views_hierarchy
from . import views_invoicing
from . import views_salaries
from . import views_parent
from . import views_parent_admin
from attendance import views_student as attendance_views_student

urlpatterns = [
    # NOTE: The old HomeView at '/' has been replaced by PublicHomeView + SubjectsHubView
    # in the project-level urls.py. HomeView is kept at /app-home/ as a fallback.
    path('app-home/', views.HomeView.as_view(), name='home'),
    path('student-dashboard/', views.StudentDashboardView.as_view(), name='student_dashboard'),
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
    path('class/<int:class_id>/settings/', views_department.ClassSettingsView.as_view(), name='class_settings'),
    path('class/progress/', views.ClassProgressListView.as_view(), name='class_progress_list'),
    path('class/manage-teachers/', views.ManageTeachersView.as_view(), name='manage_teachers'),

    # Bulk registration
    path('bulk-student-registration/', views.BulkStudentRegistrationView.as_view(), name='bulk_student_registration'),

    # CSV student import
    path('import-students/', views.StudentCSVUploadView.as_view(), name='student_csv_upload'),
    path('import-students/preview/', views.StudentCSVPreviewView.as_view(), name='student_csv_preview'),
    path('import-students/map-structure/', views.StudentCSVStructureMappingView.as_view(), name='student_csv_structure_mapping'),
    path('import-students/confirm/', views.StudentCSVConfirmView.as_view(), name='student_csv_confirm'),
    path('import-students/credentials/', views.StudentCSVCredentialsView.as_view(), name='student_csv_credentials'),

    # CSV balance import
    path('import-balances/', views.BalanceCSVUploadView.as_view(), name='balance_csv_upload'),
    path('import-balances/preview/', views.BalanceCSVPreviewView.as_view(), name='balance_csv_preview'),
    path('import-balances/confirm/', views.BalanceCSVConfirmView.as_view(), name='balance_csv_confirm'),

    # CSV teacher import
    path('import-teachers/', views.TeacherCSVUploadView.as_view(), name='teacher_csv_upload'),
    path('import-teachers/preview/', views.TeacherCSVPreviewView.as_view(), name='teacher_csv_preview'),
    path('import-teachers/confirm/', views.TeacherCSVConfirmView.as_view(), name='teacher_csv_confirm'),
    path('import-teachers/credentials/', views.TeacherCSVCredentialsView.as_view(), name='teacher_csv_credentials'),

    # CSV parent import
    path('import-parents/', views.ParentCSVUploadView.as_view(), name='parent_csv_upload'),
    path('import-parents/preview/', views.ParentCSVPreviewView.as_view(), name='parent_csv_preview'),
    path('import-parents/confirm/', views.ParentCSVConfirmView.as_view(), name='parent_csv_confirm'),
    path('import-parents/credentials/', views.ParentCSVCredentialsView.as_view(), name='parent_csv_credentials'),

    # Question management
    path('upload-questions/', views.UploadQuestionsView.as_view(), name='upload_questions'),
    path('create-question/', views.AddQuestionView.as_view(), name='create_question'),
    path('level/<int:level_number>/questions/', views.QuestionListView.as_view(), name='question_list'),
    path('level/<int:level_number>/add-question/', views.AddQuestionView.as_view(), name='add_question'),
    path('question/<int:question_id>/edit/', views.EditQuestionView.as_view(), name='edit_question'),
    path('question/<int:question_id>/delete/', views.DeleteQuestionView.as_view(), name='delete_question'),
    # HTMX cascading dropdowns for question form
    path('htmx/topics-for-level/', views.htmx_topics_for_level, name='htmx_topics_for_level'),

    # Admin dashboard & school management
    path('admin-dashboard/', views_admin.AdminDashboardView.as_view(), name='admin_dashboard'),
    path('admin-dashboard/schools/create/', views_admin.SchoolCreateView.as_view(), name='admin_school_create'),
    path('admin-dashboard/manage-settings/', views_admin.ManageSettingsRedirectView.as_view(), name='admin_manage_settings'),
    path('admin-dashboard/manage-teachers/', views_admin.ManageTeachersRedirectView.as_view(), name='admin_manage_teachers'),
    path('admin-dashboard/manage-students/', views_admin.ManageStudentsRedirectView.as_view(), name='admin_manage_students'),
    path('admin-dashboard/manage-departments/', views_admin.ManageDepartmentsRedirectView.as_view(), name='admin_manage_departments'),
    path('admin-dashboard/manage-subjects/', views_admin.ManageSubjectsRedirectView.as_view(), name='admin_manage_subjects'),
    path('admin-dashboard/manage-terms/', views_admin.ManageTermsRedirectView.as_view(), name='admin_manage_terms'),
    path('admin-dashboard/manage-parents/', views_parent_admin.ManageParentsRedirectView.as_view(), name='admin_manage_parents'),
    path('admin-dashboard/manage-holidays/', views_admin.ManageHolidaysRedirectView.as_view(), name='admin_manage_holidays'),
    path('admin-dashboard/manage-parent-invites/', views_admin.ManageParentInvitesRedirectView.as_view(), name='admin_manage_parent_invites'),
    path('admin-dashboard/schools/<int:school_id>/subjects/', views_admin.SchoolSubjectManageView.as_view(), name='admin_school_subjects'),
    path('admin-dashboard/schools/<int:school_id>/', views_admin.SchoolDetailView.as_view(), name='admin_school_detail'),
    path('admin-dashboard/schools/<int:school_id>/edit/', views_admin.SchoolEditView.as_view(), name='admin_school_edit'),
    path('admin-dashboard/schools/<int:school_id>/settings/', views_admin.SchoolSettingsView.as_view(), name='admin_school_settings'),
    path('admin-dashboard/schools/<int:school_id>/toggle-active/', views_admin.SchoolToggleActiveView.as_view(), name='admin_school_toggle_active'),
    path('admin-dashboard/schools/<int:school_id>/delete/', views_admin.SchoolDeleteView.as_view(), name='admin_school_delete'),
    path('admin-dashboard/schools/<int:school_id>/publish/', views_admin.SchoolPublishView.as_view(), name='admin_school_publish'),
    path('admin-dashboard/schools/<int:school_id>/teachers/', views_admin.SchoolTeacherManageView.as_view(), name='admin_school_teachers'),
    path('admin-dashboard/schools/<int:school_id>/teachers/<int:teacher_id>/edit/', views_admin.SchoolTeacherEditView.as_view(), name='admin_school_teacher_edit'),
    path('admin-dashboard/schools/<int:school_id>/teachers/<int:teacher_id>/remove/', views_admin.SchoolTeacherRemoveView.as_view(), name='admin_school_teacher_remove'),
    path('admin-dashboard/schools/<int:school_id>/teachers/<int:teacher_id>/restore/', views_admin.SchoolTeacherRestoreView.as_view(), name='admin_school_teacher_restore'),
    path('admin-dashboard/schools/<int:school_id>/teachers/batch-update/', views_admin.SchoolTeacherBatchUpdateView.as_view(), name='admin_school_teacher_batch_update'),
    path('admin-dashboard/schools/<int:school_id>/academic-year/create/', views_admin.AcademicYearCreateView.as_view(), name='admin_academic_year_create'),
    path('admin-dashboard/schools/<int:school_id>/academic-year/<int:academic_year_id>/edit/', views_admin.AcademicYearEditView.as_view(), name='admin_academic_year_edit'),
    path('admin-dashboard/schools/<int:school_id>/academic-year/<int:academic_year_id>/term-setup/', views_admin.AcademicYearTermSetupView.as_view(), name='admin_academic_year_term_setup'),
    path('admin-dashboard/schools/<int:school_id>/academic-year/<int:academic_year_id>/calendar/', views_admin.AcademicYearCalendarView.as_view(), name='admin_academic_year_calendar'),
    path('admin-dashboard/schools/<int:school_id>/holidays/', views_admin.SchoolHolidayManageView.as_view(), name='admin_school_holidays'),
    path('admin-dashboard/schools/<int:school_id>/public-holidays/', views_admin.PublicHolidayManageView.as_view(), name='admin_public_holidays'),
    path('admin-dashboard/schools/<int:school_id>/terms/', views_admin.TermManageView.as_view(), name='admin_school_terms'),
    path('admin-dashboard/schools/<int:school_id>/holidays/', views_admin.HolidayManageView.as_view(), name='admin_school_holidays'),

    # Platform management (superuser only)
    path('admin-dashboard/subject-apps/', views_admin.SubjectAppManageView.as_view(), name='admin_subject_apps'),

    # Database backup (superuser only)
    path('admin-dashboard/database-backup/', views_admin.DatabaseBackupView.as_view(), name='database_backup'),

    # Account blocking & school suspension
    path('admin-dashboard/block-user/', views_admin.BlockUserView.as_view(), name='admin_block_user'),
    path('admin-dashboard/unblock-user/', views_admin.UnblockUserView.as_view(), name='admin_unblock_user'),
    path('admin-dashboard/suspend-school/', views_admin.SuspendSchoolView.as_view(), name='admin_suspend_school'),
    path('admin-dashboard/unsuspend-school/', views_admin.UnsuspendSchoolView.as_view(), name='admin_unsuspend_school'),

    # Student management (school-level)
    path('admin-dashboard/schools/<int:school_id>/students/', views_admin.SchoolStudentManageView.as_view(), name='admin_school_students'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/edit/', views_admin.SchoolStudentEditView.as_view(), name='admin_school_student_edit'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/edit-modal/', views_admin.StudentEditModalView.as_view(), name='admin_school_student_edit_modal'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/remove/', views_admin.SchoolStudentRemoveView.as_view(), name='admin_school_student_remove'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/restore/', views_admin.SchoolStudentRestoreView.as_view(), name='admin_school_student_restore'),
    path('admin-dashboard/schools/<int:school_id>/students/batch-update/', views_admin.SchoolStudentBatchUpdateView.as_view(), name='admin_school_student_batch_update'),

    # Parent list & edit (school-level)
    path('admin-dashboard/schools/<int:school_id>/parents/', views_parent_admin.SchoolParentListView.as_view(), name='admin_school_parents'),
    path('admin-dashboard/schools/<int:school_id>/guardians/<int:guardian_id>/edit-modal/', views_parent_admin.GuardianEditModalView.as_view(), name='admin_guardian_edit_modal'),
    path('admin-dashboard/schools/<int:school_id>/guardians/<int:guardian_id>/edit/', views_parent_admin.GuardianUpdateView.as_view(), name='admin_guardian_update'),
    path('admin-dashboard/schools/<int:school_id>/parent-links/<int:link_id>/edit-modal/', views_parent_admin.ParentLinkEditModalView.as_view(), name='admin_parent_link_edit_modal'),
    path('admin-dashboard/schools/<int:school_id>/parent-links/<int:link_id>/edit/', views_parent_admin.ParentLinkUpdateView.as_view(), name='admin_parent_link_update'),

    # Parent invite management (school-level)
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/invite-parent/', views_parent_admin.ParentInviteCreateView.as_view(), name='invite_parent'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/parents/', views_parent_admin.StudentParentLinksView.as_view(), name='student_parent_links'),
    path('admin-dashboard/schools/<int:school_id>/students/<int:student_id>/parents/<int:link_id>/remove/', views_parent_admin.ParentStudentUnlinkView.as_view(), name='unlink_parent_student'),
    path('admin-dashboard/schools/<int:school_id>/parent-invites/', views_parent_admin.ParentInviteListView.as_view(), name='parent_invite_list'),
    path('admin-dashboard/schools/<int:school_id>/parent-invites/<int:invite_id>/revoke/', views_parent_admin.ParentInviteRevokeView.as_view(), name='revoke_parent_invite'),

    # Department management (within a school)
    path('admin-dashboard/schools/<int:school_id>/departments/', views_department.DepartmentListView.as_view(), name='admin_school_departments'),
    path('admin-dashboard/schools/<int:school_id>/departments/create/', views_department.DepartmentCreateView.as_view(), name='admin_department_create'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/', views_department.DepartmentDetailView.as_view(), name='admin_department_detail'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/edit/', views_department.DepartmentEditView.as_view(), name='admin_department_edit'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/assign-hod/', views_department.DepartmentAssignHoDView.as_view(), name='admin_department_assign_hod'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/teachers/', views_department.DepartmentManageTeachersView.as_view(), name='admin_department_teachers'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/assign-classes/', views_department.DepartmentAssignClassesView.as_view(), name='admin_department_assign_classes'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/levels/', views_department.DepartmentManageLevelsView.as_view(), name='admin_department_levels'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/subject-levels/', views_department.DepartmentSubjectLevelsView.as_view(), name='admin_department_subject_levels'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/subject-levels/<int:level_id>/remove/', views_department.DepartmentSubjectLevelRemoveView.as_view(), name='admin_department_subject_level_remove'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/settings/', views_department.DepartmentSettingsView.as_view(), name='admin_department_settings'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/update-fee/', views_department.DepartmentUpdateFeeView.as_view(), name='admin_department_update_fee'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/toggle-active/', views_department.DepartmentToggleActiveView.as_view(), name='admin_department_toggle_active'),
    path('admin-dashboard/schools/<int:school_id>/departments/<int:dept_id>/delete/', views_department.DepartmentDeleteView.as_view(), name='admin_department_delete'),

    # Email management (admin)
    path('admin-dashboard/email/', views_email.EmailDashboardView.as_view(), name='email_dashboard'),
    path('admin-dashboard/email/compose/', views_email.EmailComposeView.as_view(), name='email_compose'),
    path('admin-dashboard/email/campaigns/', views_email.EmailCampaignListView.as_view(), name='email_campaign_list'),
    path('admin-dashboard/email/campaigns/<int:campaign_id>/', views_email.EmailCampaignDetailView.as_view(), name='email_campaign_detail'),

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
    path('teacher/parent-link-requests/', views_teacher.ParentLinkRequestsView.as_view(), name='parent_link_requests'),
    path('teacher/parent-link-requests/<int:request_id>/approve/', views_teacher.ParentLinkApproveView.as_view(), name='parent_link_approve'),
    path('teacher/parent-link-requests/<int:request_id>/reject/', views_teacher.ParentLinkRejectView.as_view(), name='parent_link_reject'),

    # Session management
    path('teacher/class/<int:class_id>/start-session/', views_teacher.StartSessionView.as_view(), name='start_session'),
    path('teacher/class/<int:class_id>/create-session/', views_teacher.CreateSessionView.as_view(), name='create_session'),
    path('teacher/session/<int:session_id>/complete/', views_teacher.CompleteSessionView.as_view(), name='complete_session'),
    path('teacher/session/<int:session_id>/cancel/', views_teacher.CancelSessionView.as_view(), name='cancel_session'),
    path('teacher/session/<int:session_id>/delete/', views_teacher.DeleteSessionView.as_view(), name='delete_session'),

    # Parent portal
    path('parent/', views_parent.ParentDashboardView.as_view(), name='parent_dashboard'),
    path('parent/children/', views_parent.ParentChildrenView.as_view(), name='my_children'),
    path('parent/switch-child/<int:student_id>/', views_parent.ParentSwitchChildView.as_view(), name='parent_switch_child'),
    path('parent/invoices/', views_parent.ParentInvoicesView.as_view(), name='parent_invoices'),
    path('parent/invoices/<int:invoice_id>/', views_parent.ParentInvoiceDetailView.as_view(), name='parent_invoice_detail'),
    path('parent/payments/', views_parent.ParentPaymentHistoryView.as_view(), name='parent_payment_history'),
    path('parent/billing/', views_parent.ParentPaymentHistoryView.as_view(), name='parent_billing'),
    path('parent/attendance/', views_parent.ParentAttendanceView.as_view(), name='parent_attendance'),
    path('parent/progress/', views_parent.ParentProgressView.as_view(), name='parent_progress'),
    path('parent/add-child/', views_parent.ParentAddChildView.as_view(), name='parent_add_child'),
    path('parent/classes/', views_parent.ParentClassesView.as_view(), name='parent_classes'),
    path('parent/become-parent/', views_parent.BecomeParentView.as_view(), name='become_parent'),

    # Student enrollment & classes
    path('student/join/', views_student.JoinClassByCodeView.as_view(), name='student_join_class'),
    path('student/my-classes/', views_student.MyClassesView.as_view(), name='student_my_classes'),
    path('student/class/<int:class_id>/', views_student.StudentClassDetailView.as_view(), name='student_class_detail'),
    path('student/attendance/', views_student.StudentAttendanceHistoryView.as_view(), name='student_attendance_history'),
    path('student/session/<int:session_id>/mark-attendance/', views_student.StudentSelfMarkAttendanceView.as_view(), name='student_mark_attendance'),
    path('student/enroll-global/<int:class_id>/', views_student.EnrollGlobalClassView.as_view(), name='student_enroll_global_class'),

    # Absence token (makeup class) routes
    path('student/absence-tokens/', attendance_views_student.MyAbsenceTokensView.as_view(), name='student_absence_tokens'),
    path('student/absence-tokens/request/', attendance_views_student.RequestAbsenceTokenView.as_view(), name='student_request_absence_token'),
    path('student/absence-tokens/<int:token_id>/available-sessions/', attendance_views_student.AvailableMakeupSessionsView.as_view(), name='student_available_makeup_sessions'),
    path('student/absence-tokens/<int:token_id>/redeem/', attendance_views_student.RedeemAbsenceTokenView.as_view(), name='student_redeem_absence_token'),

    # Progress criteria & tracking
    path('progress/criteria/', views_progress.ProgressCriteriaListView.as_view(), name='progress_criteria_list'),
    path('progress/criteria/create/', views_progress.ProgressCriteriaCreateView.as_view(), name='progress_criteria_create'),
    path('progress/criteria/<int:criteria_id>/submit/', views_progress.ProgressCriteriaSubmitView.as_view(), name='progress_criteria_submit'),
    path('progress/criteria/approvals/', views_progress.ProgressCriteriaApprovalListView.as_view(), name='progress_criteria_approvals'),
    path('progress/criteria/<int:criteria_id>/approve/', views_progress.ProgressCriteriaApproveView.as_view(), name='progress_criteria_approve'),
    path('progress/criteria/<int:criteria_id>/reject/', views_progress.ProgressCriteriaRejectView.as_view(), name='progress_criteria_reject'),
    path('progress/class/<int:class_id>/record/', views_progress.RecordProgressView.as_view(), name='record_progress'),
    path('progress/student/<int:student_id>/', views_progress.StudentProgressView.as_view(), name='student_progress'),
    path('progress/report/', views_progress.StudentProgressReportView.as_view(), name='student_progress_report'),

    # Per-student fee override
    path('class/<int:class_id>/student/<int:student_id>/fee/', views.UpdateStudentFeeView.as_view(), name='update_student_fee'),
    path('class/<int:class_id>/student/<int:student_id>/remove/', views.ClassStudentRemoveView.as_view(), name='class_student_remove'),

    # API
    path('api/department/<int:dept_id>/levels/', views.DepartmentLevelsAPIView.as_view(), name='api_department_levels'),

    # School hierarchy
    path('school-hierarchy/', views_hierarchy.SchoolHierarchyView.as_view(), name='school_hierarchy_auto'),
    path('school-hierarchy/<int:school_id>/', views_hierarchy.SchoolHierarchyView.as_view(), name='school_hierarchy'),

    # HoD / Dashboard
    path('dashboard/', views.HoDOverviewView.as_view(), name='hod_overview'),
    path('department/manage-classes/', views.HoDManageClassesView.as_view(), name='hod_manage_classes'),
    path('department/class/<int:class_id>/delete/', views.HoDDeleteClassView.as_view(), name='hod_delete_class'),
    path('department/class/<int:class_id>/restore/', views.HoDRestoreClassView.as_view(), name='hod_restore_class'),
    path('department/create-class/', views.HoDCreateClassView.as_view(), name='hod_create_class'),
    path('department/assign-class/', views.HoDAssignClassView.as_view(), name='hod_assign_class'),
    path('department/workload/', views.HoDWorkloadView.as_view(), name='hod_workload'),
    path('department/reports/', views.HoDReportsView.as_view(), name='hod_reports'),
    path('department/attendance/', views.HoDAttendanceReportView.as_view(), name='hod_attendance_report'),
    path('department/attendance/detail/', views.AttendanceDetailView.as_view(), name='attendance_detail'),
    path('department/subject-levels/', views.HoDSubjectLevelsView.as_view(), name='hod_subject_levels'),
    path('department/subject-levels/<int:dept_id>/', views.HoDSubjectLevelsView.as_view(), name='hod_subject_levels_dept'),
    path('department/subject-levels/<int:dept_id>/<int:level_id>/remove/', views.HoDSubjectLevelRemoveView.as_view(), name='hod_subject_level_remove'),

    # Accounting
    path('accounting/', views.AccountingDashboardView.as_view(), name='accounting_dashboard'),
    path('accounting/packages/', views.AccountingPackagesView.as_view(), name='accounting_packages'),
    path('accounting/users/', views.AccountingUsersView.as_view(), name='accounting_users'),
    path('accounting/export/', views.AccountingExportView.as_view(), name='accounting_export'),
    path('accounting/refunds/', views.AccountingRefundsView.as_view(), name='accounting_refunds'),
    path('accounting/refund/<int:payment_id>/', views.ProcessRefundView.as_view(), name='process_refund'),

    # Invoicing
    path('invoicing/', views_invoicing.InvoiceListView.as_view(), name='invoice_list'),
    path('invoicing/fees/', views_invoicing.FeeConfigurationView.as_view(), name='fee_configuration'),
    path('invoicing/fees/class/<int:classroom_id>/set/', views_invoicing.SetClassroomFeeView.as_view(), name='set_classroom_fee'),
    path('invoicing/fees/batch-update/', views_invoicing.BatchClassroomFeeView.as_view(), name='batch_classroom_fee'),
    path('invoicing/fees/student-override/add/', views_invoicing.AddStudentFeeOverrideView.as_view(), name='add_student_fee_override'),
    path('invoicing/generate/', views_invoicing.GenerateInvoicesView.as_view(), name='generate_invoices'),
    path('invoicing/preview/', views_invoicing.InvoicePreviewView.as_view(), name='invoice_preview'),
    path('invoicing/issue/', views_invoicing.IssueInvoicesView.as_view(), name='issue_invoices'),
    path('invoicing/drafts/delete/', views_invoicing.DeleteDraftInvoicesView.as_view(), name='delete_draft_invoices'),
    path('invoicing/<int:invoice_id>/', views_invoicing.InvoiceDetailView.as_view(), name='invoice_detail'),
    path('invoicing/<int:invoice_id>/edit/', views_invoicing.InvoiceEditView.as_view(), name='invoice_edit'),
    path('invoicing/<int:invoice_id>/cancel/', views_invoicing.CancelInvoiceView.as_view(), name='cancel_invoice'),
    path('invoicing/<int:invoice_id>/pay/', views_invoicing.RecordManualPaymentView.as_view(), name='record_manual_payment'),
    path('invoicing/csv/upload/', views_invoicing.CSVUploadView.as_view(), name='csv_upload'),
    path('invoicing/csv/mapping/', views_invoicing.CSVColumnMappingView.as_view(), name='csv_column_mapping'),
    path('invoicing/csv/<int:import_id>/review/', views_invoicing.CSVReviewMatchesView.as_view(), name='csv_review_matches'),
    path('invoicing/csv/<int:import_id>/confirm/', views_invoicing.ConfirmCSVPaymentsView.as_view(), name='confirm_csv_payments'),
    path('invoicing/reference-mappings/', views_invoicing.ReferenceMappingsView.as_view(), name='reference_mappings'),
    path('invoicing/opening-balances/', views_invoicing.OpeningBalancesView.as_view(), name='opening_balances'),
    path('invoicing/opening-balances/<int:student_id>/set/', views_invoicing.SetOpeningBalanceView.as_view(), name='set_opening_balance'),
    path('invoicing/opening-balances/batch-update/', views_invoicing.BatchOpeningBalanceView.as_view(), name='batch_opening_balance'),
    path('invoicing/api/student-search/', views_invoicing.StudentSearchAPIView.as_view(), name='student_search_api'),

    # Salaries
    path('salaries/', views_salaries.SalarySlipListView.as_view(), name='salary_slip_list'),
    path('salaries/rates/', views_salaries.SalaryRateConfigurationView.as_view(), name='salary_rate_configuration'),
    path('salaries/rates/set-default/', views_salaries.SetSchoolDefaultRateView.as_view(), name='set_school_default_rate'),
    path('salaries/rates/teacher-override/add/', views_salaries.AddTeacherRateOverrideView.as_view(), name='add_teacher_rate_override'),
    path('salaries/rates/batch-update/', views_salaries.BatchTeacherRateView.as_view(), name='batch_teacher_rate'),
    path('salaries/generate/', views_salaries.GenerateSalarySlipsView.as_view(), name='generate_salary_slips'),
    path('salaries/preview/', views_salaries.SalarySlipPreviewView.as_view(), name='salary_slip_preview'),
    path('salaries/issue/', views_salaries.IssueSalarySlipsView.as_view(), name='issue_salary_slips'),
    path('salaries/drafts/delete/', views_salaries.DeleteDraftSalarySlipsView.as_view(), name='delete_draft_salary_slips'),
    path('salaries/<int:slip_id>/', views_salaries.SalarySlipDetailView.as_view(), name='salary_slip_detail'),
    path('salaries/<int:slip_id>/cancel/', views_salaries.CancelSalarySlipView.as_view(), name='cancel_salary_slip'),
    path('salaries/<int:slip_id>/pay/', views_salaries.RecordSalaryPaymentView.as_view(), name='record_salary_payment'),
    path('salaries/api/teacher-search/', views_salaries.TeacherSearchAPIView.as_view(), name='teacher_search_api'),
]
