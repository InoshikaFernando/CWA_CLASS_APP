import logging
import time

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.utils import timezone

logger = logging.getLogger(__name__)

BATCH_SIZE = 25
BATCH_PAUSE_SECONDS = 2


def _get_email_logo_url(school=None, department=None):
    """Resolve the logo URL for emails.

    Priority: department logo > school logo > default CWA logo.
    Returns an absolute URL suitable for use in email <img> tags.
    """
    site_url = getattr(settings, 'SITE_URL', '').rstrip('/')

    if department and department.logo:
        return f'{site_url}{department.logo.url}'
    if school and school.logo:
        return f'{site_url}{school.logo.url}'

    static_url = getattr(settings, 'STATIC_URL', '/static/')
    return f'{site_url}{static_url}images/logo.png'


def resolve_cc_email(school, department=None):
    """Return CC list using school's outgoing_email (with department override).

    Uses ``school.get_effective_settings()`` so that a department-level
    ``outgoing_email`` takes precedence over the school-level value.
    Returns a list with one email address, or an empty list.
    """
    if not school:
        return []
    eff = school.get_effective_settings(department)
    cc_email = eff.get('outgoing_email', '')
    return [cc_email] if cc_email else []


def send_templated_email(
    recipient_email,
    subject,
    template_name,
    context=None,
    recipient_user=None,
    notification_type='',
    campaign=None,
    fail_silently=True,
    school=None,
    department=None,
):
    """Send a single HTML email using a Django template."""
    from .models import EmailLog, EmailPreference

    # Check user preferences
    if recipient_user:
        pref = EmailPreference.objects.filter(user=recipient_user).first()
        if pref:
            if campaign and not pref.receive_campaigns:
                return False
            if not campaign and not pref.receive_transactional:
                return False

    # Build context
    site_url = getattr(settings, 'SITE_URL', '')
    ctx = {
        'site_name': 'Wizards Learning Hub',
        'site_url': site_url,
        'current_year': timezone.now().year,
        'recipient_name': '',
        'unsubscribe_url': '',
        'email_logo_url': _get_email_logo_url(school, department),
    }

    if recipient_user:
        ctx['recipient_name'] = (
            recipient_user.get_full_name() or recipient_user.username
        )
        pref, _ = EmailPreference.objects.get_or_create(user=recipient_user)
        ctx['unsubscribe_url'] = f'{site_url}/email/unsubscribe/{pref.unsubscribe_token}/'

    if context:
        ctx.update(context)

    html_content = render_to_string(template_name, ctx)
    text_content = strip_tags(html_content)
    from_email = getattr(
        settings, 'DEFAULT_FROM_EMAIL', 'noreply@wizardslearninghub.co.nz',
    )

    cc = resolve_cc_email(school, department)

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, [recipient_email], cc=cc)
        msg.attach_alternative(html_content, 'text/html')
        msg.send(fail_silently=False)

        EmailLog.objects.create(
            recipient=recipient_user,
            recipient_email=recipient_email,
            subject=subject,
            notification_type=notification_type,
            campaign=campaign,
            status='sent',
        )
        return True

    except Exception as e:
        logger.exception('Failed to send email to %s: %s', recipient_email, e)
        EmailLog.objects.create(
            recipient=recipient_user,
            recipient_email=recipient_email,
            subject=subject,
            notification_type=notification_type,
            campaign=campaign,
            status='failed',
            error_message=str(e),
        )
        if not fail_silently:
            raise
        return False


def send_notification_email(notification):
    """Send an email for a Notification that was just created."""
    TEMPLATE_MAP = {
        'enrollment_approved': 'email/transactional/enrollment_approved.html',
        'enrollment_rejected': 'email/transactional/enrollment_rejected.html',
        'enrollment_request': 'email/transactional/enrollment_request.html',
        'criteria_approval': 'email/transactional/criteria_notification.html',
        'criteria_approved': 'email/transactional/criteria_notification.html',
        'criteria_rejected': 'email/transactional/criteria_notification.html',
        'attendance': 'email/transactional/general_notification.html',
        'general': 'email/transactional/general_notification.html',
    }

    template = TEMPLATE_MAP.get(
        notification.notification_type,
        'email/transactional/general_notification.html',
    )
    user = notification.user

    if not user.email:
        return False

    return send_templated_email(
        recipient_email=user.email,
        subject=f'[Wizards Learning Hub] {notification.get_notification_type_display()}',
        template_name=template,
        context={
            'notification_message': notification.message,
            'notification_type': notification.notification_type,
            'notification_link': notification.link,
        },
        recipient_user=user,
        notification_type=notification.notification_type,
    )


def send_bulk_emails(campaign):
    """Send campaign emails to all resolved recipients with batching."""
    from accounts.models import CustomUser
    from .models import ClassStudent, SchoolStudent, SchoolTeacher

    recipients = _resolve_campaign_recipients(campaign)
    campaign.total_recipients = len(recipients)
    campaign.status = 'sending'
    campaign.save()

    sent = 0
    failed = 0

    for i, user in enumerate(recipients):
        if not user.email:
            failed += 1
            continue

        success = send_templated_email(
            recipient_email=user.email,
            subject=campaign.subject,
            template_name='email/campaign/newsletter.html',
            context={
                'campaign_name': campaign.name,
                'html_body': campaign.html_body,
            },
            recipient_user=user,
            campaign=campaign,
            school=campaign.school,
        )

        if success:
            sent += 1
        else:
            failed += 1

        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_PAUSE_SECONDS)

    campaign.sent_count = sent
    campaign.failed_count = failed
    campaign.status = 'sent' if failed < campaign.total_recipients else 'failed'
    campaign.sent_at = timezone.now()
    campaign.save()


def _resolve_campaign_recipients(campaign):
    """Resolve recipient_filter JSON into a list of CustomUser instances."""
    from accounts.models import CustomUser
    from .models import ClassStudent, SchoolStudent, SchoolTeacher

    filter_data = campaign.recipient_filter or {}
    user_ids = set()

    roles = filter_data.get('roles', [])
    if roles:
        if 'student' in roles:
            student_ids = SchoolStudent.objects.filter(
                school=campaign.school, is_active=True,
            ).values_list('student_id', flat=True)
            user_ids.update(student_ids)

        if 'teacher' in roles:
            teacher_ids = SchoolTeacher.objects.filter(
                school=campaign.school, is_active=True,
            ).values_list('teacher_id', flat=True)
            user_ids.update(teacher_ids)

    class_ids = filter_data.get('class_ids', [])
    if class_ids:
        student_ids = ClassStudent.objects.filter(
            classroom_id__in=class_ids, is_active=True,
        ).values_list('student_id', flat=True)
        user_ids.update(student_ids)

    individual_ids = filter_data.get('individual_ids', [])
    if individual_ids:
        user_ids.update(individual_ids)

    return list(
        CustomUser.objects.filter(id__in=user_ids, is_active=True)
        .exclude(email='')
    )


def send_school_publish_notifications(school):
    """Send notification emails to all students and teachers when a school is published.

    Updates notified_at on SchoolStudent and SchoolTeacher records.
    Returns dict with sent/failed counts.
    """
    from .models import SchoolStudent, SchoolTeacher

    now = timezone.now()
    sent = 0
    failed = 0

    # Notify students (who haven't been notified yet)
    school_students = SchoolStudent.objects.filter(
        school=school, is_active=True, notified_at__isnull=True,
    ).select_related('student')

    for i, ss in enumerate(school_students):
        user = ss.student
        if not user.email:
            failed += 1
            continue

        ctx = {
            'school_name': school.name,
            'role_display': 'Student',
        }
        # Include credentials if available (new user created during import)
        if ss.pending_password:
            ctx['credentials_username'] = user.username
            ctx['credentials_email'] = user.email
            ctx['credentials_password'] = ss.pending_password

        success = send_templated_email(
            recipient_email=user.email,
            subject=f'Welcome to {school.name}',
            template_name='email/transactional/school_published.html',
            context=ctx,
            recipient_user=user,
            notification_type='school_published',
            school=school,
        )

        if success:
            ss.notified_at = now
            ss.pending_password = ''  # Clear after sending
            ss.save(update_fields=['notified_at', 'pending_password'])
            sent += 1
        else:
            failed += 1

        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_PAUSE_SECONDS)

    # Notify teachers (who haven't been notified yet)
    school_teachers = SchoolTeacher.objects.filter(
        school=school, is_active=True, notified_at__isnull=True,
    ).select_related('teacher')

    for i, st in enumerate(school_teachers):
        user = st.teacher
        if not user.email:
            failed += 1
            continue

        ctx = {
            'school_name': school.name,
            'role_display': st.get_role_display(),
        }
        # Include credentials if available (new user created during import)
        if st.pending_password:
            ctx['credentials_username'] = user.username
            ctx['credentials_email'] = user.email
            ctx['credentials_password'] = st.pending_password

        success = send_templated_email(
            recipient_email=user.email,
            subject=f'Welcome to {school.name}',
            template_name='email/transactional/school_published.html',
            context=ctx,
            recipient_user=user,
            notification_type='school_published',
            school=school,
        )

        if success:
            st.notified_at = now
            st.pending_password = ''  # Clear after sending
            st.save(update_fields=['notified_at', 'pending_password'])
            sent += 1
        else:
            failed += 1

        if (i + 1) % BATCH_SIZE == 0:
            time.sleep(BATCH_PAUSE_SECONDS)

    return {'sent': sent, 'failed': failed}
