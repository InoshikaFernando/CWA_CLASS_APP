"""Reusable "who is actually subscribed" queries.

One definition, used by every page that offers a *subscribed students only*
filter: a student is subscribed when **their own** ``billing.Subscription`` is
``active`` or ``trialing`` — the same rule ``Subscription.is_active_or_trialing``
states, kept here so a list filter, a report scope and a row badge cannot drift
apart.

A school's own plan (``SchoolSubscription``) is deliberately NOT consulted:
every student of a subscribed institute would then match, and a filter that
matches everybody tells staff nothing.
"""

from billing.models import Subscription

#: The statuses that count as subscribed. Cancelled, expired and past-due do
#: not — those students still have a Subscription row, which is exactly why
#: "has a subscription" is the wrong test.
SUBSCRIBED_STATUSES = (Subscription.STATUS_ACTIVE, Subscription.STATUS_TRIALING)


def filter_subscribed(queryset, path='subscription'):
    """Narrow *queryset* to rows whose related subscription is live.

    *path* is the ORM path from the queryset's model to the subscription, so
    a queryset of users passes the default and a queryset of enrolments passes
    e.g. ``'student__subscription'``. The join is an inner one, so a student
    with no subscription row at all drops out — which is the intent: no
    subscription is not a subscription.
    """
    return queryset.filter(**{f'{path}__status__in': SUBSCRIBED_STATUSES})


def is_subscribed(user):
    """Whether one user's own subscription is live, by the rule above.

    The single-row companion to :func:`filter_subscribed`, for the places that
    hold a user rather than a queryset — the report-automation outreach asks
    this per student to decide whether "nothing to show" means *no
    subscription* or *nothing done*. Written against the same
    ``SUBSCRIBED_STATUSES`` tuple so the two answers cannot drift.
    """
    subscription = getattr(user, 'subscription', None)
    return bool(subscription and subscription.status in SUBSCRIBED_STATUSES)


def school_discount_offer(school):
    """``(code, percent)`` for the school's usable signup discount, else ``(None, None)``.

    Validity is ``DiscountCode.is_valid()``, not ``is_active`` alone: a code can
    also be past its ``expires_at`` or have burned through ``max_uses``, and the
    checkout gate that receives it checks all three. Emailing a code the gate
    will reject hands the family a credential that fails on use — worse than
    sending none, because they cannot tell the difference.

    Returns the *stored* spelling of the code rather than the school's
    configured one, so what is emailed matches the row it came from.

    Lives here rather than beside either caller because two of them now exist —
    the welcome / resend email and the report-automation outreach email — and a
    family must not be offered a code by one and refused it by the other.
    """
    code = (getattr(school, 'subscription_discount_code', '') or '').strip()
    if not code:
        return None, None

    from billing.models import DiscountCode

    discount = DiscountCode.objects.filter(code__iexact=code).first()
    if not discount or not discount.is_valid():
        return None, None
    return discount.code, discount.discount_percent
