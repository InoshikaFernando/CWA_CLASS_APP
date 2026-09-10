"""The AI Question Import tier ladder — one source of truth for what is shown.

Two problems live here, and they are different sizes.

The small one: the plans page and the institute dashboard each carried their own
hard-coded copy of the tier table, with ``price`` meaning the FULL price on one
and the DISCOUNTED price on the other, and each spelled the introductory offer
out in its own typed words. They drifted, as duplicated copy does — the plans
page ended up promising "50% off your first year" in the banner and "full price
applies after 6 months" on the line directly below it.

The large one: BOTH copies were fiction. A school is charged the Stripe price
behind ``ModuleProduct.stripe_price_id``, and in production those are $29/$59/$99
— while the plans page advertised $15/$30/$50 as the price and $30/$60/$99 as
the struck-out "full" price. Neither number on the page was the number on the
invoice. A school clicking "Activate Starter" under a $15 heading was billed $29.

So the ladder is read from the catalogue that Stripe is synced against, rather
than typed. If the price changes in ``ModuleProduct`` (and is synced), the shop
window changes with it, because it IS the shop window.
"""
import logging

logger = logging.getLogger(__name__)

MODULE_PREFIX = 'ai_import_'


# ---------------------------------------------------------------------------
# The introductory offer
# ---------------------------------------------------------------------------
#
# Half price for the first year, then full price. Stated on the plans page and
# the institute dashboard.
#
# ---------------------------------------------------------------------------
# READ THIS BEFORE CHANGING THE PRICES
# ---------------------------------------------------------------------------
# The discount is DISPLAY ONLY until a Stripe coupon exists for it. Nothing in
# the add-module path applies one: ``ModuleToggleView`` hands
# ``ModuleProduct.stripe_price_id`` to
# ``stripe_service.add_module_to_subscription``, which creates a plain
# ``SubscriptionItem`` at that price — no coupon, no schedule, no end date. So
# until the coupon is wired, a school shown $14.50 is invoiced $29.
#
# To make it true: create a Stripe coupon with
# ``percent_off=INTRO_DISCOUNT_PERCENT``, ``duration='repeating'``,
# ``duration_in_months=INTRO_DISCOUNT_MONTHS``, and ``applies_to.products``
# limited to the AI import products — so the school's institute plan is not
# discounted along with the module — then attach it when the module is added.
# ``stripe_service._build_stripe_coupon_kwargs`` already builds repeating
# coupons for discount codes and is the place to extend.
#
# Setting this to False takes the offer off both pages in one edit; the prices
# shown then fall back to the catalogue price, which is what is charged.
INTRO_DISCOUNT_ENABLED = True
INTRO_DISCOUNT_PERCENT = 50
INTRO_DISCOUNT_MONTHS = 12
INTRO_DISCOUNT_LABEL = 'first year'


def _display_name(product):
    """'AI Question Import - Starter' → 'Starter'.

    Same convention the dashboard already uses for the grading ladder, so a
    catalogue rename shows through without a code change.
    """
    return product.name.split('-')[-1].strip() or product.name


def _intro_price(price):
    """The advertised first-year price, derived rather than typed."""
    from decimal import Decimal, ROUND_HALF_UP

    factor = Decimal(100 - INTRO_DISCOUNT_PERCENT) / Decimal(100)
    return (Decimal(price) * factor).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def ai_import_tiers(current_slug=None):
    """The ladder as the pages should show it, cheapest first.

    Reads ``ModuleProduct`` — the rows ``sync_stripe_prices`` matches against
    Stripe — so the advertised price is the one that will be charged. A tier
    with no active catalogue row is left out rather than advertised: it cannot
    be bought, because ``ModuleToggleView`` has no price to send to Stripe.
    """
    from billing.models import ModuleProduct

    products = (
        ModuleProduct.objects
        .filter(module__startswith=MODULE_PREFIX, is_active=True)
        .order_by('pages_per_month', 'price')
    )

    tiers = []
    for product in products:
        if not product.stripe_price_id:
            # Buying it would fall through to the local-activation branch and
            # give the school the module for nothing. Don't offer it.
            logger.warning(
                'AI import tier %s has no stripe_price_id — not advertising it.',
                product.module,
            )
            continue
        tiers.append({
            'slug': product.module,
            'name': _display_name(product),
            'pages': product.pages_per_month or 0,
            'price': product.price,
            'intro_price': _intro_price(product.price),
            'is_current': product.module == current_slug,
        })
    return tiers


def discount_context():
    """The offer's wording, for any template that states it."""
    return {
        'ai_discount_enabled': INTRO_DISCOUNT_ENABLED,
        'ai_discount_percent': INTRO_DISCOUNT_PERCENT,
        'ai_discount_months': INTRO_DISCOUNT_MONTHS,
        'ai_discount_label': INTRO_DISCOUNT_LABEL,
    }
