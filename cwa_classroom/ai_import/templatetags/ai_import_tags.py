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
