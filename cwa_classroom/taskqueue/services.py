import logging

import django_rq
from django.utils import timezone

from taskqueue.models import BackgroundTask

logger = logging.getLogger(__name__)


def enqueue_task(*, school, user, task_type, func, args=None, kwargs=None,
                 queue='default'):
    queue_instance = django_rq.get_queue(queue)
    # Separate RQ meta-params from the task function's kwargs to prevent
    # callers from accidentally overriding our tracking callbacks.
    rq_params = {
        'on_success': on_task_success,
        'on_failure': on_task_failure,
    }
    func_kwargs = {k: v for k, v in (kwargs or {}).items()
                   if k not in rq_params}
    job = queue_instance.enqueue(
        func,
        *(args or []),
        **func_kwargs,
        **rq_params,
    )
    task = BackgroundTask.objects.create(
        school=school,
        task_type=task_type,
        rq_job_id=job.id,
        created_by=user,
    )
    logger.info(
        'Enqueued %s job=%s task=%s school=%s user=%s',
        task_type, job.id, task.pk, school.pk, user.pk,
    )
    return task, job


def on_task_success(job, connection, result, *args, **kwargs):
    _update_task(job.id, BackgroundTask.DONE, result_data=result)


def on_task_failure(job, connection, exc_type, exc_value, traceback):
    error_msg = f'{exc_type.__name__}: {exc_value}' if exc_type else 'Unknown error'
    task = _update_task(job.id, BackgroundTask.FAILED, error_message=error_msg)

    if task and task.retry_count < BackgroundTask.MAX_RETRIES:
        task.retry_count += 1
        task.status = BackgroundTask.PENDING
        task.error_message = ''
        task.completed_at = None
        task.save(update_fields=['retry_count', 'status', 'error_message', 'completed_at'])
        job.requeue()
        logger.info(
            'Retrying task=%s job=%s attempt=%s/%s',
            task.pk, job.id, task.retry_count, BackgroundTask.MAX_RETRIES,
        )


def _update_task(rq_job_id, status, result_data=None, error_message=''):
    try:
        task = BackgroundTask.objects.get(rq_job_id=rq_job_id)
    except BackgroundTask.DoesNotExist:
        logger.warning('BackgroundTask not found for job=%s', rq_job_id)
        return None

    task.status = status
    task.completed_at = timezone.now()
    update_fields = ['status', 'completed_at']

    if result_data is not None:
        task.result_data = result_data
        update_fields.append('result_data')
    if error_message:
        task.error_message = error_message
        update_fields.append('error_message')

    task.save(update_fields=update_fields)
    logger.info('Task %s (job=%s) → %s', task.pk, rq_job_id, status)
    return task
