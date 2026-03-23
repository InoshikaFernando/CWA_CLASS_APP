"""
attendance/models.py
====================
Moved from classroom/models.py as part of CPP-64 refactor.
ClassSession, StudentAttendance, and TeacherAttendance now live here.

db_table is explicitly set to preserve existing database tables —
no data migration is needed, only a schema state migration.
"""

from django.conf import settings
from django.db import models

# ClassRoom lives in classroom — import via string reference to avoid circular imports
# We use lazy FK strings ('classroom.ClassRoom') throughout.


class ClassSession(models.Model):
    """A single scheduled session (lesson) for a class."""

    STATUS_SCHEDULED = 'scheduled'
    STATUS_COMPLETED = 'completed'
    STATUS_CANCELLED = 'cancelled'

    STATUS_CHOICES = [
        (STATUS_SCHEDULED, 'Scheduled'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_CANCELLED, 'Cancelled'),
    ]

    classroom = models.ForeignKey(
        'classroom.ClassRoom',
        on_delete=models.CASCADE,
        related_name='sessions',
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_SCHEDULED,
    )
    cancellation_reason = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_sessions',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['date', 'start_time']
        # Preserve existing DB table — no data migration needed
        db_table = 'classroom_classsession'

    def __str__(self):
        return f'{self.classroom.name} — {self.date} {self.start_time}'


class StudentAttendance(models.Model):
    """Tracks student attendance for a specific class session."""

    STATUS_PRESENT = 'present'
    STATUS_ABSENT = 'absent'
    STATUS_LATE = 'late'

    STATUS_CHOICES = [
        (STATUS_PRESENT, 'Present'),
        (STATUS_ABSENT, 'Absent'),
        (STATUS_LATE, 'Late'),
    ]

    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        related_name='student_attendance',
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='attendance_records',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default=STATUS_PRESENT,
    )
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name='attendance_marks_given',
    )
    marked_at = models.DateTimeField(auto_now_add=True)
    self_reported = models.BooleanField(default=False)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_attendance_approvals',
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('session', 'student')
        ordering = ['session', 'student']
        db_table = 'classroom_studentattendance'

    def __str__(self):
        return f'{self.student.username} — {self.session} ({self.status})'


class TeacherAttendance(models.Model):
    """Tracks teacher self-attendance for a class session."""

    STATUS_CHOICES = [
        ('present', 'Present'),
        ('absent', 'Absent'),
        ('late', 'Late'),
    ]

    session = models.ForeignKey(
        ClassSession,
        on_delete=models.CASCADE,
        related_name='teacher_attendance',
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='teacher_attendance_records',
    )
    status = models.CharField(
        max_length=10,
        choices=STATUS_CHOICES,
        default='present',
    )
    self_reported = models.BooleanField(default=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teacher_attendance_approvals',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('session', 'teacher')
        db_table = 'classroom_teacherattendance'

    def __str__(self):
        return f'{self.teacher.username} — {self.session} ({self.status})'
