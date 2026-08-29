"""Role gates and object-level scoping for the API.

Two questions, answered in two different places on purpose:

* **May this account use the app at all?** (trial expired, blocked, profile
  unfinished.) Answered elsewhere: the rules live in
  ``cwa_classroom.middleware`` and are never re-implemented.

  For a browser that is the middleware itself; for a bearer token it is
  ``api.authentication.WalledJWTAuthentication``, which runs those same
  middlewares at the point the token becomes a user. Nothing in this module
  repeats those rules.

* **Which rows may they see?** That is this module, plus
  ``progress.access.can_view_student`` — the same helper the web views use.
  A permission rule with two implementations is one that will eventually
  disagree with itself, and the copy that drifts is the one nobody reads.
"""

from rest_framework import permissions

from accounts.models import Role
from progress.access import can_view_student


class _HasAnyRole(permissions.IsAuthenticated):
    """Authenticated *and* holding at least one of ``roles``."""

    roles = ()

    def has_permission(self, request, view):
        if not super().has_permission(request, view):
            return False
        user = request.user
        if user.is_superuser:
            return True
        return user.roles.filter(name__in=self.roles, is_active=True).exists()


class IsStudent(_HasAnyRole):
    roles = (Role.STUDENT, Role.INDIVIDUAL_STUDENT)


class IsParent(_HasAnyRole):
    roles = (Role.PARENT,)


class IsTeacher(_HasAnyRole):
    roles = (Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER)


class IsSchoolStaff(_HasAnyRole):
    """Teachers plus the institute roles that manage them."""

    roles = (
        Role.SENIOR_TEACHER, Role.TEACHER, Role.JUNIOR_TEACHER,
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER, Role.ACCOUNTANT, Role.ADMIN,
    )


class IsInstituteAdmin(_HasAnyRole):
    """Institute-level staff — may act across a whole school."""

    roles = (
        Role.HEAD_OF_DEPARTMENT, Role.HEAD_OF_INSTITUTE,
        Role.INSTITUTE_OWNER, Role.ADMIN,
    )


class ReadOnly(permissions.BasePermission):
    """Combine with ``|`` to let a viewset be read more widely than written."""

    def has_permission(self, request, view):
        return request.method in permissions.SAFE_METHODS


class CanViewStudentData(permissions.IsAuthenticated):
    """Object-level gate for anything hanging off a student.

    The object must expose the student it belongs to — either by being the
    student, or via a ``student`` attribute. Delegates the actual decision to
    ``progress.access.can_view_student`` so the API and the web views cannot
    drift apart on who may read a child's record.
    """

    def has_object_permission(self, request, view, obj):
        student = getattr(obj, 'student', obj)
        return can_view_student(request.user, student)
