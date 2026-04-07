"""
Project-level context processors.
These are injected into every template rendered by Django.
"""

from django.conf import settings


def app_version(request):
    """Expose APP_VERSION and APP_VERSION_DATE to all templates."""
    return {
        'APP_VERSION':      getattr(settings, 'APP_VERSION',      '1.0.0'),
        'APP_VERSION_DATE': getattr(settings, 'APP_VERSION_DATE', ''),
    }
