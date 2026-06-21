"""WhatsApp provider abstraction.

One backend is live (Meta Cloud API). Twilio and an unofficial group-posting
backend are stubs occupying the same interface so they can be swapped in via
the ``WHATSAPP_PROVIDER`` setting without touching call sites.
"""
from django.conf import settings

from .base import BaseWhatsAppProvider, WhatsAppSendError
from .meta_cloud import MetaCloudProvider
from .twilio import TwilioProvider
from .unofficial_group import UnofficialGroupProvider

PROVIDERS = {
    'meta_cloud': MetaCloudProvider,
    'twilio': TwilioProvider,
    'unofficial_group': UnofficialGroupProvider,
}


def get_provider(name=None):
    name = name or getattr(settings, 'WHATSAPP_PROVIDER', 'meta_cloud')
    try:
        provider_cls = PROVIDERS[name]
    except KeyError:
        raise ValueError(f'Unknown WhatsApp provider: {name!r}')
    return provider_cls()


__all__ = [
    'BaseWhatsAppProvider', 'WhatsAppSendError', 'MetaCloudProvider',
    'TwilioProvider', 'UnofficialGroupProvider', 'get_provider', 'PROVIDERS',
]
