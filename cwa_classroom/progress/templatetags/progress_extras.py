"""Template helpers for the report settings page."""

from django import template

register = template.Library()


@register.filter
def setting_value(row, field):
    """The stored tri-state for *field*: ``True``, ``False`` or ``None``.

    ``None`` means "inherit", and is also what an absent row means — a scope
    with no row of its own inherits everything. Returning None for both keeps
    the radio group honest instead of defaulting an unset scope to "off".
    """
    if row is None:
        return None
    return getattr(row, field, None)
