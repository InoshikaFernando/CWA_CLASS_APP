from abc import ABC, abstractmethod


class WhatsAppSendError(Exception):
    """Raised when a provider fails to accept a message.

    ``retriable`` distinguishes transient failures (network blip, 429, 5xx) —
    which the deliver task re-raises so RQ retries — from permanent ones
    (bad number, unapproved template) which are marked failed and not retried.
    """
    def __init__(self, message, *, code='', retriable=False):
        super().__init__(message)
        self.code = code
        self.retriable = retriable


class BaseWhatsAppProvider(ABC):
    """Interface every WhatsApp backend implements."""

    @abstractmethod
    def send_template(self, *, to, template_name, language_code, params):
        """Send an approved template message.

        ``to`` is an E.164 number, ``params`` the positional body params.
        Returns the provider message id (Meta ``wamid``). Raises
        ``WhatsAppSendError`` on failure.
        """
        raise NotImplementedError
