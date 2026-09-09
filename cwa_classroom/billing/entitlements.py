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


def _effective_class_limit(sub):
    """Get the effective class limit, considering discount code overrides."""
    if sub.discount_code and sub.discount_code.override_class_limit is not None:
        return sub.discount_code.override_class_limit
    return sub.plan.class_limit


def _effective_student_limit(sub):
    """Get the effective student limit, considering discount code overrides."""
    if sub.discount_code and sub.discount_code.override_student_limit is not None:
        return sub.discount_code.override_student_limit
    return sub.plan.student_limit


def check_class_limit(school):
    """
    Check if a school can create another class.
    Returns (allowed: bool, current: int, limit: int).
    Legacy schools (no subscription) are always allowed.
    Discount code overrides take precedence over plan limits (0 = unlimited).
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return (True, 0, 0)
    limit = _effective_class_limit(sub)
    if limit == 0:
        # Unlimited
        current = ClassRoom.objects.filter(school=school, is_active=True).count()
        return (True, current, 0)
    current = ClassRoom.objects.filter(school=school, is_active=True).count()
    return (current < limit, current, limit)


def check_student_limit(school):
    """
    Check if a school can add another student.
    Returns (allowed: bool, current: int, limit: int).
    Legacy schools (no subscription) are always allowed.
    Discount code overrides take precedence over plan limits (0 = unlimited).
    """
    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return (True, 0, 0)
    limit = _effective_student_limit(sub)
    if limit == 0:
        current = SchoolStudent.objects.filter(school=school, is_active=True).count()
        return (True, current, 0)
    current = SchoolStudent.objects.filter(school=school, is_active=True).count()
    return (current < limit, current, limit)


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


def _parent_linked_modules(user):
    """Modules held by the schools of this user's linked children.

    A parent belongs to no school of their own: ``get_all_schools_for_user``
    reads admin, teacher and student roles, and a parent is none of them. So
    without this a parent resolves to *no* modules at all, and every gate that
    asks the request rather than the student denies them — the parent-facing
    half of invoicing, and every parent opening the report their child's
    school has paid for.

    That has been invisible so far only because ``MODULE_ENFORCEMENT`` ships
    in shadow: the middleware records the denial and lets the request through.
    Flipping to enforce without this would lock parents out of features their
    school is being billed for, which is the worst possible first impression
    of the module system.

    View-level gates already got this right one at a time
    (:func:`student_school_has_module`). This is the same rule, resolved once
    per request, so the middleware's answer agrees with theirs.

    Only ever *adds* entitlements. A parent can hold nothing a school has not
    already bought, so this cannot open a gate for anyone else.
    """
    from classroom.models import ParentStudent
    from billing.models import ModuleSubscription

    school_ids = ParentStudent.objects.filter(
        parent=user, is_active=True, school__isnull=False,
    ).values_list('school_id', flat=True)

    if not school_ids:
        return frozenset()

    return frozenset(
        ModuleSubscription.objects.filter(
            is_active=True,
            school_subscription__school_id__in=school_ids,
        ).values_list('module', flat=True)
    )


def student_school_has_module(student, module_slug):
    """Whether the SCHOOL that *student* belongs to has *module_slug* active.

    Three near-neighbours, and picking the wrong one is a silent bug rather
    than an error, so the names spell out whose modules each one reads:

    * :func:`has_module_any_school` — the *viewer's* schools.
    * :func:`student_has_module`    — the student's OWN per-student modules
      (``billing.StudentModule``), which is a different table entirely.
    * this one                      — the *student's* schools.

    Reports need this one. They are read by parents, who belong to no school
    of their own, so asking about the viewer would deny a parent the report
    their child's school has paid for; and they are a school-bought module, so
    asking about the student's own StudentModule rows would deny everybody,
    since nearly nobody has any.
    """
    if student is None:
        return False

    schools = get_all_schools_for_user(student)
    if not schools.exists():
        # Individual learner: no institute owns their data, so the institute
        # module economy does not apply to them. Their access is governed by
        # their own Subscription and the trial wall, which is the same call
        # any_school_has_active_subscription() makes for the same reason.
        return True

    return any(has_module(school, module_slug) for school in schools)


def school_ids_with_module(module_slug):
    """School ids with *module_slug* active, as a queryset for filtering rows.

    Needed where the gate cannot hang off the request: the report API returns
    rows for other people's children, and the schedule cron runs with no
    request at all. Matches :func:`has_module` in treating a school with no
    subscription as not having the module.
    """
    from billing.models import ModuleSubscription
    return ModuleSubscription.objects.filter(
        module=module_slug,
        is_active=True,
    ).values_list('school_subscription__school_id', flat=True)


def entitled_modules(request):
    """Every module slug this request is entitled to, resolved once.

    One query for the school modules instead of the per-school, per-module
    walk :func:`has_module_any_school` does — a sidebar asking about six
    modules used to pay that six times over, and the middleware asks on every
    request.

    The result is the union of two things a user can hold modules through:
    the schools they belong to (``ModuleSubscription``) and, where the slug is
    one of theirs, their own subscription (``StudentModule``). One set, so a
    caller never has to know which of the two a given slug came from.

    Cached on the request. A request that grants a module to itself mid-flight
    (the checkout success page) must re-read rather than trust this — call
    :func:`clear_entitlement_cache` after such a write.
    """
    cached = getattr(request, '_entitled_modules', None)
    if cached is not None:
        return cached

    user = getattr(request, 'user', None)
    if user is None or not getattr(user, 'is_authenticated', False):
        result = frozenset()
        request._entitled_modules = result
        return result

    from billing.models import ModuleSubscription

    slugs = set(
        ModuleSubscription.objects.filter(
            is_active=True,
            school_subscription__school__in=get_all_schools_for_user(user),
        ).values_list('module', flat=True)
    )
    slugs.update(active_student_modules(user))
    slugs.update(_parent_linked_modules(user))

    result = frozenset(slugs)
    request._entitled_modules = result
    return result


def clear_entitlement_cache(request):
    """Drop the cached set so the next read re-queries.

    Needed by the few views that change entitlement and then keep rendering —
    the module toggle and the checkout return — because otherwise the page
    that just sold a module renders as though it had not.
    """
    if hasattr(request, '_entitled_modules'):
        del request._entitled_modules


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

    return School.objects.filter(id__in=school_ids, is_active=True).select_related('subscription')


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


def check_ai_import_quota(school):
    """
    Check AI import page quota for a school.
    Returns (remaining, limit, used).
    Returns (0, 0, 0) if the school has no AI import module active.
    """
    from django.utils import timezone as tz

    sub = get_school_subscription(school)
    if not sub:
        return (0, 0, 0)

    ai_module = sub.modules.filter(
        module__startswith='ai_import_', is_active=True,
    ).select_related().first()
    if not ai_module:
        return (0, 0, 0)

    from billing.models import ModuleProduct
    try:
        product = ModuleProduct.objects.get(module=ai_module.module)
    except ModuleProduct.DoesNotExist:
        return (0, 0, 0)

    if product.pages_per_month is None or product.pages_per_month == 0:
        return (999999, 0, 0)

    limit = product.pages_per_month

    from ai_import.models import AIImportUsage
    today = tz.localdate()
    period_start = today.replace(day=1)
    usage, _ = AIImportUsage.objects.get_or_create(
        school=school, period_start=period_start,
        defaults={'pages_processed': 0, 'tokens_used': 0},
    )

    used = usage.pages_processed
    remaining = max(0, limit - used)
    return (remaining, limit, used)


def record_invoice_usage(school, count):
    """
    Increment the invoice usage counter for a school's subscription.
    Called after generating invoices.
    Auto-resets the counter if a year has elapsed since invoice_year_start.
    """
    from django.utils import timezone as tz

    sub = get_school_subscription(school)
    if not sub or not sub.plan:
        return

    today = tz.localdate()

    # Auto-reset if a year has elapsed
    if sub.invoice_year_start and (today - sub.invoice_year_start).days >= 365:
        sub.invoices_used_this_year = 0
        sub.invoice_year_start = today

    # Initialize invoice_year_start if never set
    if not sub.invoice_year_start:
        sub.invoice_year_start = today

    sub.invoices_used_this_year += count
    sub.save(update_fields=['invoices_used_this_year', 'invoice_year_start', 'updated_at'])


# ---------------------------------------------------------------------------
# Per-student modules (billing.StudentModule)
# ---------------------------------------------------------------------------
#
# The individual mirror of the school module system above. A school buys modules
# against its SchoolSubscription; a student carries them on their own
# billing.Subscription.
#
# The one rule that makes this safe to deploy: **a student with no module rows
# is not on any tier**. Every student on the site today has none, and a student
# who subscribes tomorrow gets none, so nothing about their access changes.
# Modules are attached deliberately, one student at a time — there is no
# student-facing way to pick one up.


def get_student_subscription(user):
    """Return the individual ``billing.Subscription`` for *user*, or None."""
    from billing.models import Subscription
    if not getattr(user, 'is_authenticated', False):
        return None
    return Subscription.objects.filter(user=user).first()


def active_student_modules(user):
    """The set of module slugs currently switched on for *user*.

    Empty for everybody who has never been given one — which is the whole
    site until somebody is put on a promotion.
    """
    from billing.models import StudentModule
    if not getattr(user, 'is_authenticated', False):
        return set()
    return set(
        StudentModule.objects
        .filter(subscription__user=user, is_active=True)
        .values_list('module', flat=True)
    )


def student_has_module(user, module_slug):
    """Is *module_slug* switched on for this student?"""
    return module_slug in active_student_modules(user)


def student_module_ai_verdict(user):
    """What the student's OWN modules say about AI grading.

    ``True``  — they hold the paid AI grading add-on.
    ``False`` — they are on Student Basic, the free promotional edition.
    ``None``  — they hold neither, so their modules have no opinion and the
                school rules decide (which, for a student in no school, means
                the app in full, exactly as before this existed).

    The add-on beats Basic on purpose: it is the thing a Basic student upgrades
    to, so holding both has to read as "upgraded".
    """
    from billing.models import StudentModule
    modules = active_student_modules(user)
    if StudentModule.MODULE_AI_GRADING in modules:
        return True
    if StudentModule.MODULE_BASIC in modules:
        return False
    return None


def grant_student_module(user, module_slug, granted_by=None, source_code='',
                         note=''):
    """Switch *module_slug* on for *user*, and say whether anything changed.

    Returns ``(module_row, changed)``. Re-granting a module the student already
    has switched on is a no-op rather than an error, so the management command
    and the admin can both be run twice.

    A student with no ``billing.Subscription`` cannot carry a module — there is
    nothing to hang it on — and gets ``(None, False)`` rather than a crash, so
    the caller can report the skip.
    """
    from billing.models import StudentModule

    subscription = get_student_subscription(user)
    if subscription is None:
        return (None, False)

    row, created = StudentModule.objects.get_or_create(
        subscription=subscription, module=module_slug,
        defaults={
            'granted_by': granted_by, 'source_code': source_code, 'note': note,
        },
    )
    if created:
        return (row, True)
    if not row.is_active:
        row.is_active = True
        row.deactivated_at = None
        row.granted_by = granted_by or row.granted_by
        row.source_code = source_code or row.source_code
        row.note = note or row.note
        row.save(update_fields=['is_active', 'deactivated_at', 'granted_by',
                                'source_code', 'note'])
        return (row, True)
    return (row, False)


def revoke_student_module(user, module_slug):
    """Switch *module_slug* off for *user*. Returns ``(row, changed)``.

    The row is kept and deactivated rather than deleted, so who had what, and
    when, survives the promotion ending.
    """
    from django.utils import timezone as tz
    from billing.models import StudentModule

    row = StudentModule.objects.filter(
        subscription__user=user, module=module_slug,
    ).first()
    if row is None or not row.is_active:
        return (row, False)
    row.is_active = False
    row.deactivated_at = tz.now()
    row.save(update_fields=['is_active', 'deactivated_at'])
    return (row, True)


def apply_code_student_modules(user, code, granted_by=None):
    """Attach whatever modules a redeemed promotion/discount *code* grants.

    Only reads flags the OWNER set on the code when they created it — a student
    typing a code can never choose a tier, only receive the one attached to the
    code they were handed.

    A code with no flags set (every code that exists today) does nothing.

    A flagged code that is not 100% off is refused here as well as in the
    model's ``clean()``. The form-level guard cannot see a row written by a
    script, a fixture or an old migration, and this is the last point before a
    paying student would be silently put on a reduced product.
    """
    import logging

    from billing.models import StudentModule

    if code is None or not getattr(code, 'grants_student_basic', False):
        return None
    if not getattr(code, 'is_fully_free', False):
        logging.getLogger(__name__).error(
            'Code %s is flagged grants_student_basic but is only %s%% off; '
            'refusing to put a paying student on the free tier.',
            getattr(code, 'code', code), getattr(code, 'discount_percent', '?'),
        )
        return None
    row, _changed = grant_student_module(
        user, StudentModule.MODULE_BASIC,
        granted_by=granted_by, source_code=getattr(code, 'code', ''),
        note='Granted by promotion code at redemption.',
    )
    return row


def codes_on_subscription(subscription):
    """Every promotion/discount code *subscription* was activated with.

    A subscription can carry a code two ways, because the two code types are
    recorded differently: ``discount_code`` is a real foreign key to a
    ``DiscountCode``, while a ``PromoCode`` leaves only its string in
    ``promo_code_used``. Both are looked up so neither kind of promotion is
    silently the one that doesn't work.
    """
    from billing.models import DiscountCode, PromoCode

    codes = []
    if subscription.discount_code_id:
        codes.append(subscription.discount_code)
    slug = (subscription.promo_code_used or '').strip()
    if slug:
        codes.append(PromoCode.objects.filter(code__iexact=slug).first()
                     or DiscountCode.objects.filter(code__iexact=slug).first())
    return [code for code in codes if code is not None]


def sync_student_modules(subscription, granted_by=None):
    """Bring a subscription's modules into line with the code that activated it.

    **Called when a subscription becomes real, not when a code is typed.** That
    distinction is the whole point of this function. A promotion code that
    covers the price in full activates the student on the spot; one that leaves
    a balance sends them to Stripe and the subscription is activated minutes
    later by the webhook — or, if that is lost, by the success page. Granting at
    the moment the code was entered would have worked only for the first kind,
    so a half-price promotion would have quietly handed out the AI-graded
    questions it was sold without.

    Idempotent by construction (``grant_student_module`` is), so every
    activation path can call it, the webhook and the success page can both fire,
    and the result is the same one row.

    Returns the module rows it granted, which is ``[]`` for every subscription
    whose code carries no tier — i.e. all of them today.
    """
    if subscription is None or subscription.user_id is None:
        return []
    granted = []
    for code in codes_on_subscription(subscription):
        row = apply_code_student_modules(
            subscription.user, code, granted_by=granted_by)
        if row is not None:
            granted.append(row)
    return granted
