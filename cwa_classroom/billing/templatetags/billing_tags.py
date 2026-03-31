from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def school_has_module(context, module_slug):
    """
    Check if the current user's school has a specific module enabled.
    For multi-school students, returns True if ANY school has the module.

    Usage: {% school_has_module 'teachers_attendance' as has_ta %}
    """
    # First check the primary school subscription (fast path)
    sub = context.get('school_subscription')
    if sub and sub.modules.filter(module=module_slug, is_active=True).exists():
        return True

    # Multi-school fallback: check all schools the user belongs to
    request = context.get('request')
    if request and hasattr(request, 'user') and request.user.is_authenticated:
        from billing.entitlements import has_module_any_school
        return has_module_any_school(request.user, module_slug)

    return False
