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
