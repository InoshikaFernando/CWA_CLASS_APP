"""
Email notification utilities for subscription lifecycle events.
"""
import logging

from django.conf import settings
from django.core.mail import send_mail
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)

SITE_NAME = getattr(settings, 'SITE_NAME', 'Wizards Learning Hub')
DEFAULT_FROM = getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@wizardslearninghub.co.nz')


def notify_payment_failed(school=None, user=None, detail=None):
    """Send payment failure notification to the school admin or individual user."""
    from classroom.email_service import _get_email_logo_url

    detail = detail or {}
    recipient = None
    context = {'site_name': SITE_NAME, 'detail': detail, 'email_logo_url': _get_email_logo_url(school)}

    if school and school.admin and school.admin.email:
        recipient = school.admin.email
        context['name'] = school.admin.get_full_name() or school.admin.username
        context['school'] = school
    elif user and user.email:
        recipient = user.email
        context['name'] = user.get_full_name() or user.username

    if not recipient:
        logger.warning('No recipient for payment failure notification')
        return

    try:
        send_mail(
            subject=f'[{SITE_NAME}] Payment failed — action required',
            message=render_to_string('emails/payment_failed.txt', context),
            from_email=DEFAULT_FROM,
            recipient_list=[recipient],
            html_message=render_to_string('emails/payment_failed.html', context),
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send payment failure email to %s', recipient)


def notify_subscription_cancelled(school=None, user=None):
    """Send cancellation confirmation email."""
    from classroom.email_service import _get_email_logo_url

    recipient = None
    context = {'site_name': SITE_NAME, 'email_logo_url': _get_email_logo_url(school)}

    if school and school.admin and school.admin.email:
        recipient = school.admin.email
        context['name'] = school.admin.get_full_name() or school.admin.username
        context['school'] = school
    elif user and user.email:
        recipient = user.email
        context['name'] = user.get_full_name() or user.username

    if not recipient:
        return

    try:
        send_mail(
            subject=f'[{SITE_NAME}] Subscription cancelled',
            message=render_to_string('emails/subscription_cancelled.txt', context),
            from_email=DEFAULT_FROM,
            recipient_list=[recipient],
            html_message=render_to_string('emails/subscription_cancelled.html', context),
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send cancellation email to %s', recipient)


def notify_trial_expiring(school, days_remaining):
    """Send trial expiry warning email to the school admin."""
    from classroom.email_service import _get_email_logo_url

    if not school.admin or not school.admin.email:
        return

    context = {
        'site_name': SITE_NAME,
        'name': school.admin.get_full_name() or school.admin.username,
        'school': school,
        'days_remaining': days_remaining,
        'email_logo_url': _get_email_logo_url(school),
    }

    try:
        send_mail(
            subject=f'[{SITE_NAME}] Your trial expires in {days_remaining} day{"s" if days_remaining != 1 else ""}',
            message=render_to_string('emails/trial_expiring.txt', context),
            from_email=DEFAULT_FROM,
            recipient_list=[school.admin.email],
            html_message=render_to_string('emails/trial_expiring.html', context),
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send trial expiry email for school %s', school.name)


def notify_individual_trial_expiring(user, days_remaining, is_promo=False):
    """Send trial/promo expiry warning email to an individual student."""
    if not user.email:
        return

    label = 'promotion' if is_promo else 'trial'
    context = {
        'site_name': SITE_NAME,
        'name': user.get_full_name() or user.username,
        'days_remaining': days_remaining,
        'is_promo': is_promo,
        'label': label,
    }

    try:
        send_mail(
            subject=f'[{SITE_NAME}] Your {label} expires in {days_remaining} day{"s" if days_remaining != 1 else ""}',
            message=(
                f'Hi {context["name"]},\n\n'
                f'Your {label} access to {SITE_NAME} expires in {days_remaining} day{"s" if days_remaining != 1 else ""}.\n\n'
                f'Subscribe to a plan to continue using the platform.\n\n'
                f'Thanks,\n{SITE_NAME} Team'
            ),
            from_email=DEFAULT_FROM,
            recipient_list=[user.email],
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send %s expiry email for user %s', label, user.username)
