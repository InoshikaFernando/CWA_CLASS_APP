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


def _parent_emails(user):
    """Addresses of the parents linked to *user*.

    A student's card is usually their parent's. Writing only to the student
    tells the child their payment failed and leaves the person who can fix it
    unaware — so parents are copied, not substituted: the student still needs
    to know why they are locked out.
    """
    if user is None:
        return []
    try:
        from classroom.models import ParentStudent
    except Exception:
        return []
    return [
        link.parent.email
        for link in ParentStudent.objects.filter(
            student=user, is_active=True).select_related('parent')
        if link.parent and link.parent.email
    ]


def notify_payment_failed(school=None, user=None, detail=None):
    """Tell whoever can fix it that a payment failed.

    Recipients are the school admin (for an institute plan) or the student AND
    their linked parents (for a student subscription).

    Reaching nobody is recorded as an audit event, not just a log line. It used
    to be ``logger.warning`` alone, and that is how 41 failed payments went
    unnoticed on production: an upstream lookup silently yielded no user, this
    function found no recipient, and the only trace was a warning in a log
    nobody reads. Six students sat locked out with no idea why.
    """
    from classroom.email_service import _get_email_logo_url

    detail = detail or {}
    recipients = []
    context = {'site_name': SITE_NAME, 'detail': detail, 'email_logo_url': _get_email_logo_url(school)}

    if school and school.admin and school.admin.email:
        recipients = [school.admin.email]
        context['name'] = school.admin.get_full_name() or school.admin.username
        context['school'] = school
    elif user:
        if user.email:
            recipients.append(user.email)
        # Deduplicated defensively only: CustomUser.email is unique and
        # ParentStudent is unique on (parent, student), so neither a shared
        # address nor a doubled link can actually occur today. Kept because a
        # family receiving the same warning twice reads as a second failure,
        # and that should not depend on a constraint two apps away.
        recipients += [e for e in _parent_emails(user) if e not in recipients]
        context['name'] = user.get_full_name() or user.username

    if not recipients:
        logger.warning('No recipient for payment failure notification')
        try:
            from audit.services import log_event
            log_event(
                user=user, school=school, category='billing',
                action='payment_failed_unreachable', result='blocked',
                detail={**detail,
                        'why': 'no email address for the payer',
                        'user': user.username if user else None,
                        'school': school.name if school else None},
            )
        except Exception:
            logger.exception('Could not record unreachable payment failure')
        return

    sent_to = list(dict.fromkeys(recipients))
    try:
        send_mail(
            subject=f'[{SITE_NAME}] Payment failed — action required',
            message=render_to_string('emails/payment_failed.txt', context),
            from_email=DEFAULT_FROM,
            recipient_list=sent_to,
            html_message=render_to_string('emails/payment_failed.html', context),
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send payment failure email to %s', recipients)
        return

    # Record the send, not just the failure to send. The dashboard panel and
    # the ops health tile both read "has this family been told" from this
    # event; without it every automated notice would look like silence and the
    # tile would sit red forever, which is the same as no tile at all.
    if user is not None:
        try:
            from audit.services import log_event
            log_event(
                user=user, school=school, category='billing',
                action='payment_failed_notice_sent', result='success',
                detail={**detail, 'recipients': sent_to, 'why': 'automatic'},
            )
        except Exception:
            logger.exception('Could not record payment failure notice')


def notify_past_due_backlog(user, since=None):
    """The catching-up notice, for a failure nobody was told about at the time.

    Separate from ``notify_payment_failed`` because the two arrive in different
    worlds and the automated one is right for its own job:

    * It says "to avoid any interruption to your service". By the time this
      message goes out the interruption has already happened, in one case for
      nearly a month, so that sentence reads as either stale or oblivious.
    * It greets ``{{ name }}``, which is the STUDENT's name — and the recipient
      list includes the parents, so a parent with two children past due would
      receive two red cards, one opening "Hi Randula" and one "Hi Hansi", both
      in the same inbox. This one greets nobody by name and names the student
      in the body instead, which is true for every recipient.
    * It says "log in" without saying WHOSE account. The billing portal reads
      ``request.user.subscription``, so a parent signing in to their own
      account gets "No billing account found" and a dead end. The subscription
      belongs to the student, and the message now says so.

    It does not apologise for the delay. Payment is the family's to keep up
    with, and an apology in the opening line reads as an offer to waive the
    charge rather than a request to settle it.
    """
    from classroom.email_service import _get_email_logo_url
    from django.conf import settings

    recipients = ([user.email] if user.email else [])
    recipients += [e for e in _parent_emails(user) if e not in recipients]
    if not recipients:
        logger.warning('No recipient for past-due backlog notice')
        return []

    full = user.get_full_name() or user.username
    context = {
        'site_name': SITE_NAME,
        'site_url': getattr(settings, 'SITE_URL', ''),
        'student_name': full,
        # "Randula can still sign in" reads better than the full name repeated.
        'first_name': user.first_name or full,
        'since': since,
        'email_logo_url': _get_email_logo_url(None),
    }
    try:
        send_mail(
            subject=f'[{SITE_NAME}] {full}\u2019s account is paused \u2014 payment needs updating',
            message=render_to_string('emails/payment_past_due_notice.txt', context),
            from_email=DEFAULT_FROM,
            recipient_list=list(dict.fromkeys(recipients)),
            html_message=render_to_string('emails/payment_past_due_notice.html', context),
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send past-due backlog notice to %s', recipients)
        return []
    return list(dict.fromkeys(recipients))


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


def send_discount_cleared_notification(student, school=None):
    """Notify a student (and their active linked parents) that their discount
    was removed by the institute and payment is now required on next login.

    Recipients with no email are skipped. Returns the list of addresses emailed.
    """
    from classroom.models import ParentStudent

    recipients = []
    if getattr(student, 'email', None):
        recipients.append(student.email)
    for link in ParentStudent.objects.filter(
        student=student, is_active=True,
    ).select_related('parent'):
        if link.parent and link.parent.email and link.parent.email not in recipients:
            recipients.append(link.parent.email)

    if not recipients:
        logger.warning('No recipient for discount-cleared notification (student %s)', student.pk)
        return []

    name = student.get_full_name() or student.username
    school_name = school.name if school else SITE_NAME
    body = (
        f'Hi,\n\n'
        f"The discount on {name}'s account at {school_name} has been removed.\n\n"
        f'On the next login, {name} will be asked to enter payment details and '
        f'subscribe at the standard rate to keep access.\n\n'
        f'If you believe this is a mistake, please contact your institute.\n\n'
        f'Thanks,\n{SITE_NAME} Team'
    )
    try:
        send_mail(
            subject=f'[{SITE_NAME}] Action required — payment now needed for {name}',
            message=body,
            from_email=DEFAULT_FROM,
            recipient_list=recipients,
            fail_silently=True,
        )
    except Exception:
        logger.exception('Failed to send discount-cleared email for student %s', student.pk)
    return recipients


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
