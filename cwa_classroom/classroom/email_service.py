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


def send_templated_email(
    recipient_email,
    subject,
    template_name,
    context=None,
    recipient_user=None,
    notification_type='',
    campaign=None,
    fail_silently=True,
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

    try:
        msg = EmailMultiAlternatives(subject, text_content, from_email, [recipient_email])
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
