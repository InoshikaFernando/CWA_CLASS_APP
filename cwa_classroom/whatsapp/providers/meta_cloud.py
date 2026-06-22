"""Meta WhatsApp Cloud API backend (the primary, live provider).

Sends template messages through the Graph API. Inert until
``WHATSAPP_ACCESS_TOKEN`` and ``WHATSAPP_PHONE_NUMBER_ID`` are configured —
without them every send raises a non-retriable ``no_credentials`` error.
"""
import logging

import requests
from django.conf import settings

from .base import BaseWhatsAppProvider, WhatsAppSendError

logger = logging.getLogger(__name__)


class MetaCloudProvider(BaseWhatsAppProvider):
    def __init__(self, *, access_token=None, phone_number_id=None, graph_version=None):
        self.access_token = access_token if access_token is not None else getattr(
            settings, 'WHATSAPP_ACCESS_TOKEN', '')
        self.phone_number_id = phone_number_id if phone_number_id is not None else getattr(
            settings, 'WHATSAPP_PHONE_NUMBER_ID', '')
        self.graph_version = graph_version or getattr(
            settings, 'WHATSAPP_GRAPH_VERSION', 'v19.0')

    def send_template(self, *, to, template_name, language_code, params):
        if not self.access_token or not self.phone_number_id:
            raise WhatsAppSendError(
                'Meta Cloud API credentials not configured', code='no_credentials')

        url = (f'https://graph.facebook.com/{self.graph_version}'
               f'/{self.phone_number_id}/messages')
        components = []
        if params:
            components = [{
                'type': 'body',
                'parameters': [{'type': 'text', 'text': str(p)} for p in params],
            }]
        payload = {
            'messaging_product': 'whatsapp',
            'to': to,
            'type': 'template',
            'template': {
                'name': template_name,
                'language': {'code': language_code},
                'components': components,
            },
        }
        headers = {'Authorization': f'Bearer {self.access_token}'}

        try:
            resp = requests.post(url, json=payload, headers=headers, timeout=15)
        except requests.RequestException as exc:
            raise WhatsAppSendError(
                f'WhatsApp request failed: {exc}', code='network', retriable=True
            ) from exc

        if resp.status_code == 429 or resp.status_code >= 500:
            raise WhatsAppSendError(
                f'WhatsApp transient error {resp.status_code}: {resp.text}',
                code=str(resp.status_code), retriable=True)
        if resp.status_code >= 400:
            raise WhatsAppSendError(
                f'WhatsApp error {resp.status_code}: {resp.text}',
                code=str(resp.status_code))

        try:
            return resp.json()['messages'][0]['id']
        except (ValueError, KeyError, IndexError) as exc:
            raise WhatsAppSendError(
                f'Unexpected WhatsApp response: {resp.text}', code='bad_response'
            ) from exc
