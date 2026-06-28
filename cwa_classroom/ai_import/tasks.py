"""
Background tasks for AI Import (CPP-307b).

These run in an RQ worker process — keep them importable at module level and
self-contained (load everything from the DB via the session id).
"""
import logging

from .services import classify_questions, crop_figure_boxes, extract_pdf_content

logger = logging.getLogger(__name__)


def process_pdf_import(session_id):
    """Extract + classify a previously-uploaded PDF, storing results on the session.

    Runs in a background worker. Reads the persisted PDF from the session's
    FileField, runs PyMuPDF extraction + Claude classification, and writes the
    result back to the session, flipping status PROCESSING → READY (or FAILED).

    Returns a small dict summary (stored on the BackgroundTask.result_data).
    """
    from .models import AIImportSession

    session = AIImportSession.objects.get(pk=session_id)
    try:
        if not session.pdf_file:
            raise ValueError('Session has no stored PDF file to process.')

        # Re-open the persisted upload from storage (S3 / local). Read the bytes
        # once so they can feed both extraction and the high-DPI figure re-render.
        from io import BytesIO
        session.pdf_file.open('rb')
        try:
            pdf_bytes = session.pdf_file.read()
        finally:
            session.pdf_file.close()
        extracted = extract_pdf_content(BytesIO(pdf_bytes))

        from classroom.models import Level, Topic
        existing_topics = list(Topic.objects.filter(
            subject__slug='mathematics',
        ).values('name', 'slug')[:100])
        existing_levels = list(Level.objects.filter(
            level_number__lte=12,
        ).values('level_number', 'display_name'))

        result = classify_questions(extracted, existing_topics, existing_levels)

        # Collect embedded images keyed by ref.
        extracted_images = {}
        for page in extracted['pages']:
            for img in page['images']:
                extracted_images[img['ref']] = img['base64']

        # Crop drawn figures (shapes/diagrams with no embedded raster); rendered
        # straight from the PDF vectors at high DPI when possible. These join the
        # image pool and save like any other.
        extracted_images.update(crop_figure_boxes(extracted, result, pdf_bytes=pdf_bytes))

        # Preserve any pre-set classroom selection stored at enqueue time.
        existing = session.extracted_data or {}
        if existing.get('classroom_id'):
            result['classroom_id'] = existing['classroom_id']

        session.extracted_data = result
        session.extracted_images = extracted_images
        session.page_count = extracted['page_count']
        session.tokens_used = result.get('usage', {}).get('total_tokens', 0)
        session.status = AIImportSession.STATUS_READY
        session.error_message = ''
        session.save(update_fields=[
            'extracted_data', 'extracted_images', 'page_count',
            'tokens_used', 'status', 'error_message',
        ])

        from taskqueue.models import AIUsageLog
        from taskqueue.services import record_ai_usage
        record_ai_usage(
            school=session.school,
            source=AIUsageLog.SOURCE_AI_IMPORT,
            session_id=session.pk,
            pages=extracted['page_count'],
            usage=result.get('usage', {}),
        )

        logger.info(
            'AI import session=%s processed: %s pages, %s questions',
            session_id, extracted['page_count'], len(result.get('questions', [])),
        )
        return {
            'session_id': session_id,
            'page_count': extracted['page_count'],
            'questions': len(result.get('questions', [])),
        }

    except Exception as exc:
        logger.exception('AI import session=%s failed: %s', session_id, exc)
        session.status = AIImportSession.STATUS_FAILED
        session.error_message = str(exc)
        session.save(update_fields=['status', 'error_message'])
        raise
