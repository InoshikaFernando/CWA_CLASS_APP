from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse

from taskqueue.models import BackgroundTask

# Human-friendly labels for known task types.
TASK_TYPE_LABELS = {
    'ai_import_pdf': 'PDF question import',
    'homework_pdf': 'Homework PDF import',
    'ai_grade': 'AI grading',
}


def _task_link(task):
    """Best-effort deep link for a completed task, or None."""
    if task.status != BackgroundTask.DONE:
        return None
    data = task.result_data or {}
    session_id = data.get('session_id')
    if task.task_type == 'ai_import_pdf' and session_id:
        return reverse('ai_import:preview', args=[session_id])
    return None


@login_required
def notifications_dropdown(request):
    """HTMX partial: the current user's recent background tasks."""
    tasks = list(
        BackgroundTask.objects.filter(created_by=request.user)[:10]
    )
    items = []
    for t in tasks:
        items.append({
            'label': TASK_TYPE_LABELS.get(t.task_type, t.task_type.replace('_', ' ').title()),
            'status': t.status,
            'created_at': t.created_at,
            'error_message': t.error_message,
            'link': _task_link(t),
        })
    has_active = any(
        t.status in (BackgroundTask.PENDING, BackgroundTask.RUNNING) for t in tasks
    )
    return render(request, 'taskqueue/_notifications.html', {
        'items': items,
        'has_active': has_active,
    })
