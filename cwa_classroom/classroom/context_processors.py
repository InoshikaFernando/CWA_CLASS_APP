from .models import SubjectApp


def subject_apps(request):
    """
    Inject subject apps into every template context.
    Used by the public nav dropdown to show available subjects.
    Only queries the database for authenticated users (the dropdown
    is only shown post-login).
    """
    if not request.user.is_authenticated:
        return {}
    return {
        'subject_apps': SubjectApp.objects.exclude(
            is_active=False, is_coming_soon=False
        ).order_by('order'),
    }
