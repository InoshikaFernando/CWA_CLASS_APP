"""Stripe configuration and checkout health — the failures nobody was told about.

On 2026-09-07 a school student hit the payment page eleven times over two days.
Every attempt failed with the same Stripe message — *the price specified is
inactive* — because the price on the default package had been archived in the
Stripe dashboard. Nothing in the app changed; a field changed on Stripe's side.

The student saw "contact support". The reason sat in `/var/log/cwa/` and
nowhere else, so it took an SSH session and a grep to find, two weeks later.

Two answers live here, and they are deliberately different questions:

``get_checkout_failure_health``
    What has already failed. Reads the audit log, so it is the record of real
    students who could not pay.

``get_stripe_price_health``
    What is *about* to fail. Checks the price ids we hold against Stripe, so an
    archived price is visible before a student finds it.
"""
import logging
from datetime import timedelta

from django.core.cache import cache
from django.utils import timezone

logger = logging.getLogger(__name__)

#: Audit action written whenever a Stripe Checkout session cannot be created.
CHECKOUT_FAILED = 'checkout_session_failed'

#: Price validation costs one Stripe call per configured price, so the result is
#: cached. Short enough that a fix shows up while the admin is still on the page.
PRICE_CACHE_KEY = 'stripe_price_health_v1'
PRICE_CACHE_SECONDS = 600


def record_checkout_failure(exc, *, user=None, school=None, package=None,
                            plan=None, request=None, flow=''):
    """Record a failed checkout so it is visible in the app, not just the log.

    Never raises: a monitoring write must not turn a checkout failure the user
    is already being told about into a 500 on top of it.
    """
    try:
        from audit.services import log_event
        detail = {
            'error': str(exc)[:500],
            'error_type': type(exc).__name__,
            'flow': flow,
        }
        if package is not None:
            detail['package'] = getattr(package, 'name', str(package))
            detail['package_id'] = getattr(package, 'id', None)
            detail['stripe_price_id'] = getattr(package, 'stripe_price_id', '')
        if plan is not None:
            detail['plan'] = getattr(plan, 'name', str(plan))
            detail['plan_id'] = getattr(plan, 'id', None)
            detail['stripe_price_id'] = getattr(plan, 'stripe_price_id', '')
        log_event(
            user=user, school=school, category='billing',
            action=CHECKOUT_FAILED, result='blocked',
            detail=detail, request=request,
        )
    except Exception:  # noqa: BLE001 — monitoring must never break checkout
        logger.exception('Failed to record checkout failure for audit')


def get_checkout_failure_health(days=7, limit=20, now=None):
    """Return the Stripe checkouts that failed in the last ``days``.

    Keys:
        status     'ok' | 'warning' | 'critical'
        reasons    list[str] — why it is not ok (empty when ok)
        count      int  — failures in the window
        users      int  — distinct people who could not pay
        top_error  str  — the most common Stripe message, or ''
        rows       list[dict] — when, who, package, error; newest first
        truncated  bool — more rows exist than are listed
    """
    from audit.models import AuditLog

    now = now or timezone.now()
    since = now - timedelta(days=days)

    qs = (AuditLog.objects
          .filter(category='billing', action=CHECKOUT_FAILED, created_at__gte=since)
          .select_related('user')
          .order_by('-created_at'))

    total = qs.count()
    events = list(qs[:limit])

    rows = []
    user_ids = set()
    error_counts = {}
    for ev in events:
        detail = ev.detail if isinstance(ev.detail, dict) else {}
        error = (detail.get('error') or '').strip()
        error_counts[error] = error_counts.get(error, 0) + 1
        if ev.user_id:
            user_ids.add(ev.user_id)
        rows.append({
            'when': ev.created_at,
            'username': ev.user.username if ev.user else '—',
            'name': (ev.user.get_full_name() if ev.user else '') or '',
            'user_id': ev.user_id,
            'package': detail.get('package') or detail.get('plan') or '—',
            'stripe_price_id': detail.get('stripe_price_id', ''),
            'flow': detail.get('flow', ''),
            'error': error,
        })

    top_error = ''
    if error_counts:
        top_error = max(error_counts.items(), key=lambda kv: kv[1])[0]

    reasons = []
    status = 'ok'
    if total:
        # Any failure at all is someone who tried to pay and could not, so this
        # never sits quietly at 'ok' with a non-zero count.
        status = 'critical' if len(user_ids) > 1 or total >= 5 else 'warning'
        people = f'{len(user_ids)} student' + ('s' if len(user_ids) != 1 else '')
        reasons.append(
            f'{total} checkout attempt{"s" if total != 1 else ""} failed in the '
            f'last {days} days ({people} could not pay)'
        )

    return {
        'status': status,
        'reasons': reasons,
        'count': total,
        'users': len(user_ids),
        'days': days,
        'top_error': top_error,
        'rows': rows,
        'truncated': total > len(events),
    }


def _configured_prices():
    """Every Stripe price id the app would try to charge against.

    Yields ``(kind, label, price_id, obj_id)``. Only active, paid rows — a free
    package has no price id by design, and an inactive one charges nobody.
    """
    from .models import InstitutePlan, Package

    for pkg in Package.objects.filter(is_active=True, price__gt=0):
        yield ('Package', pkg.name, pkg.stripe_price_id, pkg.id)
    for plan in InstitutePlan.objects.filter(is_active=True, price__gt=0):
        yield ('InstitutePlan', plan.name, plan.stripe_price_id, plan.id)


def get_stripe_price_health(use_cache=True):
    """Check every configured Stripe price still exists and is active.

    This is the check that would have caught the archived price before a
    student did. Results are cached — it costs one Stripe call per price.

    Keys:
        status    'ok' | 'warning' | 'critical' | 'unknown'
        reasons   list[str]
        checked   int  — prices verified against Stripe
        broken    list[dict] — kind, label, price_id, problem
        skipped   str  — why the check did not run, when it did not
    """
    if use_cache:
        cached = cache.get(PRICE_CACHE_KEY)
        if cached is not None:
            return cached

    result = _compute_price_health()
    if use_cache:
        cache.set(PRICE_CACHE_KEY, result, PRICE_CACHE_SECONDS)
    return result


def _compute_price_health():
    import stripe

    from .stripe_service import _ensure_stripe_key, _stripe_configured

    if not _stripe_configured():
        return {
            'status': 'unknown', 'reasons': [], 'checked': 0, 'broken': [],
            'skipped': 'Stripe is not configured on this server.',
        }

    _ensure_stripe_key()
    broken = []
    checked = 0

    for kind, label, price_id, obj_id in _configured_prices():
        if not price_id:
            broken.append({
                'kind': kind, 'label': label, 'id': obj_id, 'price_id': '',
                'problem': 'No Stripe price id set — this plan cannot be paid for.',
            })
            continue
        try:
            price = stripe.Price.retrieve(price_id)
        except Exception as e:  # noqa: BLE001 — reported, not raised
            broken.append({
                'kind': kind, 'label': label, 'id': obj_id, 'price_id': price_id,
                'problem': f'Stripe rejected this price: {e}',
            })
            continue
        checked += 1
        if not price.get('active', True):
            broken.append({
                'kind': kind, 'label': label, 'id': obj_id, 'price_id': price_id,
                'problem': 'Archived in Stripe — checkout fails with '
                           '"The price specified is inactive".',
            })

    reasons = []
    status = 'ok'
    if broken:
        status = 'critical'
        reasons.append(
            f'{len(broken)} price{"s" if len(broken) != 1 else ""} cannot be '
            f'charged against — students on {"them" if len(broken) != 1 else "it"} '
            f'cannot pay'
        )

    return {
        'status': status, 'reasons': reasons, 'checked': checked,
        'broken': broken, 'skipped': '',
    }
