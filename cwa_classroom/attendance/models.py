"""
attendance/models.py
====================
Re-exports attendance models from classroom.models.

The canonical model definitions live in classroom/models.py (which manages
migrations).  This module provides convenient imports so that attendance
views can do ``from .models import ClassSession, StudentAttendance, ...``.
"""

from classroom.models import (  # noqa: F401
    AbsenceToken,
    ClassSession,
    StudentAttendance,
    TeacherAttendance,
)
