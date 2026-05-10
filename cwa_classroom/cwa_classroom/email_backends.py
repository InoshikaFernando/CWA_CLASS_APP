"""
Custom Django email backend using Resend (resend.com).

Wraps the Resend Python SDK to integrate with Django's standard email
infrastructure (EmailMessage, EmailMultiAlternatives). All existing code
that uses Django's send_mail() or EmailMultiAlternatives works unchanged.

Usage:
    Set EMAIL_BACKEND = 'cwa_classroom.email_backends.ResendEmailBackend'
    and RESEND_API_KEY in your environment.
"""

import logging

import resend
from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend

logger = logging.getLogger(__name__)


class ResendEmailBackend(BaseEmailBackend):
    """Django email backend that sends via Resend's transactional email API."""

    def __init__(self, fail_silently=False, **kwargs):
        super().__init__(fail_silently=fail_silently, **kwargs)
        api_key = getattr(settings, 'RESEND_API_KEY', '')
        if not api_key:
            raise ValueError(
                'RESEND_API_KEY must be set in settings when using '
                'ResendEmailBackend.'
            )
        resend.api_key = api_key

    def send_messages(self, email_messages):
        """Send one or more EmailMessage objects via Resend. Returns count sent."""
        if not email_messages:
            return 0

        sent_count = 0
        for message in email_messages:
            try:
                self._send(message)
                sent_count += 1
            except Exception as e:
                logger.exception(
                    'Resend: failed to send email to %s: %s',
                    message.to, e,
                )
                if not self.fail_silently:
                    raise
        return sent_count

    def _send(self, message):
        """Send a single EmailMessage via Resend API."""
        params = {
            'from': message.from_email,
            'to': message.to,
            'subject': message.subject,
            'text': message.body,
        }

        # HTML alternative (from EmailMultiAlternatives.attach_alternative)
        for content, mimetype in getattr(message, 'alternatives', []):
            if mimetype == 'text/html':
                params['html'] = content
                break

        if message.cc:
            params['cc'] = message.cc

        if message.bcc:
            params['bcc'] = message.bcc

        if message.reply_to:
            params['reply_to'] = message.reply_to

        # File attachments (e.g. PDF invoices)
        if message.attachments:
            attachments = []
            for attachment in message.attachments:
                if isinstance(attachment, tuple):
                    filename, content, _ = attachment
                    attachments.append({
                        'filename': filename,
                        'content': list(content.encode() if isinstance(content, str) else content),
                    })
            if attachments:
                params['attachments'] = attachments

        # Custom headers (e.g. List-Unsubscribe)
        if message.extra_headers:
            params['headers'] = message.extra_headers

        resend.Emails.send(params)
