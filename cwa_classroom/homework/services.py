"""
homework/services.py
=====================
Shared homework side effects, kept out of views so the scheduled-publish
management command and the model's ``publish()`` can reuse them without
importing view code.
"""

from django.urls import reverse

from classroom.models import ClassStudent
from classroom.notifications import create_notification


def notify_students_homework_published(homework):
    """Notify every active student in the class that homework is now live.

    Creates an in-app notification and (via ``create_notification``) an email
    for each active ``ClassStudent``. Used by the immediate-publish path in
    ``HomeworkCreateView``, the manual "Publish now" view, and the
    ``publish_scheduled_homework`` cron command — i.e. whenever homework
    transitions to published, never at mere creation of a scheduled item.
    """
    homework_url = reverse('homework:student_take', kwargs={'homework_id': homework.id})
    due_str = homework.due_date.strftime('%d %b %Y') if homework.due_date else 'no deadline'
    active_students = (
        ClassStudent.objects
        .filter(classroom=homework.classroom, is_active=True)
        .select_related('student')
    )
    for cs in active_students:
        create_notification(
            user=cs.student,
            message=(
                f'New homework "{homework.title}" has been assigned in '
                f'{homework.classroom.name}. Due: {due_str}.'
            ),
            notification_type='homework_assigned',
            link=homework_url,
        )
