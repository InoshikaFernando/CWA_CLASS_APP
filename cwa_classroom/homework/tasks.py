"""
Background tasks for homework PDF processing (CPP-307c).

Replaces the previous daemon-thread approach with durable RQ jobs that survive
gunicorn worker restarts. Runs in an RQ worker process.
"""
import logging
from io import BytesIO

logger = logging.getLogger(__name__)


def process_homework_pdf(session_id, existing_topics, existing_levels):
    """Extract + classify a homework PDF, updating the HomeworkUploadSession.

    Reads the persisted PDF from the session's FileField (set at upload time),
    runs worksheet extraction/classification, and flips the session status
    PROCESSING → DONE (or ERROR on failure).
    """
    from worksheets.services import extract_and_classify_worksheet

    from .models import HomeworkUploadSession

    session = HomeworkUploadSession.objects.get(pk=session_id)
    try:
        session.pdf_file.open('rb')
        try:
            pdf_io = BytesIO(session.pdf_file.read())
        finally:
            session.pdf_file.close()
        pdf_io.name = session.pdf_filename

        output = extract_and_classify_worksheet(pdf_io, existing_topics, existing_levels)
        result = output['result']

        HomeworkUploadSession.objects.filter(pk=session_id).update(
            extracted_data=result,
            extracted_images=output['extracted_images'],
            page_count=output['page_count'],
            tokens_used=result.get('usage', {}).get('total_tokens', 0),
            status=HomeworkUploadSession.STATUS_DONE,
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
        )
        raise
