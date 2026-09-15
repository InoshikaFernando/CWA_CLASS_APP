from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def school_has_ai_import(context):
    """
    Check if the current user's school has any AI import module enabled.

    Usage: {% school_has_ai_import as has_ai %}
    """
    request = context.get('request')
    if not request or not hasattr(request, 'user') or not request.user.is_authenticated:
        return False

    if request.user.is_superuser:
        return True

    from ai_import.views import _has_ai_import_access
    return _has_ai_import_access(request.user)


@register.filter
def review_points(question):
    """The "what to check" advice for a flagged question, field by field.

    Usage: {% for point in q|review_points %}{{ point.label }}: {{ point.text }}

    See ai_import.review_points — the preview screens render these instead of
    hiding the whole reason in the review badge's tooltip.
    """
    from ai_import.review_points import review_points as _points
    return _points(question)
