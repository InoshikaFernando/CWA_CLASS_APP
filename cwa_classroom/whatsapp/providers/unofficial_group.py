"""Unofficial group-posting backend — placeholder, DO NOT ENABLE without review.

The official WhatsApp Business API (Meta Cloud / Twilio) CANNOT post to a real
WhatsApp group. Group posting is only possible by automating a logged-in
WhatsApp account (whatsapp-web.js / Baileys), which VIOLATES WhatsApp's Terms of
Service and risks the number being banned. This slot exists only so a future
opt-in implementation has a home; it is intentionally not implemented.
"""
from .base import BaseWhatsAppProvider, WhatsAppSendError


class UnofficialGroupProvider(BaseWhatsAppProvider):
    def send_template(self, *, to, template_name, language_code, params):
        raise WhatsAppSendError(
            'Unofficial group backend is not implemented (ToS-violating; '
            'requires explicit opt-in before building)', code='not_implemented')
