# CPP-64 — Attendance app refactor

Extracts attendance from classroom/ into a dedicated attendance/ app.

## Apply order
1. Copy attendance/ into cwa_classroom/
2. Apply PATCH_*.py instructions
3. python manage.py migrate attendance
4. python manage.py makemigrations classroom --name remove_attendance_models
5. python manage.py migrate classroom --fake-initial
6. python manage.py test classroom.tests.test_attendance --verbosity=2
7. Update test imports: from attendance.models import ...
8. python manage.py test --verbosity=2

## Zero data loss
db_table preserved on all 3 models:
- ClassSession → classroom_classsession
- StudentAttendance → classroom_studentattendance
- TeacherAttendance → classroom_teacheratttendance
