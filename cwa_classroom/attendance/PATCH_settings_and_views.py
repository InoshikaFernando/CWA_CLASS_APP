# CPP-64 patch: see README.md for full instructions
# settings.py: add "attendance" to INSTALLED_APPS
# cwa_classroom/urls.py: add path("", include("attendance.urls")),
# classroom/views_teacher.py: remove 11 views, update imports
# classroom/views.py: remove ClassAttendanceView, add re-export alias
