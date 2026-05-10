import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string

logger = logging.getLogger(__name__)


def send_staff_welcome_email(
    user,
    plain_password,
    role_display,
    school,
    department=None,
    login_url=None,
):
    """
    Send a welcome email to a newly created staff member.

    Args:
        user: The CustomUser instance (must have first_name, last_name, email).
        plain_password: The password in plain text (only available at creation time).
        role_display: Human-readable role name, e.g. "Teacher", "Head of Department".
        school: The School instance.
        department: Optional Department instance (for HoD assignments).
        login_url: Optional full login URL. Defaults to SITE_URL + LOGIN_URL.
    """
    if not user.email:
        logger.warning(
            'Cannot send welcome email to user %s: no email address.', user.username
        )
        return

    if login_url is None:
        site_url = getattr(settings, 'SITE_URL', '').rstrip('/')
        login_path = getattr(settings, 'LOGIN_URL', '/accounts/login/')
        login_url = f'{site_url}{login_path}'

    from .email_service import _get_email_logo_url

    context = {
        'user': user,
        'full_name': user.get_full_name() or user.username,
        'email': user.email,
        'password': plain_password,
        'role_display': role_display,
        'school': school,
        'department': department,
        'login_url': login_url,
        'site_name': getattr(settings, 'SITE_NAME', 'Classroom'),
        'email_logo_url': _get_email_logo_url(school, department),
    }

    subject = f'Welcome to {school.name} — Your Account is Ready'

    text_body = render_to_string('emails/welcome_staff.txt', context)
    html_body = render_to_string('emails/welcome_staff.html', context)

    from_email = getattr(
        settings, 'DEFAULT_FROM_EMAIL', 'noreply@wizardslearninghub.co.nz'
    )

    from .email_service import resolve_cc_email
    cc = resolve_cc_email(school, department)

    try:
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=from_email,
            to=[user.email],
            cc=cc,
        )
        msg.attach_alternative(html_body, 'text/html')
        msg.send(fail_silently=True)
        logger.info(
            'Welcome email sent to %s (%s) at %s.',
            user.get_full_name(), role_display, school.name,
        )
        # Mark lifecycle fields so duplicate guards work correctly
        from django.utils import timezone
        update_fields = []
        if not user.welcome_email_sent:
            user.welcome_email_sent = timezone.now()
            update_fields.append('welcome_email_sent')
        if user.creation_method != 'institute':
            user.creation_method = 'institute'
            update_fields.append('creation_method')
        if update_fields:
            user.save(update_fields=update_fields)
    except Exception:
        logger.exception(
            'Failed to send welcome email to %s.', user.email,
        )
