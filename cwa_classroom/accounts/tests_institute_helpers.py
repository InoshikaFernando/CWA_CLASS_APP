"""Helpers for tests that need a fully registered institute.

Registration no longer creates anything until Stripe confirms the card, so a
test that wants a real school has to finish the checkout too. These wrap that
two-step dance so the tests can go on asserting what they were written to
assert — that Silver gives you a Silver subscription, that company fields are
saved — without each one re-deriving the Stripe plumbing.

No test functions live here; it is imported by tests in several apps.
"""
from datetime import timedelta
from unittest.mock import MagicMock, patch

from django.utils import timezone


def stripe_checkout_session(session_id='cs_test_signup',
                            url='https://checkout.stripe.com/c/pay/test'):
    session = MagicMock()
    session.id = session_id
    session.url = url
    return session


def register_institute(client, url, data, session_id=None):
    """POST the signup form with Stripe stubbed. Creates NO account.

    Returns ``(response, session_id)``. After this the details live in a
    ``PendingInstituteRegistration`` and nothing else exists — which is the
    behaviour under test in ``tests_institute_card_first.py``.
    """
    session_id = session_id or f"cs_test_{data.get('username', 'signup')}"
    session = stripe_checkout_session(session_id=session_id)
    with patch('billing.stripe_service.create_pending_institute_checkout_session',
               return_value=session):
        resp = client.post(url, data)
    return resp, session_id


def complete_checkout(session_id, trial_days=14, subscription_id=None,
                      customer_id='cus_test_signup'):
    """Run the webhook Stripe would send once the card is accepted."""
    from billing.webhook_handlers import handle_checkout_completed

    trial_end = timezone.now() + timedelta(days=trial_days)
    subscription_id = subscription_id or f'sub_{session_id}'
    with patch('billing.webhook_handlers._stripe_trial_end',
               return_value=trial_end), \
            patch('stripe.Subscription.modify'):
        handle_checkout_completed({'object': {
            'id': session_id,
            'metadata': {'type': 'pending_institute_registration'},
            'subscription': subscription_id,
            'customer': customer_id,
        }})
    return trial_end


def register_and_pay(client, url, data, trial_days=14):
    """Register an institute AND complete its checkout — a real, live school.

    The equivalent of what a bare POST used to do before the card was required.
    """
    resp, session_id = register_institute(client, url, data)
    complete_checkout(session_id, trial_days=trial_days)
    return resp
