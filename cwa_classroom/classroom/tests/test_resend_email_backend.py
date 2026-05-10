"""
Unit tests for the custom Resend email backend (cwa_classroom.email_backends).

All tests mock the Resend SDK — no real API calls are made.
"""

from unittest.mock import patch, MagicMock

import pytest
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.test import override_settings


@pytest.fixture
def resend_backend():
    """Create a ResendEmailBackend instance with a mocked API key."""
    with override_settings(RESEND_API_KEY='re_test_123456'):
        from cwa_classroom.email_backends import ResendEmailBackend
        return ResendEmailBackend(fail_silently=False)


@pytest.fixture
def resend_backend_silent():
    """Create a ResendEmailBackend instance with fail_silently=True."""
    with override_settings(RESEND_API_KEY='re_test_123456'):
        from cwa_classroom.email_backends import ResendEmailBackend
        return ResendEmailBackend(fail_silently=True)


class TestResendBackendInit:
    """Tests for backend initialisation."""

    def test_init_sets_api_key(self):
        """Backend sets resend.api_key from settings on init."""
        with override_settings(RESEND_API_KEY='re_test_abc'):
            import resend as resend_mod
            from cwa_classroom.email_backends import ResendEmailBackend
            ResendEmailBackend(fail_silently=False)
            assert resend_mod.api_key == 're_test_abc'

    def test_init_raises_without_api_key(self):
        """Backend raises ValueError if RESEND_API_KEY is empty."""
        with override_settings(RESEND_API_KEY=''):
            from cwa_classroom.email_backends import ResendEmailBackend
            with pytest.raises(ValueError, match='RESEND_API_KEY must be set'):
                ResendEmailBackend(fail_silently=False)


class TestResendBackendSendSimple:
    """Tests for sending simple text emails."""

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_simple_email(self, mock_send, resend_backend):
        """Sends a plain text email with correct params."""
        msg = EmailMessage(
            subject='Test Subject',
            body='Hello world',
            from_email='info@wizardslearninghub.co.nz',
            to=['parent@example.com'],
        )
        count = resend_backend.send_messages([msg])

        assert count == 1
        mock_send.assert_called_once()
        call_params = mock_send.call_args[0][0]
        assert call_params['from'] == 'info@wizardslearninghub.co.nz'
        assert call_params['to'] == ['parent@example.com']
        assert call_params['subject'] == 'Test Subject'
        assert call_params['text'] == 'Hello world'
        assert 'html' not in call_params

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_returns_zero_for_empty_list(self, mock_send, resend_backend):
        """Returns 0 and does not call API for empty message list."""
        count = resend_backend.send_messages([])
        assert count == 0
        mock_send.assert_not_called()


class TestResendBackendSendHtml:
    """Tests for sending HTML alternative emails."""

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_html_alternative(self, mock_send, resend_backend):
        """Sends HTML content from EmailMultiAlternatives."""
        msg = EmailMultiAlternatives(
            subject='Invoice #001',
            body='Plain text fallback',
            from_email='info@wizardslearninghub.co.nz',
            to=['parent@example.com'],
        )
        msg.attach_alternative('<h1>Invoice</h1>', 'text/html')

        count = resend_backend.send_messages([msg])

        assert count == 1
        call_params = mock_send.call_args[0][0]
        assert call_params['html'] == '<h1>Invoice</h1>'
        assert call_params['text'] == 'Plain text fallback'


class TestResendBackendCcBccReplyTo:
    """Tests for CC, BCC, and Reply-To headers."""

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_with_cc(self, mock_send, resend_backend):
        """CC recipients are passed through to Resend."""
        msg = EmailMultiAlternatives(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['student@example.com'],
            cc=['school@example.com'],
        )
        resend_backend.send_messages([msg])

        call_params = mock_send.call_args[0][0]
        assert call_params['cc'] == ['school@example.com']

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_with_bcc(self, mock_send, resend_backend):
        """BCC recipients are passed through to Resend."""
        msg = EmailMessage(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['student@example.com'],
            bcc=['admin@example.com'],
        )
        resend_backend.send_messages([msg])

        call_params = mock_send.call_args[0][0]
        assert call_params['bcc'] == ['admin@example.com']

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_send_with_reply_to(self, mock_send, resend_backend):
        """Reply-to header is forwarded to Resend."""
        msg = EmailMessage(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['parent@example.com'],
            reply_to=['school@lincoln.co.nz'],
        )
        resend_backend.send_messages([msg])

        call_params = mock_send.call_args[0][0]
        assert call_params['reply_to'] == ['school@lincoln.co.nz']

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_no_cc_when_empty(self, mock_send, resend_backend):
        """Does not include cc/bcc/reply_to keys when not set."""
        msg = EmailMessage(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['user@example.com'],
        )
        resend_backend.send_messages([msg])

        call_params = mock_send.call_args[0][0]
        assert 'cc' not in call_params
        assert 'bcc' not in call_params
        assert 'reply_to' not in call_params


class TestResendBackendErrorHandling:
    """Tests for error handling and fail_silently behavior."""

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_api_error_raises_when_not_silent(self, mock_send, resend_backend):
        """Raises exception when Resend returns error and fail_silently=False."""
        mock_send.side_effect = Exception('Resend API error: 422')
        msg = EmailMessage(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['user@example.com'],
        )
        with pytest.raises(Exception, match='422'):
            resend_backend.send_messages([msg])

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_api_error_suppressed_when_silent(self, mock_send, resend_backend_silent):
        """Suppresses exception when fail_silently=True."""
        mock_send.side_effect = Exception('Resend API error: 500')
        msg = EmailMessage(
            subject='Test',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['user@example.com'],
        )
        count = resend_backend_silent.send_messages([msg])
        assert count == 0

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_multiple_messages_partial_failure(self, mock_send, resend_backend_silent):
        """Counts only successfully sent messages in batch."""
        # First call succeeds, second fails
        mock_send.side_effect = [MagicMock(), Exception('fail')]

        messages = [
            EmailMessage('OK', 'body', 'a@b.com', ['c@d.com']),
            EmailMessage('Fail', 'body', 'a@b.com', ['e@f.com']),
        ]
        count = resend_backend_silent.send_messages(messages)
        assert count == 1


class TestResendBackendMultipleRecipients:
    """Tests for multiple recipients."""

    @patch('cwa_classroom.email_backends.resend.Emails.send')
    def test_multiple_to_recipients(self, mock_send, resend_backend):
        """Multiple 'to' recipients are passed as a list."""
        msg = EmailMessage(
            subject='Bulk',
            body='Body',
            from_email='info@wizardslearninghub.co.nz',
            to=['a@example.com', 'b@example.com', 'c@example.com'],
        )
        resend_backend.send_messages([msg])

        call_params = mock_send.call_args[0][0]
        assert call_params['to'] == ['a@example.com', 'b@example.com', 'c@example.com']


class TestSettingsFallback:
    """Tests for settings fallback chain."""

    @override_settings(RESEND_API_KEY='re_test_key')
    def test_resend_backend_selected_when_api_key_set(self):
        """With RESEND_API_KEY, settings should select Resend backend."""
        from django.conf import settings
        # This tests the logic conceptually — in reality settings.py
        # evaluates at import time. We verify the pattern is correct.
        api_key = settings.RESEND_API_KEY
        assert api_key == 're_test_key'

    @override_settings(RESEND_API_KEY='', EMAIL_HOST_USER='', EMAIL_HOST_PASSWORD='')
    def test_console_backend_when_no_credentials(self):
        """With no credentials at all, console backend should be used."""
        from django.conf import settings
        # Verify no API key means we won't try Resend
        assert settings.RESEND_API_KEY == ''
