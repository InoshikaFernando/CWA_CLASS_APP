"""
Entitlement checking service layer for subscription enforcement.

Provides functions to check plan limits (classes, students, invoices)
and module access for schools.

Multi-school design:
  A student can be enrolled in multiple institutes via SchoolStudent.
  - Plan limits (classes, students, invoices) are always checked per-school
    because they are the school admin's responsibility.
  - Module access uses ANY-school logic: if a student is in School A (which
    has the attendance module) and School B (which doesn't), the student can
    access attendance features because at least one of their schools has it.
  - Trial/subscription expiry uses ANY-school logic: if any school the
    student belongs to has an active or trialing subscription, the student
    is not blocked.
  - Individual students ($19.90/mo) have their own Subscription object,
    independent of any school subscriptions. One payment covers access
    regardless of how many school classes they join.
"""
from decimal import Decimal

from classroom.models import ClassRoom, SchoolStudent, SchoolTeacher, School
from accounts.models import Role


def get_school_subscription(school):
    """Return the SchoolSubscription for a school, or None."""
    from billing.models import SchoolSubscription
    try:
        return school.subscription
    except SchoolSubscription.DoesNotExist:
        return None


def check_class_limit(school):
    """
    Check if a school can create another class.
    Returns (allowed: bool, current: int, limit: int).
    Legacy schools (no subscription) are always allowed.
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return (True, 0, 0)
    current = ClassRoom.objects.filter(school=school, is_active=True).count()
    return (current < sub.plan.class_limit, current, sub.plan.class_limit)


def check_student_limit(school):
    """
    Check if a school can add another student.
    Returns (allowed: bool, current: int, limit: int).
    Legacy schools (no subscription) are always allowed.
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return (True, 0, 0)
    current = SchoolStudent.objects.filter(school=school, is_active=True).count()
    return (current < sub.plan.student_limit, current, sub.plan.student_limit)


def check_invoice_limit(school):
    """
    Check invoice usage against yearly limit.
    Returns (within_limit: bool, current: int, limit: int, overage_rate: Decimal).
    Invoices are always allowed but overages are billed.
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return (True, 0, 0, Decimal('0'))
    within_limit = sub.invoices_used_this_year < sub.plan.invoice_limit_yearly
    return (
        within_limit,
        sub.invoices_used_this_year,
        sub.plan.invoice_limit_yearly,
        sub.plan.extra_invoice_rate,
    )


def has_module(school, module_slug):
    """Check if a school has an active module subscription."""
    sub = get_school_subscription(school)
    if not sub:
        return False
    return sub.modules.filter(module=module_slug, is_active=True).exists()


def has_module_any_school(user, module_slug):
    """
    Check if ANY school the user belongs to has a specific module enabled.
    Used for students who may be enrolled in multiple institutes —
    if any one school has the module, the student can access it.
    """
    for school in get_all_schools_for_user(user):
        if has_module(school, module_slug):
            return True
    return False


def get_school_for_user(user):
    """
    Resolve the primary school for a user.
    Priority: admin of school > teacher membership > student membership.
    Returns School or None.

    For multi-school students, returns the first active school.
    Use get_all_schools_for_user() when you need the full list.
    """
    if not user.is_authenticated:
        return None

    # Institute owner / Head of Institute — they're the school admin
    if user.has_role(Role.HEAD_OF_INSTITUTE) or user.has_role(Role.INSTITUTE_OWNER):
        school = School.objects.filter(admin=user, is_active=True).first()
        if school:
            return school

    # Teacher/HoD/Accountant — linked via SchoolTeacher
    membership = SchoolTeacher.objects.filter(
        teacher=user, is_active=True,
    ).select_related('school').first()
    if membership:
        return membership.school

    # School student — linked via SchoolStudent
    student_link = SchoolStudent.objects.filter(
        student=user, is_active=True,
    ).select_related('school').first()
    if student_link:
        return student_link.school

    return None


def get_all_schools_for_user(user):
    """
    Return ALL schools the user belongs to (as admin, teacher, or student).
    Used for multi-school entitlement checks where ANY-school logic applies.
    """
    if not user.is_authenticated:
        return School.objects.none()

    school_ids = set()

    # Schools where user is admin
    school_ids.update(
        School.objects.filter(admin=user, is_active=True)
        .values_list('id', flat=True)
    )

    # Schools where user is teacher
    school_ids.update(
        SchoolTeacher.objects.filter(teacher=user, is_active=True)
        .values_list('school_id', flat=True)
    )

    # Schools where user is student
    school_ids.update(
        SchoolStudent.objects.filter(student=user, is_active=True)
        .values_list('school_id', flat=True)
    )

    return School.objects.filter(id__in=school_ids, is_active=True)


def any_school_has_active_subscription(user):
    """
    Check if ANY school the user belongs to has an active/trialing subscription.
    Used by middleware to decide whether to block a multi-school user.
    Returns True if at least one school has an active or trialing subscription,
    or if the user has no school associations (legacy/individual).
    """
    schools = get_all_schools_for_user(user)
    if not schools.exists():
        return True  # No school = not an institute user, don't block

    for school in schools:
        sub = get_school_subscription(school)
        if sub is None:
            return True  # Legacy school with no subscription = allow
        if sub.is_active_or_trialing:
            return True
    return False


def record_invoice_usage(school, count):
    """
    Increment the invoice usage counter for a school's subscription.
    Called after generating invoices.
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return
    sub.invoices_used_this_year += count
    sub.save(update_fields=['invoices_used_this_year', 'updated_at'])
