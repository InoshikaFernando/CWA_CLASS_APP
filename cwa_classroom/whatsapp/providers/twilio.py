"""Twilio WhatsApp backend — placeholder.

Occupies the provider interface so the codebase can switch to Twilio via
``WHATSAPP_PROVIDER=twilio`` later (e.g. to use its sandbox/tooling) without
changing call sites. Not implemented in this epic.
"""
from .base import BaseWhatsAppProvider, WhatsAppSendError


class TwilioProvider(BaseWhatsAppProvider):
    def send_template(self, *, to, template_name, language_code, params):
        raise WhatsAppSendError(
            'Twilio WhatsApp backend is not implemented', code='not_implemented')
