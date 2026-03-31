"""
attendance/urls.py
===================
All attendance and session URL patterns extracted from classroom/urls.py (CPP-64).
Included into main urls.py via:
    path('', include('attendance.urls')),
URL names are unchanged — no template or redirect updates needed.
"""

from django.urls import path
from . import views, views_student, views_teacher

urlpatterns = [
    path('class/<int:class_id>/attendance/', views.ClassAttendanceView.as_view(), name='class_attendance'),
    path('teacher/class/<int:class_id>/start-session/', views_teacher.StartSessionView.as_view(), name='start_session'),
    path('teacher/class/<int:class_id>/create-session/', views_teacher.CreateSessionView.as_view(), name='create_session'),
    path('teacher/session/<int:session_id>/complete/', views_teacher.CompleteSessionView.as_view(), name='complete_session'),
    path('teacher/session/<int:session_id>/cancel/', views_teacher.CancelSessionView.as_view(), name='cancel_session'),
    path('teacher/session/<int:session_id>/delete/', views_teacher.DeleteSessionView.as_view(), name='delete_session'),
    path('teacher/session/<int:session_id>/attendance/', views_teacher.SessionAttendanceView.as_view(), name='session_attendance'),
    path('teacher/session/<int:session_id>/self-attendance/', views_teacher.TeacherSelfAttendanceView.as_view(), name='teacher_self_attendance'),
    path('teacher/attendance-approvals/', views_teacher.StudentAttendanceApprovalListView.as_view(), name='attendance_approvals'),
    path('teacher/attendance/<int:attendance_id>/approve/', views_teacher.StudentAttendanceApproveView.as_view(), name='attendance_approve'),
    path('teacher/attendance/<int:attendance_id>/reject/', views_teacher.StudentAttendanceRejectView.as_view(), name='attendance_reject'),
    path('teacher/attendance/bulk-approve/', views_teacher.StudentAttendanceBulkApproveView.as_view(), name='attendance_bulk_approve'),
    path('student/attendance/', views_student.StudentAttendanceHistoryView.as_view(), name='student_attendance_history'),
    path('student/session/<int:session_id>/mark-attendance/', views_student.StudentSelfMarkAttendanceView.as_view(), name='student_mark_attendance'),
    # Absence token (makeup class) routes
    path('student/absence-tokens/', views_student.MyAbsenceTokensView.as_view(), name='student_absence_tokens'),
    path('student/absence-tokens/request/', views_student.RequestAbsenceTokenView.as_view(), name='student_request_absence_token'),
    path('student/absence-tokens/<int:token_id>/available-sessions/', views_student.AvailableMakeupSessionsView.as_view(), name='student_available_makeup_sessions'),
    path('student/absence-tokens/<int:token_id>/redeem/', views_student.RedeemAbsenceTokenView.as_view(), name='student_redeem_absence_token'),
]
