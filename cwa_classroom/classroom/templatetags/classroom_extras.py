from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django import template

register = template.Library()


# Progress rubric (§12.7) → Tailwind colour classes, ordered worst→best.
_PROGRESS_BADGE_CLASSES = {
    'advanced': 'bg-emerald-100 text-emerald-700',
    'confident': 'bg-teal-100 text-teal-700',
    'developing': 'bg-amber-100 text-amber-700',
    'beginning': 'bg-orange-100 text-orange-700',
    'not_started': 'bg-slate-100 text-slate-500',
    'not_assessed': 'bg-slate-100 text-slate-400',
}
_PROGRESS_SELECT_CLASSES = {
    'advanced': 'bg-emerald-50 text-emerald-700',
    'confident': 'bg-teal-50 text-teal-700',
    'developing': 'bg-amber-50 text-amber-700',
    'beginning': 'bg-orange-50 text-orange-700',
}


_PROGRESS_LABELS = {
    'advanced': 'Advanced',
    'confident': 'Confident',
    'developing': 'Developing',
    'beginning': 'Beginning',
    'not_started': 'Not Started',
    'not_assessed': 'Not Assessed',
}
_PROFICIENT = ('confident', 'advanced')
_DEVELOPING = ('beginning', 'developing')


@register.filter
def progress_badge_classes(status):
    """Tailwind classes for a progress-rating pill (§12.7)."""
    return _PROGRESS_BADGE_CLASSES.get(status, 'bg-slate-100 text-slate-500')


@register.filter
def progress_status_label(status):
    """Human label for a progress status (handles the 'not_assessed' pseudo-state)."""
    return _PROGRESS_LABELS.get(status, status)


@register.filter
def progress_bucket(status):
    """Collapse a rubric status into a summary bucket for icon selection."""
    if status in _PROFICIENT:
        return 'proficient'
    if status in _DEVELOPING:
        return 'developing'
    if status == 'not_started':
        return 'not_started'
    return 'not_assessed'


@register.filter
def progress_select_classes(status):
    """Tailwind bg/text classes for a progress-rating <select> (§12.7)."""
    return _PROGRESS_SELECT_CLASSES.get(status, 'bg-white')


@register.filter
def pct_text(value):
    """Text colour for a score %: green when done (>0), ash-grey when 0/none."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return 'text-emerald-600' if v > 0 else 'text-gray-400'


@register.filter
def pct_bar(value):
    """Bar-fill colour matching :func:`pct_text` (green when done, grey when 0)."""
    try:
        v = int(value)
    except (TypeError, ValueError):
        v = 0
    return 'bg-emerald-500' if v > 0 else 'bg-slate-200'


@register.filter
def get_item(dictionary, key):
    """Look up a dictionary value by key in a template."""
    if dictionary is None:
        return ''
    return dictionary.get(key, '')


@register.filter
def format_currency(value, currency=None):
    """Format *value* as a currency string using a :class:`~classroom.models.Currency` instance.

    Usage in templates::

        {% load classroom_extras %}
        {{ invoice.amount|format_currency:school.default_currency }}

    If *currency* is ``None`` (e.g. the FK is not yet assigned), falls back to
    a plain two-decimal-place representation prefixed with ``$``::

        {{ invoice.amount|format_currency }}     → "$120.00"

    When *currency* is provided its ``format_amount()`` method is used, which
    honours ``symbol``, ``symbol_position``, and ``decimal_places``.
    """
    if value is None:
        return ''
    try:
        # Ensure we have a Decimal for safety
        decimal_value = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return str(value)

    if currency is None:
        # Fallback: two decimal places, $ prefix (existing behaviour)
        formatted = f'{decimal_value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP):.2f}'
        return f'${formatted}'

    return currency.format_amount(decimal_value)
