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


def filter_unsubscribed(queryset, path='subscription'):
    """Narrow *queryset* to rows whose related subscription is NOT live.

    The complement of :func:`filter_subscribed`, stated against the same list of
    statuses so the two cannot drift into overlapping or leaving a gap.

    **Includes rows with no subscription at all**, which is the whole point and
    is not what the obvious spelling does. ``filter_subscribed`` joins, so a
    student with no subscription row simply is not in it; the mirror image of
    that — ``filter(status__in=<everything else>)`` — would ALSO join and would
    quietly reach only students who subscribed once and lapsed. For a promotion
    aimed at people who have never paid, that is precisely the wrong half, and
    the query returns rows either way so nothing looks wrong.

    ``exclude`` does the right thing here because Django compiles it to a NOT
    IN subquery rather than a join, so a student with no subscription is not
    excluded by it. That behaviour is pinned by a test rather than trusted.
    """
    return queryset.exclude(**{f'{path}__status__in': SUBSCRIBED_STATUSES})
