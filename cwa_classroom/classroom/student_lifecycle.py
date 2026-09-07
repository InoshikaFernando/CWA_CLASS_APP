"""Student lifecycle transitions tied to school membership.

The one operation here is what happens to a student's *account* when they are
removed from a school. Subscriptions in CWA are per-user (``billing.Subscription``
is a OneToOne on the user, with no school FK) — a school never "owns" a
subscription. So:

* A student who belongs to **other** active schools is left completely
  untouched: their single per-user subscription is naturally shared and stays
  exactly as it is.
* A student removed from their **last** school is converted to an *individual
  student* — role swap ``STUDENT -> INDIVIDUAL_STUDENT`` (the mirror of the
  enrolment-approval swap in ``views_teacher``) — and any **partial**
  school-granted discount is ended so they pay CWA the full monthly price.
  A **100% (fully-free) discount is preserved** so CWA-school free students
  stay free.

Nothing here is school-driven billing: the discount snapshot already lives on
the per-user subscription; we only clear a *partial* one, mirroring the manual
``StudentDiscountClearView`` flow (Stripe-first cancel, then local clear, then
re-gate so the next login collects full payment).
"""
from __future__ import annotations

import logging

from django.db import transaction

logger = logging.getLogger(__name__)


def _subscription_or_none(user):
    from billing.models import Subscription
    try:
        return user.subscription
    except Subscription.DoesNotExist:
        return None


def _cancel_stripe_subscription(sub) -> bool:
    """Cancel a live Stripe subscription. Returns True if it is safe to proceed
    with the local clear (cancelled, or already gone), False on a real error so
    the caller can leave the discount in place rather than create a half-state
    where we bill nothing locally but Stripe keeps charging."""
    if not sub.stripe_subscription_id:
        return True
    import stripe
    from django.conf import settings
    stripe.api_key = settings.STRIPE_SECRET_KEY
    try:
        stripe.Subscription.delete(sub.stripe_subscription_id)
        return True
    except stripe.error.InvalidRequestError:
        logger.warning('Stripe sub %s already gone for user %s — clearing locally.',
                       sub.stripe_subscription_id, sub.user_id)
        return True
    except Exception as e:  # noqa: BLE001 — best-effort; leave discount intact on failure
        logger.error('Failed to cancel Stripe sub %s for user %s: %s',
                     sub.stripe_subscription_id, sub.user_id, e)
        return False


def convert_to_individual_if_last_school(student, *, actor=None):
    """Convert ``student`` to an individual student iff they have no active
    ``SchoolStudent`` links left.

    Returns a summary dict (safe for audit logging / tests)::

        {'converted': bool, 'reason': str, 'discount': 'kept_free_100'|'cleared'|'none'}

    Never raises for the expected paths — a Stripe failure downgrades the
    discount handling to a no-op (logged) rather than breaking the removal.
    """
    from accounts.models import Role, UserRole
    from billing.models import Subscription
    from .models import SchoolStudent

    # Still a member of another school → per-user subscription/role stay as-is.
    if SchoolStudent.objects.filter(student=student, is_active=True).exists():
        return {'converted': False, 'reason': 'still_in_school', 'discount': 'none'}

    student_role = Role.objects.filter(name=Role.STUDENT).first()
    had_student_role = bool(
        student_role and UserRole.objects.filter(user=student, role=student_role).exists()
    )
    if not had_student_role:
        # Not a school student (e.g. already individual) — nothing to convert.
        return {'converted': False, 'reason': 'not_a_school_student', 'discount': 'none'}

    # Converting to individual requires the role to exist — create it if the
    # environment has not been seeded, so we never strip STUDENT and leave the
    # account role-less.
    indv_role, _ = Role.objects.get_or_create(
        name=Role.INDIVIDUAL_STUDENT,
        defaults={'display_name': 'Individual Student'},
    )

    discount_outcome = 'none'
    sub = _subscription_or_none(student)
    state = sub.discount_state if sub else Subscription.DISCOUNT_NONE

    with transaction.atomic():
        # Role swap: STUDENT -> INDIVIDUAL_STUDENT (mirror of the enrolment-
        # approval swap in views_teacher).
        UserRole.objects.filter(user=student, role=student_role).delete()
        if indv_role:
            UserRole.objects.get_or_create(user=student, role=indv_role)

    # A 100% (fully-free) discount is preserved — CWA free students stay free.
    # A partial school discount ends so they pay full monthly to CWA.
    if state == Subscription.DISCOUNT_PARTIAL:
        if _cancel_stripe_subscription(sub):
            with transaction.atomic():
                sub.clear_discount(by_user=actor)
                student.profile_completed = False
                student.save(update_fields=['profile_completed'])
            discount_outcome = 'cleared'
        else:
            # Stripe cancel failed — leave the discount in place (safe). A human
            # can clear it later via the normal control.
            discount_outcome = 'clear_failed'
    elif state == Subscription.DISCOUNT_FREE_100:
        discount_outcome = 'kept_free_100'

    return {'converted': True, 'reason': 'last_school', 'discount': discount_outcome}


def restore_school_student_role(student):
    """Inverse role fix for restoring a student to a school: if they are
    currently an individual student, swap them back to a school ``STUDENT`` so a
    restored account is not left as an individual inside a school. A previously
    cleared discount is not resurrected (that is intentionally permanent)."""
    from accounts.models import Role, UserRole

    student_role = Role.objects.filter(name=Role.STUDENT).first()
    indv_role = Role.objects.filter(name=Role.INDIVIDUAL_STUDENT).first()
    if not student_role:
        return False
    has_indv = bool(indv_role and UserRole.objects.filter(user=student, role=indv_role).exists())
    has_student = UserRole.objects.filter(user=student, role=student_role).exists()
    if has_indv and not has_student:
        with transaction.atomic():
            UserRole.objects.filter(user=student, role=indv_role).delete()
            UserRole.objects.get_or_create(user=student, role=student_role)
        return True
    return False
