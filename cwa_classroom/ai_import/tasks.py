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

        # Collect embedded images keyed by ref, and the subset flagged at
        # extraction as decorative photos/illustrations (photo_like).
        extracted_images = {}
        photo_like_refs = set()
        for page in extracted['pages']:
            for img in page['images']:
                extracted_images[img['ref']] = img['base64']
                if img.get('photo_like'):
                    photo_like_refs.add(img['ref'])

        # Crop drawn figures (shapes/diagrams with no embedded raster); rendered
        # straight from the PDF vectors at high DPI when possible. These join the
        # image pool and save like any other.
        extracted_images.update(crop_figure_boxes(extracted, result, pdf_bytes=pdf_bytes))

        # Image checks, now that every question's image is finalised (embedded ref
        # or fresh crop). Three layers route a suspect attachment to the teacher via
        # needs_review, which the preview badge already renders:
        #   1. A deterministic page-locality guard — free, always on — flags any
        #      image whose ref page is far from the question's source_page (e.g. a
        #      page-1 decoration attached to a page-5 question).
        #   2. A deterministic missing-figure guard — free, always on — flags a
        #      question whose text points at a figure ("this shape", "the diagram")
        #      but that ended up with NO image, i.e. its figure was skipped.
        #   3. A deterministic photo-mismatch guard — free, always on — flags a
        #      question needing a drawn maths figure (perimeter, angle, coordinate
        #      grid) whose attached image was flagged photo_like at extraction, i.e.
        #      a decorative header/word-problem picture grabbed by mistake.
        #      These three run before the paid pass, sparing it a call on what they
        #      caught.
        #   4. The vision second opinion looks at each still-unflagged question with
        #      its attached image and flags mismatches the checks above can't see
        #      (a same-page wrong crop, art that isn't photo_like). Self-gating on
        #      OPENAI_API_KEY; never fails the import; reported apart from the
        #      Claude token ledger.
        #   5. A vision count re-check independently counts "count the squares"
        #      area/perimeter questions against their OWN grid crop and flags a
        #      count that disagrees with the imported answer. Also self-gating.
        from .verification import (
            flag_cross_page_images, flag_missing_figures,
            flag_photo_images_on_diagrams, image_verification_enabled,
            verify_counts, verify_images,
        )
        questions = result.get('questions', [])
        cross_page_flagged = flag_cross_page_images(questions)
        missing_figure_flagged = flag_missing_figures(questions)
        photo_mismatch_flagged = flag_photo_images_on_diagrams(
            questions, photo_like_refs)
        image_verification = verify_images(questions, extracted_images)
        # Always record an image-verification summary — no silent pass. When the
        # vision layer didn't run (no key / disabled / nothing left to check) say
        # so, and always report the deterministic guards' tallies.
        if image_verification is None:
            image_verification = {
                'status': ('disabled' if not image_verification_enabled()
                           else 'nothing_to_check'),
            }
        image_verification['cross_page_flagged'] = cross_page_flagged
        image_verification['missing_figure_flagged'] = missing_figure_flagged
        image_verification['photo_mismatch_flagged'] = photo_mismatch_flagged

        # Vision re-count of "count the squares" questions (own crop, not the full
        # page). Reported separately; kept out of the Claude token ledger.
        count_verification = verify_counts(questions, extracted_images)
        if count_verification is not None:
            result['count_verification'] = count_verification
        result['image_verification'] = image_verification

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
