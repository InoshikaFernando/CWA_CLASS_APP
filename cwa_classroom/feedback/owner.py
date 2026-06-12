"""
Helpers for resolving the platform feedback owner and authorising the
triage surface (CPP-321).

Feedback is platform-wide rather than per-tenant: every submission is
assigned to a single product owner who runs the weekly triage. The owner is
resolved from ``settings.FEEDBACK_OWNER_EMAIL`` when configured, falling back
to the first superuser so the feature still works on a fresh install.
"""
from django.conf import settings


def get_feedback_owner():
    """Return the CustomUser who owns the feedback queue, or None.

    Priority: ``settings.FEEDBACK_OWNER_EMAIL`` → first active superuser.
    """
    from accounts.models import CustomUser

    email = getattr(settings, 'FEEDBACK_OWNER_EMAIL', '') or ''
    if email:
        owner = CustomUser.objects.filter(email__iexact=email).first()
        if owner:
            return owner
    return CustomUser.objects.filter(is_superuser=True).order_by('id').first()


def is_feedback_owner(user):
    """True if ``user`` may access the triage dashboard.

    The owner is the platform admin: a superuser or any user holding the
    ``admin`` role. Per-school staff (HoI/HoD/teachers) do not get access —
    triage is centralised with the platform owner.
    """
    from accounts.models import Role

    if not user or not user.is_authenticated:
        return False
    return bool(user.is_superuser or user.has_role(Role.ADMIN))
