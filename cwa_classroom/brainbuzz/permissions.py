"""Role-based permissions and visibility control for question uploads.

Enforces strict isolation between global (super user) and local (institute/class)
questions based on user role and school/department/classroom assignments.
"""

from functools import wraps
from typing import Literal
from django.http import JsonResponse, HttpResponse
from django.shortcuts import redirect
from django.db.models import Q
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model

User = get_user_model()


def _get_user_school(user):
    """Return user's primary school.

    Checks ``user.school`` instance attribute first (set in direct-call tests).
    Falls back to the SchoolTeacher M2M relationship for users loaded from DB
    (e.g. ``request.user`` in HTTP views where no instance attr is present).
    """
    school = getattr(user, 'school', None)
    if school is not None:
        return school
    try:
        st = user.school_memberships.filter(is_active=True).first()
        return st.school if st else None
    except Exception:
        return None


_ADMIN_ROLES = frozenset([
    'admin', 'institute_owner', 'head_of_institute', 'head_of_department', 'senior_teacher',
])
_TEACHER_ROLES = frozenset(['teacher', 'junior_teacher'])


def _has_role_model_permission(user) -> bool:
    """Return True if user holds any Role that grants upload permission."""
    allowed = _ADMIN_ROLES | _TEACHER_ROLES
    return user.roles.filter(name__in=allowed, is_active=True).exists()


def get_user_role(user) -> Literal['superuser', 'admin', 'teacher', 'guest']:
    """Determine user role based on authentication and school assignment.

    Returns:
        'superuser': Django superuser (global question access)
        'admin': Staff/institute-level role with school assignment
        'teacher': Class-teacher role with school + classroom
        'guest': Not authenticated or no qualifying role
    """
    if not user.is_authenticated:
        return 'guest'

    if user.is_superuser:
        return 'superuser'

    # Accept either is_staff (legacy) OR an accounts.Role model match
    has_permission = user.is_staff or _has_role_model_permission(user)
    if not has_permission:
        return 'guest'

    school = _get_user_school(user)
    if not school:
        return 'guest'

    # Class-teacher roles → scoped to classroom
    is_class_teacher = (
        (hasattr(user, 'classroom') and user.classroom)
        or user.roles.filter(name__in=_TEACHER_ROLES, is_active=True).exists()
    )
    if is_class_teacher:
        return 'teacher'

    return 'admin'


def auto_scope_question(question_dict: dict, user, subject_type: str = 'maths') -> dict:
    """Automatically set school/department/classroom scope based on user role.

    For maths questions: Sets school, department, classroom FKs
    For coding exercises: Sets school, department, classroom FKs
    For other subjects: Sets school, department, classroom FKs

    Args:
        question_dict: Question data dict to be modified
        user: User object
        subject_type: 'maths', 'coding', etc.

    Returns:
        Modified question_dict with scope fields set
    """
    role = get_user_role(user)

    if role == 'superuser':
        # Super user: Global questions (null scope)
        question_dict['school'] = None
        question_dict['department'] = None
        question_dict['classroom'] = None

    elif role == 'admin':
        # Institute admin: Local to school, visible across institute
        question_dict['school'] = _get_user_school(user)
        question_dict['department'] = None
        question_dict['classroom'] = None

    elif role == 'teacher':
        # Class teacher: Local to school + classroom
        question_dict['school'] = _get_user_school(user)
        question_dict['department'] = None
        question_dict['classroom'] = getattr(user, 'classroom', None)

    else:
        # Guest/unknown: Reject
        raise PermissionError(f"User {user.username} does not have permission to upload questions")

    return question_dict


def can_upload_questions(user) -> bool:
    """Check if user is allowed to upload questions.

    Super users, institute admins, and class teachers can upload.
    Regular users and unauthenticated users cannot.

    Args:
        user: Django user object

    Returns:
        True if user can upload, False otherwise
    """
    role = get_user_role(user)
    return role in ('superuser', 'admin', 'teacher')


def can_see_question(question, user) -> bool:
    """Check if user can view/use a question based on visibility scope.

    Global questions (school=None) are visible to all users.
    Local questions are visible only within their scope:
      - school_id match required
      - if department_id set: department_id match required
      - if classroom_id set: classroom_id match required

    Args:
        question: Question or CodingExercise model instance
        user: Django user object

    Returns:
        True if user can see question, False otherwise
    """
    # Unauthenticated users see only global questions
    if not user.is_authenticated:
        return question.school is None

    # Global questions visible to all authenticated users
    if question.school is None:
        return True

    # User must have school assigned to see local questions
    user_school = _get_user_school(user)
    if not user_school:
        return False

    # Local question must be in same school
    if question.school != user_school:
        return False

    # If question is department-scoped, user must match
    if question.department:
        if not hasattr(user, 'department') or question.department != user.department:
            return False

    # If question is class-scoped, user must match
    if question.classroom:
        if not hasattr(user, 'classroom') or question.classroom != user.classroom:
            return False

    return True


def get_visible_questions_filter(user, subject: str = 'maths') -> Q:
    """Get a Django Q object filter for questions visible to user.

    Use this in querysets to filter questions: Question.objects.filter(get_visible_questions_filter(user))

    Args:
        user: Django user object
        subject: 'maths' or 'coding'

    Returns:
        Django Q object with visibility filters
    """
    # Global questions always visible to authenticated users
    global_filter = Q(school__isnull=True)

    # If not authenticated, only see global questions
    if not user.is_authenticated:
        return global_filter

    # If no school assigned, only see global questions
    user_school = _get_user_school(user)
    if not user_school:
        return global_filter

    # Local questions: must be in same school
    local_filter = Q(school=user_school)

    # If user has department, also filter by department scope
    if hasattr(user, 'department') and user.department:
        dept_filter = Q(department__isnull=True) | Q(department=user.department)
        local_filter &= dept_filter

    # If user has classroom, also filter by classroom scope
    if hasattr(user, 'classroom') and user.classroom:
        class_filter = Q(classroom__isnull=True) | Q(classroom=user.classroom)
        local_filter &= class_filter

    # Combine global and local filters
    return global_filter | local_filter


# ============================================================================
# Decorators for view protection
# ============================================================================

def require_upload_permission(view_func):
    """Decorator to require upload permission for a view.

    Returns 403 Forbidden if user cannot upload questions.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not can_upload_questions(request.user):
            return HttpResponse("Permission denied: You do not have permission to upload questions", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def require_superuser(view_func):
    """Decorator to require superuser status.

    Returns 403 Forbidden if user is not a superuser.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            return HttpResponse("Permission denied: Superuser required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def require_institute_admin(view_func):
    """Decorator to require institute admin or superuser status.

    Returns 403 Forbidden if user is not an admin.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        role = get_user_role(request.user)
        if role not in ('superuser', 'admin'):
            return HttpResponse("Permission denied: Institute admin required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


def require_staff(view_func):
    """Decorator to require staff status.

    Returns 403 Forbidden if user is not staff.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_staff:
            return HttpResponse("Permission denied: Staff required", status=403)
        return view_func(request, *args, **kwargs)

    return wrapper


# ============================================================================
# Helper functions for common permission checks
# ============================================================================

def user_school(user):
    """Get user's school, or None if not assigned."""
    return getattr(user, 'school', None)


def user_department(user):
    """Get user's department, or None if not assigned."""
    return getattr(user, 'department', None)


def user_classroom(user):
    """Get user's classroom, or None if not assigned."""
    return getattr(user, 'classroom', None)


def is_superuser(user) -> bool:
    """Check if user is superuser."""
    return user.is_authenticated and user.is_superuser


def is_institute_admin(user) -> bool:
    """Check if user is institute admin (staff with school, no classroom)."""
    role = get_user_role(user)
    return role == 'admin'


def is_teacher(user) -> bool:
    """Check if user is class teacher (staff with school + classroom)."""
    role = get_user_role(user)
    return role == 'teacher'


def is_staff(user) -> bool:
    """Check if user is staff."""
    return user.is_authenticated and user.is_staff
