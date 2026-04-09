from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django import template

register = template.Library()


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
