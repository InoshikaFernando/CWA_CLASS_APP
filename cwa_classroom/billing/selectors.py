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
