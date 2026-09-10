from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def school_has_module(context, module_slug):
    """Whether the current user is entitled to *module_slug*.

    Usage: ``{% school_has_module 'teachers_attendance' as has_ta %}``

    Reads the same per-request set the enforcement middleware decides on, so a
    link cannot be shown for something the next click will refuse — the two
    used to be independent implementations, and a sidebar asking about six
    modules paid for the per-school, per-module walk six times over.

    The name is kept for the templates that already call it, though it now
    also covers a student's own modules. Renaming it would touch every
    sidebar for no behaviour change.
    """
    request = context.get('request')
    if request is None or not getattr(request, 'user', None):
        return False
    if not request.user.is_authenticated:
        return False

    from billing.entitlements import entitled_modules
    return module_slug in entitled_modules(request)


@register.simple_tag(takes_context=True)
def entitled_modules_list(context):
    """Every module slug the current user holds.

    For a nav that renders from the registry rather than from a hand-kept list
    of ``{% if %}`` blocks — the reason only 2 of the 10 sidebars ever checked
    a module was that each one had to be edited by hand.
    """
    request = context.get('request')
    if request is None or not getattr(request, 'user', None):
        return frozenset()
    if not request.user.is_authenticated:
        return frozenset()

    from billing.entitlements import entitled_modules
    return entitled_modules(request)


@register.inclusion_tag(
    'billing/_ai_grading_alert_modal.html', takes_context=True)
def ai_grading_login_alert(context):
    """The head-of-institute AI grading warning, shown once per login per rung.

    An inclusion tag rather than a context processor on purpose: a context
    processor lives in settings.py, and settings.py is watched by ci.yml's
    `shared` filter — the escape hatch that runs every unit suite and every
    Playwright group. A banner does not need to cost a full CI matrix.
    """
    request = context.get('request')
    if not request or not hasattr(request, 'user'):
        return {'alert': None}
    from billing.quota_alerts import grading_alert_for_user
    return {
        'alert': grading_alert_for_user(request.user, getattr(request, 'session', None)),
    }


@register.filter
def money(amount):
    """Render a price with the currency that will actually be charged.

    Every price in this product used to render as a bare ``$``, while
    ``STRIPE_CURRENCY`` decides what the card is billed in. That is only
    unambiguous to an American: the customers here are a Melbourne Pty Ltd and
    an Aotearoa institute, and "$189.00/month" reads to both of them as their
    own dollar — a reading that is reasonable rather than careless, and wrong
    by roughly half.

    The system already knows two currencies are in play: invoices to families
    deliberately use the school's ``default_currency`` while subscriptions use
    the env var (see ``stripe_service`` around the invoice-payment path). It
    displayed neither.

    A filter rather than a context variable so it cannot be half-applied: a
    template that renders a price without it is visibly different from one
    that does, and there is one format to change if it ever needs changing.

    Usage: ``{{ plan.price|money }}`` -> ``USD $189.00``
    """
    from django.conf import settings

    if amount is None or amount == '':
        return ''
    code = (getattr(settings, 'STRIPE_CURRENCY', 'usd') or 'usd').upper()
    try:
        return f'{code} ${amount:.2f}'
    except (TypeError, ValueError):
        # A price that is not a number is a bug elsewhere; showing it bare is
        # better than a 500 on the page where somebody agrees to pay.
        return f'{code} ${amount}'
