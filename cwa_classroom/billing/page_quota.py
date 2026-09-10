"""One monthly AI page budget, shared by every pipeline that spends pages.

Why this exists
---------------
The AI import tiers sell a monthly page allowance — Starter 300, Professional
600, Enterprise 1000, held on ``ModuleProduct.pages_per_month``. Three pipelines
turn a teacher's PDF into questions, and every page of every one of them is a
real AI call billed by Anthropic (and, for the second-opinion verifier, OpenAI):

    worksheets/tasks.py   process_worksheet_pdf
    ai_import/tasks.py    process_pdf_import
    homework/tasks.py     process_homework_pdf

Only the AI import path moved the counter, and only once the teacher reached the
final confirm step. Homework and worksheet uploads were never metered at all,
and an AI import that was uploaded but abandoned was free. A school on the
600-page tier could therefore spend several times its allowance with the quota
reading zero — one did: 962 homework pages in a month against a 600-page plan,
counter untouched.

This module is the single budget all three draw on:

    check_page_budget(school, pages)  before spending — may refuse, with a
                                      teacher-facing message naming the upgrade
    consume_pages(school, pages)      once the work is committed to
    quota_status(school)              the meter + 75% warning for the UI

Pages are charged at UPLOAD, before extraction, because that is when the money
is spent: the background worker makes the AI call whether or not the teacher
ever confirms the result.

Who is metered
--------------
The allowance *is* the AI import tier, so a school without one has no allowance
to draw down and is left unmetered — exactly as it was before this module
existed. Metering a school that never bought a tier would cut off homework
upload for everyone on a plain plan, which is a pricing decision, not a
quota-enforcement one. ``quota_status()['metered']`` says which case a school is
in so the UI can stay quiet rather than render an empty 0/0 meter.
"""
import logging

logger = logging.getLogger(__name__)

# Fraction of the allowance at which the UI starts warning the teacher. Set so
# a school sees it coming with roughly a quarter of the month's pages left,
# rather than discovering the limit by being refused mid-upload.
WARN_RATIO = 0.75

# Sentinel "no ceiling" used by the pre-existing quota API and the superuser
# path. Kept as a large int rather than None so callers can compare numerically.
UNLIMITED = 999999

AI_IMPORT_MODULE_PREFIX = 'ai_import_'

TIER_NAMES = {
    'ai_import_starter': 'Starter',
    'ai_import_professional': 'Professional',
    'ai_import_enterprise': 'Enterprise',
}


def tier_label(module_slug):
    """'Professional' for 'ai_import_professional' — falls back to the slug."""
    if not module_slug:
        return ''
    return TIER_NAMES.get(
        module_slug,
        module_slug.replace(AI_IMPORT_MODULE_PREFIX, '').replace('_', ' ').title(),
    )


def current_period_start():
    """First day of the month the quota is counted over."""
    from django.utils import timezone as tz
    return tz.localdate().replace(day=1)


def _period_reset_label():
    """'1 October' — when the allowance next resets, for the block message."""
    start = current_period_start()
    year, month = (start.year + 1, 1) if start.month == 12 else (start.year, start.month + 1)
    return f'1 {start.replace(year=year, month=month, day=1):%B}'


def _active_tier(school):
    """``(module_slug, ModuleProduct)`` for the school's AI tier, or ``(None, None)``."""
    from billing.entitlements import get_school_subscription
    from billing.models import ModuleProduct

    sub = get_school_subscription(school)
    if not sub:
        return None, None
    module = sub.modules.filter(
        module__startswith=AI_IMPORT_MODULE_PREFIX, is_active=True,
    ).first()
    if not module:
        return None, None
    try:
        return module.module, ModuleProduct.objects.get(module=module.module)
    except ModuleProduct.DoesNotExist:
        # A tier the catalogue doesn't know about can't name a page limit.
        # Treat it as unmetered rather than silently refusing every upload.
        logger.warning(
            'School %s is on AI module %s with no ModuleProduct row — '
            'page quota not enforced for it.', getattr(school, 'pk', None), module.module,
        )
        return module.module, None


def get_usage_row(school):
    """The school's usage row for this period, created on first touch."""
    from ai_import.models import AIImportUsage
    usage, _ = AIImportUsage.objects.get_or_create(
        school=school, period_start=current_period_start(),
        defaults={'pages_processed': 0, 'tokens_used': 0},
    )
    return usage


def next_tier_above(limit):
    """Cheapest AI import tier with a bigger allowance than ``limit``, or None.

    Read from the catalogue rather than a hard-coded ladder so adding a tier
    doesn't need this module changed to be suggested.
    """
    from billing.models import ModuleProduct
    return (
        ModuleProduct.objects
        .filter(module__startswith=AI_IMPORT_MODULE_PREFIX,
                is_active=True, pages_per_month__gt=limit)
        .order_by('pages_per_month')
        .first()
    )


def _unmetered(reason, tier_name=''):
    """Status for a school this budget does not apply to."""
    return {
        'metered': False, 'unlimited': True, 'limit': 0, 'used': 0,
        'remaining': UNLIMITED, 'percent': 0, 'warn': False, 'exhausted': False,
        'no_allowance': False,
        'tier_name': tier_name, 'next_tier_name': '', 'next_tier_pages': 0,
        'reset_label': _period_reset_label(), 'reason': reason,
    }


# Reasons a school has no allowance at all, as opposed to having spent one.
# check_page_budget writes a different message for each: "buy the module" is
# useless advice to someone with no school to attach it to, and "wait for your
# allowance to reset" is useless advice to someone who never had one.
NO_ALLOWANCE_REASONS = ('no_ai_module', 'no_school')


def _no_allowance(reason):
    """Status for a school that has never had an allowance to spend.

    Metered with a limit of zero rather than unmetered. Before this, a school
    with no AI module fell through as unmetered and uploaded unlimited PDFs
    through homework and worksheets — every page a real Anthropic call — while
    the schools that *had* bought a tier were the only ones capped. The tier is
    the licence to spend AI pages at all, wherever the upload starts.
    """
    return {
        'metered': True, 'unlimited': False, 'limit': 0, 'used': 0,
        'remaining': 0, 'percent': 100, 'warn': False, 'exhausted': True,
        # The one the templates branch on: "never had an allowance", as opposed
        # to `exhausted`, which means "had one and spent it". They need
        # different words and a different link.
        'no_allowance': True,
        'tier_name': '', 'next_tier_name': '', 'next_tier_pages': 0,
        'reset_label': _period_reset_label(), 'reason': reason,
    }


def quota_status(school, *, unlimited=False):
    """This month's page budget for ``school``, shaped for templates.

    ``unlimited=True`` is the superuser path. Keys:

    ``metered``       whether the limit binds at all (see module docstring)
    ``limit``/``used``/``remaining``/``percent``
    ``warn``          used >= 75% of the allowance and not yet exhausted
    ``exhausted``     nothing left this month
    ``tier_name``     'Professional'
    ``next_tier_name``/``next_tier_pages``  the upgrade to offer, if any
    ``reset_label``   '1 October'
    """
    if unlimited:
        return _unmetered('superuser', tier_name='Unlimited (Admin)')
    if school is None:
        # A teacher role is school-linked by construction, so this is an account
        # part-way through setup rather than a supported kind of user. It has no
        # subscription to charge, so it cannot spend AI pages.
        return _no_allowance('no_school')

    module_slug, product = _active_tier(school)
    if module_slug is None:
        # No AI module at all — no allowance to draw on, anywhere.
        return _no_allowance('no_ai_module')
    if product is None:
        # On a tier the catalogue has no row for: a paying school we can't price.
        # _active_tier has already logged it; fail open rather than refuse a
        # school that has actually bought something.
        return _unmetered('tier_not_in_catalogue', tier_name=tier_label(module_slug))

    # NULL = not applicable, 0 = unlimited (ModuleProduct.pages_per_month).
    if product.pages_per_month is None or product.pages_per_month == 0:
        return _unmetered('tier_unlimited', tier_name=tier_label(module_slug))

    limit = product.pages_per_month
    used = get_usage_row(school).pages_processed
    remaining = max(0, limit - used)
    percent = min(100, round(used / limit * 100))
    upgrade = next_tier_above(limit)

    return {
        'metered': True,
        'unlimited': False,
        'no_allowance': False,
        'limit': limit,
        'used': used,
        'remaining': remaining,
        'percent': percent,
        'warn': remaining > 0 and used >= limit * WARN_RATIO,
        'exhausted': remaining == 0,
        'tier_name': tier_label(module_slug),
        'next_tier_name': tier_label(upgrade.module) if upgrade else '',
        'next_tier_pages': upgrade.pages_per_month if upgrade else 0,
        'reset_label': _period_reset_label(),
        'reason': '',
    }


def _upgrade_sentence(status):
    """'Upgrade to Enterprise (1,000 pages a month) to carry on…' or the fallback."""
    if status['next_tier_name']:
        return (f'Upgrade to {status["next_tier_name"]} '
                f'({status["next_tier_pages"]:,} pages a month) to carry on, '
                f'or wait until your allowance resets on {status["reset_label"]}.')
    return (f'You are already on the largest plan — please contact us if you need '
            f'more, or wait until your allowance resets on {status["reset_label"]}.')


def ai_plans_url():
    """Where a teacher goes to buy AI pages.

    The AI import tier comparison — Starter / Professional / Enterprise with
    their monthly page counts — which is the thing being bought, whichever
    upload screen the teacher was refused on. Not itself gated.
    """
    from django.urls import reverse, NoReverseMatch
    try:
        return reverse('ai_import:tier_select')
    except NoReverseMatch:  # pragma: no cover - urlconf without ai_import
        return ''


def _no_allowance_message(status):
    """What a teacher whose school has no AI pages at all should read.

    Marked safe so the toast can carry the link; every part of it is a literal
    or a reversed URL, so there is nothing user-supplied to escape.
    """
    from django.utils.html import format_html
    from django.utils.safestring import mark_safe

    if status['reason'] == 'no_school':
        return mark_safe(
            'Your account is not linked to a school yet, so it has no AI page '
            'allowance to draw on. Ask your institute administrator to add you, '
            'then try again.'
        )

    url = ai_plans_url()
    body = ('Reading a PDF with AI needs an AI module, and your school does not '
            'have one. You can still upload authored questions as JSON or ZIP, '
            'and build homework from the question bank, without it.')
    if not url:
        return mark_safe(body)
    return format_html(
        '{} <a href="{}" class="underline font-semibold">See the AI plans</a>.',
        body, url,
    )


def check_page_budget(school, pages, *, unlimited=False):
    """Can ``school`` afford ``pages`` right now?

    Returns ``(allowed, message, status)``. ``message`` is None when allowed and
    otherwise written for the teacher — it names the tier, what is left, and the
    upgrade that unblocks them. Callers show it and stop; nothing is consumed
    here, so a refused upload costs the school nothing.
    """
    status = quota_status(school, unlimited=unlimited)
    if not status['metered']:
        return True, None, status

    pages = max(0, int(pages or 0))
    if pages <= status['remaining']:
        return True, None, status

    # Never had an allowance, as opposed to having spent one. "Upgrade" and
    # "wait for your reset" are both wrong here — there is nothing to upgrade
    # from and the reset lands on the same zero. Point at the plans instead.
    if status['reason'] in NO_ALLOWANCE_REASONS:
        return False, _no_allowance_message(status), status

    if status['exhausted']:
        message = (
            f'You have used all {status["limit"]:,} pages of your monthly '
            f'{status["tier_name"]} page allowance. {_upgrade_sentence(status)}'
        )
    else:
        message = (
            f'This upload needs {pages:,} page{"" if pages == 1 else "s"} but only '
            f'{status["remaining"]:,} of your {status["limit"]:,}-page monthly '
            f'{status["tier_name"]} allowance '
            f'{"is" if status["remaining"] == 1 else "are"} left. '
            f'Select fewer pages, or upload a smaller file. {_upgrade_sentence(status)}'
        )
    return False, message, status


def consume_pages(school, pages, *, unlimited=False):
    """Charge ``pages`` to the school's monthly allowance.

    Called once an upload is committed to — i.e. the extraction job is queued —
    because that is the point the AI spend becomes unavoidable. The increment is
    an F() expression so two uploads landing together can't lose one another's
    pages.

    Never raises into the caller: a quota row that fails to update must not fail
    an upload the teacher has already been told is under way. It is logged
    loudly instead, because silently under-counting is exactly the bug this
    module exists to fix.
    """
    if unlimited or school is None:
        return
    pages = max(0, int(pages or 0))
    if not pages:
        return
    status = quota_status(school)
    if not status['metered']:
        return
    try:
        from django.db.models import F
        from ai_import.models import AIImportUsage
        row = get_usage_row(school)
        AIImportUsage.objects.filter(pk=row.pk).update(
            pages_processed=F('pages_processed') + pages,
        )
    except Exception:
        logger.exception(
            'Failed to charge %s page(s) to school %s — the monthly AI page '
            'quota is now under-counting for this period.',
            pages, getattr(school, 'pk', None),
        )


def refund_pages(school, pages, *, unlimited=False):
    """Give ``pages`` back after an upload that was charged but never ran.

    The enqueue failure paths delete the session and tell the teacher to try
    again; without this the pages would stay spent on work that never happened.
    Floors at zero so a double refund can't mint allowance.
    """
    if unlimited or school is None:
        return
    pages = max(0, int(pages or 0))
    if not pages:
        return
    try:
        from django.db.models import F, Value
        from django.db.models.functions import Greatest
        from ai_import.models import AIImportUsage
        row = get_usage_row(school)
        AIImportUsage.objects.filter(pk=row.pk).update(
            pages_processed=Greatest(
                F('pages_processed') - pages, Value(0),
            ),
        )
    except Exception:
        logger.exception(
            'Failed to refund %s page(s) to school %s after a failed upload.',
            pages, getattr(school, 'pk', None),
        )


def upload_page_count(selected_pages, total_pages, pdf_source):
    """How many pages an upload will actually charge for.

    ``clean_upload_selection`` short-circuits on a blank spec and returns
    ``(None, None)`` for selection/total without opening the PDF, so the common
    "extract everything" upload still has to be counted here. Only the selected
    pages are rendered and sent to the AI, so only those are charged.

    A file PyMuPDF can't open counts as one page rather than raising. The quota
    is not the right place to reject a corrupt upload — the extraction pipeline
    already fails it with a message about the PDF, and turning that into a
    billing error would report the wrong problem. One page keeps an exhausted
    school blocked (so this isn't a bypass) while charging almost nothing for
    work that is about to fail anyway.
    """
    if selected_pages is not None:
        return len(selected_pages)
    if total_pages:
        return total_pages
    from worksheets.page_selection import pdf_page_count
    try:
        return pdf_page_count(pdf_source)
    except Exception as exc:
        logger.info(
            'Could not count pages for a PDF upload (%s); charging 1 page. '
            'The extraction job will report the real problem.', exc,
        )
        return 1
