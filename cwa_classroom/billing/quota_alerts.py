"""Usage warnings for the AI grading allowance — email the institute before it stops.

An institute that runs out of AI grading mid-term finds out when children stop
being marked, which is the worst possible moment and the worst possible
messenger. So the school admin is emailed as the allowance is consumed:

    75%  80%  85%  90%  95%   warning — how much is left, and the upgrade
    100%                      stopped — AI grading is off until reset/upgrade

Each threshold fires **once per school per month**. The high-water mark lives on
``AIGradingUsage.highest_alert_sent`` (one row per school per month, so it resets
by itself on the 1st), and is claimed with a conditional UPDATE: two answers
graded at the same instant can both compute "95%", but only one of them wins the
row and sends the mail.

Emails never raise into the grader. A mail server having a bad afternoon must
not fail a child's answer, so failures are logged and swallowed — the quota
itself is still enforced either way.
"""
import logging

logger = logging.getLogger(__name__)

# Ascending, and 100 is one of them: "you have been stopped" is the same
# mechanism as "you are nearly stopped", just the last rung.
ALERT_THRESHOLDS = (75, 80, 85, 90, 95, 100)

GRADING_TIER_ORDER = [
    'ai_grading_starter',
    'ai_grading_professional',
    'ai_grading_enterprise',
]


def threshold_reached(percent):
    """Highest configured threshold at or below ``percent``, else 0."""
    reached = [t for t in ALERT_THRESHOLDS if percent >= t]
    return max(reached) if reached else 0


def next_grading_tier(current_slug):
    """The tier above ``current_slug``, or None if already at the top."""
    from billing.models import ModuleProduct
    try:
        index = GRADING_TIER_ORDER.index(current_slug)
    except ValueError:
        return None
    for slug in GRADING_TIER_ORDER[index + 1:]:
        product = ModuleProduct.objects.filter(module=slug, is_active=True).first()
        if product:
            return product
    return None


def _claim_threshold(usage_row, threshold):
    """Claim ``threshold`` for this period, returning True if we won the race.

    A conditional UPDATE rather than a read-then-save: the check and the claim
    are one statement, so concurrent graders can't both decide they are the one
    to send the 95% email.
    """
    from billing.models import AIGradingUsage
    claimed = AIGradingUsage.objects.filter(
        pk=usage_row.pk, highest_alert_sent__lt=threshold,
    ).update(highest_alert_sent=threshold)
    return bool(claimed)


def _recipients(school):
    """Who hears about the institute's allowance — admin first, deduplicated."""
    emails = []
    admin = getattr(school, 'admin', None)
    if admin and admin.email:
        emails.append((admin.email, admin))

    # Heads of institute carry the same commercial responsibility as the
    # nominal admin, and on bigger schools they are the ones who actually hold
    # the card. Missing them means the warning lands nowhere. Note that roles
    # are school-scoped through SchoolTeacher, not through UserRole — UserRole
    # is global and has no school.
    try:
        from classroom.models import SchoolTeacher
        heads = SchoolTeacher.objects.filter(
            school=school, role='head_of_institute',
        ).select_related('teacher')
        for head in heads:
            if head.teacher and head.teacher.email:
                emails.append((head.teacher.email, head.teacher))
    except Exception:
        logger.exception('Could not resolve institute heads for school %s',
                         getattr(school, 'pk', None))

    seen, unique = set(), []
    for email, user in emails:
        key = email.lower()
        if key not in seen:
            seen.add(key)
            unique.append((email, user))
    return unique


def send_grading_quota_alert(school, *, percent, used, limit, tier_slug, stopped):
    """Email the institute that its AI grading allowance is running out (or has)."""
    from classroom.email_service import send_templated_email

    upgrade = next_grading_tier(tier_slug)
    context = {
        'school': school,
        'percent': percent,
        'used': used,
        'limit': limit,
        'remaining': max(0, limit - used),
        'stopped': stopped,
        'next_tier_name': upgrade.name if upgrade else '',
        'next_tier_answers': upgrade.questions_per_month if upgrade else None,
        'next_tier_price': upgrade.price if upgrade else None,
    }
    subject = (
        f'AI grading paused for {school.name} — monthly allowance used up'
        if stopped else
        f'{percent}% of {school.name}’s AI grading allowance used'
    )

    sent = 0
    for email, user in _recipients(school):
        try:
            ok = send_templated_email(
                recipient_email=email,
                subject=subject,
                template_name='billing/email/ai_grading_quota_alert.html',
                context=context,
                recipient_user=user,
                notification_type='ai_grading_quota',
                school=school,
            )
            sent += 1 if ok else 0
        except Exception:
            logger.exception(
                'Failed to send AI grading quota alert to %s for school %s',
                email, getattr(school, 'pk', None),
            )
    if not sent:
        logger.warning(
            'AI grading quota alert at %s%% for school %s reached nobody — '
            'no institute email address resolved or delivery failed.',
            percent, getattr(school, 'pk', None),
        )
    return sent


def check_grading_quota_alerts(school, used, limit):
    """Send the threshold email if this usage crosses a rung not yet sent.

    Called after each recorded AI grading call. Cheap when nothing has changed:
    an unclaimed threshold is a single indexed UPDATE that matches no rows.
    Never raises — see the module docstring.
    """
    if not school or not limit:
        return None
    try:
        percent = min(100, int(used / limit * 100))
        threshold = threshold_reached(percent)
        if not threshold:
            return None

        from billing.models import AIGradingUsage
        from django.utils import timezone
        period_start = timezone.localdate().replace(day=1)
        row = AIGradingUsage.objects.filter(
            school=school, period_start=period_start,
        ).first()
        if row is None or row.highest_alert_sent >= threshold:
            return None
        if not _claim_threshold(row, threshold):
            return None

        from worksheets.grading_service import get_ai_grading_tier
        send_grading_quota_alert(
            school, percent=percent, used=used, limit=limit,
            tier_slug=get_ai_grading_tier(school), stopped=threshold >= 100,
        )
        return threshold
    except Exception:
        logger.exception(
            'AI grading quota alert check failed for school %s',
            getattr(school, 'pk', None),
        )
        return None
