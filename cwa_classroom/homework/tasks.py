"""
Background tasks for homework PDF processing (CPP-307c).

Replaces the previous daemon-thread approach with durable RQ jobs that survive
gunicorn worker restarts. Runs in an RQ worker process.
"""
import logging
import time
from io import BytesIO

from django.utils import timezone

logger = logging.getLogger(__name__)

# Don't write a heartbeat row more often than this. Progress fires per rendered
# image, which on a big worksheet is hundreds of calls — throttling keeps the
# updates useful without turning them into a write storm. A second is plenty of
# resolution: the upload page only polls every three.
HEARTBEAT_MIN_INTERVAL_S = 1.0


def _progress_reporter(session_id):
    """Return a ``callable(message)`` that heartbeats onto the upload session.

    Writes are throttled and never raise into the pipeline: a failed heartbeat
    must not fail an extraction that is otherwise going fine. The timestamp is
    what lets the UI tell "still working" from "the worker died" — a work-horse
    killed by the OOM killer never runs its failure handler, so a stale
    heartbeat is the only evidence the job is gone.
    """
    from .models import HomeworkUploadSession

    state = {'last': 0.0}

    def report(message, force=False):
        now = time.monotonic()
        if not force and now - state['last'] < HEARTBEAT_MIN_INTERVAL_S:
            return
        state['last'] = now
        try:
            HomeworkUploadSession.objects.filter(pk=session_id).update(
                progress_message=str(message)[:200],
                progress_updated_at=timezone.now(),
            )
        except Exception:
            logger.warning('Heartbeat write failed for session=%s', session_id, exc_info=True)

    return report


def process_homework_pdf(session_id, existing_topics, existing_levels):
    """Extract + classify a homework PDF, updating the HomeworkUploadSession.

    Reads the persisted PDF from the session's FileField (set at upload time),
    runs worksheet extraction/classification, and flips the session status
    PROCESSING → DONE (or ERROR on failure). Reports progress onto the session
    as it goes so the polling page can show live status and detect a dead job.
    """
    from worksheets.services import extract_and_classify_worksheet

    from .models import HomeworkUploadSession

    session = HomeworkUploadSession.objects.get(pk=session_id)
    report = _progress_reporter(session_id)
    try:
        report('Fetching the uploaded PDF…', force=True)
        session.pdf_file.open('rb')
        try:
            pdf_io = BytesIO(session.pdf_file.read())
        finally:
            session.pdf_file.close()
        pdf_io.name = session.pdf_filename

        output = extract_and_classify_worksheet(
            pdf_io, existing_topics, existing_levels,
            shape_naming=session.shape_naming,
            progress=report,
        )
        result = output['result']

        report('Saving the extracted questions…', force=True)
        HomeworkUploadSession.objects.filter(pk=session_id).update(
            extracted_data=result,
            extracted_images=output['extracted_images'],
            page_count=output['page_count'],
            tokens_used=result.get('usage', {}).get('total_tokens', 0),
            status=HomeworkUploadSession.STATUS_DONE,
            progress_message='',
            progress_updated_at=timezone.now(),
        )

        from taskqueue.models import AIUsageLog
        from taskqueue.services import record_ai_usage
        record_ai_usage(
            school=session.school,
            source=AIUsageLog.SOURCE_HOMEWORK,
            session_id=session_id,
            pages=output['page_count'],
            usage=result.get('usage', {}),
        )

        logger.info(
            'Homework PDF session=%s processed: %s pages',
            session_id, output['page_count'],
        )
        return {
            'session_id': session_id,
            'page_count': output['page_count'],
        }
    except Exception as exc:
        logger.exception('Homework PDF session=%s failed: %s', session_id, exc)
        HomeworkUploadSession.objects.filter(pk=session_id).update(
            status=HomeworkUploadSession.STATUS_ERROR,
            error_message=str(exc),
            progress_message='',
            progress_updated_at=timezone.now(),
        )
        raise


def grade_submission_answers(submission_id, school_id=None):
    """Grade all pending-AI answers for a submission in a background worker (CPP-307d).

    Used when a submission has more pending AI answers than the inline threshold,
    so the student's request isn't blocked on several Claude calls.
    """
    from classroom.models import School

    from .models import HomeworkStudentAnswer, HomeworkSubmission
    from .views import grade_pending_answers

    submission = HomeworkSubmission.objects.get(pk=submission_id)
    school = School.objects.filter(pk=school_id).first() if school_id else None

    grade_pending_answers(submission, school)

    graded = submission.answers.filter(
        review_status=HomeworkStudentAnswer.REVIEW_AI_DONE,
    ).count()
    logger.info('Graded submission=%s (%s answers)', submission_id, graded)
    return {'submission_id': submission_id, 'graded': graded}
