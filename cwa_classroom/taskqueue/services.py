import logging
from decimal import Decimal, ROUND_HALF_UP

import django_rq
from django.conf import settings
from django.utils import timezone

from taskqueue.models import AIUsageLog, BackgroundTask

logger = logging.getLogger(__name__)

# Claude Opus 4.8 list pricing, USD per 1M tokens — matches the model both AI
# pipelines actually run (AI_IMPORT_MODEL / WORKSHEET_MODEL default to
# claude-opus-4-8). Overridable via CLAUDE_INPUT_COST_PER_MTOK /
# CLAUDE_OUTPUT_COST_PER_MTOK so the ledger stays accurate if the model or
# pricing changes without a code deploy. (Was $3/$15 Sonnet 4 — understated true
# cost ~1.67x while the pipelines ran on Opus.)
_DEFAULT_INPUT_COST_PER_MTOK = 5.0
_DEFAULT_OUTPUT_COST_PER_MTOK = 25.0
_MILLION = Decimal(1_000_000)


def estimate_cost_usd(input_tokens, output_tokens):
    """Estimate the USD cost of a Claude call from its token counts."""
    in_rate = Decimal(str(getattr(
        settings, 'CLAUDE_INPUT_COST_PER_MTOK', _DEFAULT_INPUT_COST_PER_MTOK)))
    out_rate = Decimal(str(getattr(
        settings, 'CLAUDE_OUTPUT_COST_PER_MTOK', _DEFAULT_OUTPUT_COST_PER_MTOK)))
    cost = (Decimal(int(input_tokens or 0)) / _MILLION) * in_rate \
        + (Decimal(int(output_tokens or 0)) / _MILLION) * out_rate
    return cost.quantize(Decimal('0.00001'), rounding=ROUND_HALF_UP)


def record_ai_usage(*, school, source, session_id, pages, usage):
    """Record one AI classification run in the usage/cost ledger.

    ``usage`` is the dict returned by the classifier — expects ``input_tokens``
    and ``output_tokens``. Never raises into the caller: usage accounting must
    not be able to fail a PDF that already classified successfully.
    """
    try:
        usage = usage or {}
        input_tokens = usage.get('input_tokens', 0) or 0
        output_tokens = usage.get('output_tokens', 0) or 0
        log = AIUsageLog.objects.create(
            school=school,
            source=source,
            session_id=session_id,
            pages=pages or 0,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            est_cost_usd=estimate_cost_usd(input_tokens, output_tokens),
        )
        # Per-call cost line — reuses values already in hand, so it's
        # effectively free (no extra process / query). Shows up in the worker
        # log after every AI call: `journalctl -u cwa-rqworker-test`.
        logger.info(
            'AI usage: source=%s session=%s pages=%s in=%s out=%s '
            'cost=$%.5f ($%.4f/page)',
            source, session_id, log.pages, log.input_tokens, log.output_tokens,
            log.est_cost_usd, float(log.cost_per_page_usd or 0),
        )
    except Exception:
        logger.exception(
            'Failed to record AI usage (source=%s session=%s)', source, session_id)
        return None

    # Refresh the live GitHub dashboard with the new total. Best-effort and
    # already swallows its own errors — but guard anyway so a GitHub hiccup can
    # never fail an AI call that already succeeded.
    try:
        from taskqueue.dashboard import update_dashboard_issue
        update_dashboard_issue()
    except Exception:
        logger.exception('AI dashboard refresh raised (non-fatal)')
    return log


def enqueue_task(*, school, user, task_type, func, args=None, kwargs=None,
                 queue='default', job_timeout=600):
    """Enqueue a background task.

    ``job_timeout`` (seconds) bounds how long RQ lets the work-horse run before
    it kills it. Defaults to 10 minutes because AI PDF classification of large
    documents routinely exceeds RQ's 180s default — too-short a timeout shows up
    as 'killed horse pid' / 'Work-horse terminated unexpectedly' in the worker log.
    """
    queue_instance = django_rq.get_queue(queue)
    # Separate RQ meta-params from the task function's kwargs to prevent
    # callers from accidentally overriding our tracking callbacks / timeout.
    rq_params = {
        'on_success': on_task_success,
        'on_failure': on_task_failure,
        'job_timeout': job_timeout,
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
        task_type, job.id, task.pk, school.pk if school else None, user.pk,
    )
    return task, job


def on_task_success(job, connection, result, *args, **kwargs):
    _update_task(job.id, BackgroundTask.DONE, result_data=result)


def on_task_failure(job, connection, exc_type, exc_value, traceback):
    error_msg = f'{exc_type.__name__}: {exc_value}' if exc_type else 'Unknown error'
    task = _update_task(job.id, BackgroundTask.FAILED, error_message=error_msg)

    if task and task.retry_count < BackgroundTask.MAX_RETRIES:
        # Requeue first; only mark the task as retrying if it actually worked.
        # RQ 2.x raises InvalidJobOperation if the job can't be requeued from the
        # failure callback — in that case leave the task FAILED rather than
        # stranding it in PENDING (and don't let the error escape the callback).
        try:
            job.requeue()
        except Exception as exc:
            logger.warning(
                'Could not requeue job=%s for retry; leaving it failed: %s',
                job.id, exc,
            )
            return
        task.retry_count += 1
        task.status = BackgroundTask.PENDING
        task.error_message = ''
        task.completed_at = None
        task.save(update_fields=['retry_count', 'status', 'error_message', 'completed_at'])
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
