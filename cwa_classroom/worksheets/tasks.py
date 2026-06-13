"""
Background tasks for Worksheets PDF upload (CPP-327).

Mirrors ai_import.tasks — runs in an RQ worker process, loads everything from
the DB via the session id, and flips the session status when done.
"""
import logging

from .services import extract_and_classify_worksheet

logger = logging.getLogger(__name__)


def process_worksheet_pdf(session_id):
    """Extract + classify a previously-uploaded worksheet PDF.

    Reads the persisted PDF from the session's FileField, runs the worksheet
    extraction/classification pipeline, writes the result back to the session,
    and flips status PROCESSING → READY (or FAILED on error).
    """
    from classroom.models import Level, Topic

    from .models import WorksheetUploadSession

    session = WorksheetUploadSession.objects.get(pk=session_id)
    try:
        if not session.pdf_file:
            raise ValueError('Session has no stored PDF file to process.')

        existing_topics = list(Topic.objects.filter(
            subject__slug='mathematics',
        ).values('name', 'slug')[:100])
        existing_levels = list(Level.objects.filter(
            level_number__lte=12,
        ).values('level_number', 'display_name'))

        # Re-open the persisted upload from storage (S3 / local).
        session.pdf_file.open('rb')
        try:
            output = extract_and_classify_worksheet(
                session.pdf_file, existing_topics, existing_levels,
                shape_naming=session.shape_naming,
            )
        finally:
            session.pdf_file.close()

        result = output['result']
        session.extracted_data = result
        session.extracted_images = output['extracted_images']
        session.page_count = output['page_count']
        session.tokens_used = result.get('usage', {}).get('total_tokens', 0)
        session.status = WorksheetUploadSession.STATUS_READY
        session.error_message = ''
        session.save(update_fields=[
            'extracted_data', 'extracted_images', 'page_count',
            'tokens_used', 'status', 'error_message',
        ])

        from taskqueue.models import AIUsageLog
        from taskqueue.services import record_ai_usage
        record_ai_usage(
            school=session.school,
            source=AIUsageLog.SOURCE_WORKSHEET,
            session_id=session.pk,
            pages=output['page_count'],
            usage=result.get('usage', {}),
        )

        logger.info(
            'Worksheet session=%s processed: %s pages, %s questions',
            session_id, output['page_count'], len(result.get('questions', [])),
        )
        return {
            'session_id': session_id,
            'page_count': output['page_count'],
            'questions': len(result.get('questions', [])),
        }

    except Exception as exc:
        logger.exception('Worksheet session=%s failed: %s', session_id, exc)
        session.status = WorksheetUploadSession.STATUS_FAILED
        session.error_message = str(exc)
        session.save(update_fields=['status', 'error_message'])
        raise
