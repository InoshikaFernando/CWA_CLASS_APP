"""
notifications/services.py
=========================
Centralised lifecycle email notification service for Wizards Learning Hub.

Handles three transactional notification types:
  - welcome            : Sent once on account creation (institute vs self-registered variants)
  - email_changed      : Sent to the NEW address after a successful email update
  - password_changed   : Sent after a successful password change (no password included)

Usage
-----
From any view or service, after the relevant user action succeeds::

    from notifications.services import (
        send_welcome_notification,
        send_email_changed_notification,
        send_password_changed_notification,
    )

    # Self-registered user (no temp password):
    send_welcome_notification(user)

    # Institute-created user (include temp password, mark as institute-created):
    send_welcome_notification(user, plain_password='Tmp@1234', school=school)

    # After email update:
    send_email_changed_notification(user, new_email='new@example.com', school=school)

    # After password change:
    send_password_changed_notification(user, school=school)

All functions:
  - Resolve the institute CC email automatically if ``school`` is not supplied
  - Log success/failure via EmailLog (classroom.models)
  - Never raise exceptions — failures are logged and swallowed so user actions
    are never blocked by email delivery issues

Design notes
------------
- Reuses ``classroom.email_service.send_templated_email`` (logging, CC, preference
  checks, EmailLog) rather than sending raw emails here.
- ``must_change_password`` (existing field) doubles as the force-password-change
  flag for institute-created accounts; no separate field is needed.
- Template selection is role-driven: parent / teacher (inc. HoI/HoD) / student.
  Within each role, ``creation_method`` on the user selects the institute vs
  self-registered variant.
"""

import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Notification type constants (stored in EmailLog.notification_type)
# ---------------------------------------------------------------------------
NOTIF_WELCOME = 'welcome'
NOTIF_WELCOME_RESEND = 'welcome_resend'
NOTIF_EMAIL_CHANGED = 'email_changed'
NOTIF_PASSWORD_CHANGED = 'password_changed'
NOTIF_PAYMENT_REQUIRED = 'payment_required'

# ---------------------------------------------------------------------------
# Template paths
# ---------------------------------------------------------------------------
_WELCOME_TEMPLATES = {
    # (role_bucket, creation_method) → template path
    ('parent',   'institute'):       'email/lifecycle/welcome_parent_institute.html',
    ('parent',   'self_registered'): 'email/lifecycle/welcome_parent_self.html',
    ('teacher',  'institute'):       'email/lifecycle/welcome_teacher_institute.html',
    ('teacher',  'self_registered'): 'email/lifecycle/welcome_teacher_self.html',
    ('student',  'institute'):       'email/lifecycle/welcome_student_institute.html',
    ('student',  'self_registered'): 'email/lifecycle/welcome_student_self.html',
}

_TEMPLATE_EMAIL_CHANGED  = 'email/lifecycle/email_changed.html'
_TEMPLATE_PASSWORD_CHANGED = 'email/lifecycle/password_changed.html'
_TEMPLATE_PAYMENT_REQUIRED = 'email/lifecycle/payment_required.html'


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _role_bucket(user):
    """Classify user into parent / teacher / student for template selection."""
    from accounts.models import Role
    if user.has_role(Role.PARENT):
        return 'parent'
    if user.has_role(Role.STUDENT) or user.has_role(Role.INDIVIDUAL_STUDENT):
        return 'student'
    # Everyone else (HoI, HoD, Teacher, etc.) is treated as "teacher"
    return 'teacher'


def _resolve_school(user, school=None):
    """
    Return the School instance associated with ``user``.

    Precedence: explicitly supplied ``school`` arg > SchoolStudent FK >
    SchoolTeacher FK > School.admin FK (for HoI who created their own school).
    Returns None if no school can be found (e.g. individual student, parent
    not yet linked).
    """
    if school is not None:
        return school

    from classroom.models import SchoolStudent, SchoolTeacher, School

    ss = SchoolStudent.objects.filter(student=user, is_active=True).select_related('school').first()
    if ss:
        return ss.school

    st = SchoolTeacher.objects.filter(teacher=user, is_active=True).select_related('school').first()
    if st:
        return st.school

    # HoI who owns the school
    owned = School.objects.filter(admin=user).first()
    if owned:
        return owned

    return None


def _build_base_context(user, school):
    """Shared context variables injected into every lifecycle template."""
    from django.conf import settings
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
    login_path = getattr(settings, 'LOGIN_URL', '/accounts/login/')

    return {
        'user': user,
        'recipient_name': user.get_full_name() or user.username,
        'school_name': school.name if school else 'Wizards Learning Hub',
        'login_url': f'{site_url}{login_path}',
        'site_url': site_url,
        'change_datetime': timezone.now(),
    }


def _send(
    recipient_email,
    subject,
    template,
    context,
    user,
    school,
    notification_type,
):
    """
    Thin wrapper around ``classroom.email_service.send_templated_email``.

    Returns True on success, False on failure. Never raises.
    """
    try:
        from classroom.email_service import send_templated_email
        return send_templated_email(
            recipient_email=recipient_email,
            subject=subject,
            template_name=template,
            context=context,
            recipient_user=user,
            notification_type=notification_type,
            school=school,
            fail_silently=True,
        )
    except Exception:
        logger.exception(
            'Unexpected error sending %s notification to %s',
            notification_type, recipient_email,
        )
        return False


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _send_welcome_core(user, plain_password, school, notification_type):
    """
    Shared logic for sending welcome emails (first-send and resend).

    Builds the template context, sends the email, and updates
    ``welcome_email_sent`` on success. Returns True/False.
    """
    if not user.email:
        logger.warning('Cannot send welcome to user %s: no email address.', user.pk)
        return False

    resolved_school = _resolve_school(user, school)
    creation = user.creation_method or 'self_registered'
    bucket = _role_bucket(user)
    template = _WELCOME_TEMPLATES.get(
        (bucket, creation), _WELCOME_TEMPLATES[('teacher', 'self_registered')]
    )

    ctx = _build_base_context(user, resolved_school)
    ctx['is_institute_created'] = (creation == 'institute')
    ctx['role_display'] = {
        'parent':  'Parent',
        'student': 'Student',
        'teacher': 'Staff Member',
    }.get(bucket, 'Member')

    if plain_password and creation == 'institute':
        ctx['temp_password'] = plain_password
        ctx['username'] = user.username

    school_label = resolved_school.name if resolved_school else 'Wizards Learning Hub'
    subject = f'Welcome to {school_label} — Your Account is Ready'

    label = 'resend' if notification_type == NOTIF_WELCOME_RESEND else 'email'
    success = _send(
        recipient_email=user.email,
        subject=subject,
        template=template,
        context=ctx,
        user=user,
        school=resolved_school,
        notification_type=notification_type,
    )

    if success:
        user.welcome_email_sent = timezone.now()
        user.save(update_fields=['welcome_email_sent'])
        logger.info('Welcome %s sent to user %s (%s).', label, user.pk, user.email)
    else:
        logger.warning('Welcome %s FAILED for user %s (%s).', label, user.pk, user.email)

    return success


def send_welcome_notification(user, plain_password=None, school=None):
    """
    Send a role-appropriate welcome email to ``user``.

    Guards against duplicates: if ``user.welcome_email_sent`` is already set,
    the call is a no-op (returns False).

    Parameters
    ----------
    user : CustomUser
        The newly created user instance.
    plain_password : str | None
        The plaintext temporary password — only supplied for institute-created
        accounts (before hashing). Never include for self-registered users.
    school : School | None
        The institute the user belongs to. If None, auto-resolved from DB.
    """
    if user.welcome_email_sent:
        logger.debug(
            'Welcome email already sent to user %s on %s — skipping.',
            user.pk, user.welcome_email_sent,
        )
        return False

    return _send_welcome_core(user, plain_password, school, NOTIF_WELCOME)


def resend_welcome_notification(user, plain_password=None, school=None):
    """
    Force-send a welcome email, bypassing the duplicate-send guard.

    Used by the HoI "Resend Welcome Email" action. The caller has already
    confirmed intent and optionally reset the user's password for institute
    accounts. Updates ``welcome_email_sent`` to now on success.
    """
    return _send_welcome_core(user, plain_password, school, NOTIF_WELCOME_RESEND)


def send_email_changed_notification(user, new_email, school=None):
    """
    Notify the user that their email address was changed.

    Sends to ``new_email`` (the updated address) so the user can verify they
    received it. CC's the institute's outgoing email.

    Parameters
    ----------
    user : CustomUser
        The user whose email was just changed (already saved to DB with new email).
    new_email : str
        The new email address (same as ``user.email`` after save, but passed
        explicitly so callers don't need to refresh the instance).
    school : School | None
        Auto-resolved if not supplied.
    """
    if not new_email:
        logger.warning('send_email_changed_notification: new_email is empty for user %s.', user.pk)
        return False

    resolved_school = _resolve_school(user, school)
    ctx = _build_base_context(user, resolved_school)
    ctx['new_email'] = new_email

    school_label = resolved_school.name if resolved_school else 'Wizards Learning Hub'
    subject = f'[{school_label}] Your email address has been updated'

    success = _send(
        recipient_email=new_email,
        subject=subject,
        template=_TEMPLATE_EMAIL_CHANGED,
        context=ctx,
        user=user,
        school=resolved_school,
        notification_type=NOTIF_EMAIL_CHANGED,
    )

    if success:
        logger.info('Email-changed notification sent to %s for user %s.', new_email, user.pk)
    else:
        logger.warning('Email-changed notification FAILED for user %s.', user.pk)

    return success


def send_password_changed_notification(user, school=None):
    """
    Notify the user that their password was changed.

    Sends to the user's current email. Never includes the new password.

    Parameters
    ----------
    user : CustomUser
        The user whose password was just changed.
    school : School | None
        Auto-resolved if not supplied.
    """
    if not user.email:
        logger.warning(
            'send_password_changed_notification: no email for user %s.', user.pk
        )
        return False

    resolved_school = _resolve_school(user, school)
    ctx = _build_base_context(user, resolved_school)

    school_label = resolved_school.name if resolved_school else 'Wizards Learning Hub'
    subject = f'[{school_label}] Your password has been changed'

    success = _send(
        recipient_email=user.email,
        subject=subject,
        template=_TEMPLATE_PASSWORD_CHANGED,
        context=ctx,
        user=user,
        school=resolved_school,
        notification_type=NOTIF_PASSWORD_CHANGED,
    )

    if success:
        logger.info('Password-changed notification sent to user %s.', user.pk)
    else:
        logger.warning('Password-changed notification FAILED for user %s.', user.pk)

    return success


def send_payment_required_notification(
    user,
    school=None,
    *,
    plan_name='Wizard',
    monthly_price='19.90',
    discount_code='',
    discount_percent=0,
    discounted_price=None,
    currency_symbol='$',
    reset_url='',
    support_email='',
):
    """
    Notify a re-gated school student's guardian that they must add payment
    (and may apply a discount code) on their next login.

    Sent to ``user.email`` (the guardian's address for institute students).
    Never raises; returns True/False.

    Parameters
    ----------
    user : CustomUser
        The re-gated student account.
    school : School | None
        Auto-resolved if not supplied (used for branding + CC).
    plan_name, monthly_price, currency_symbol :
        Plan label and full price shown in the email.
    discount_code, discount_percent, discounted_price :
        The family's discount. ``discounted_price`` is computed from
        ``monthly_price`` and ``discount_percent`` if not supplied.
    reset_url, support_email :
        Optional links shown in the email.
    """
    if not user.email:
        logger.warning(
            'send_payment_required_notification: no email for user %s.', user.pk
        )
        return False

    resolved_school = _resolve_school(user, school)
    ctx = _build_base_context(user, resolved_school)

    if discounted_price is None and discount_percent:
        from decimal import Decimal, ROUND_HALF_UP
        net = Decimal(str(monthly_price)) * (Decimal(100 - discount_percent) / Decimal(100))
        discounted_price = str(net.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))

    ctx.update({
        'plan_name': plan_name,
        'monthly_price': monthly_price,
        'discount_code': discount_code,
        'discount_percent': discount_percent,
        'discounted_price': discounted_price or monthly_price,
        'currency_symbol': currency_symbol,
        'reset_url': reset_url,
        'support_email': support_email,
    })

    school_label = resolved_school.name if resolved_school else 'Wizards Learning Hub'
    subject = f'Action needed — activate your {school_label} subscription to keep access'

    success = _send(
        recipient_email=user.email,
        subject=subject,
        template=_TEMPLATE_PAYMENT_REQUIRED,
        context=ctx,
        user=user,
        school=resolved_school,
        notification_type=NOTIF_PAYMENT_REQUIRED,
    )

    if success:
        logger.info('Payment-required notification sent to user %s (%s).', user.pk, user.email)
    else:
        logger.warning('Payment-required notification FAILED for user %s (%s).', user.pk, user.email)

    return success
