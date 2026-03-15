from .models import Notification


def create_notification(user, message, notification_type='general', link='', send_email=True):
    """
    Create an in-app notification and optionally send an email.
    Drop-in replacement for Notification.objects.create() calls.
    """
    notification = Notification.objects.create(
        user=user,
        message=message,
        notification_type=notification_type,
        link=link,
    )

    if send_email:
        from .email_service import send_notification_email
        try:
            send_notification_email(notification)
        except Exception:
            pass  # Already logged inside send_notification_email

    return notification
