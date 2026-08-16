"""Measure PDF extraction over a corpus of real papers.

This is a bench, not a test suite: point it at real PDFs, get numbers, change
the extraction logic, run it again and see whether the numbers moved the right
way. It is deliberately NOT part of the pytest run — real papers are large,
gitignored, and (in --live mode) cost money — so nothing here fires on a daily
PR. See Runbooks/pdf-extraction-benchmark.md.

Two modes, because the two things worth measuring have very different costs:

* offline (default, free) — everything up to the AI call: page rendering, the
  page-role detectors, answer-key parsing, and the figure-cropping path driven
  by each page's real embedded images. This is where a bad PDF crashes the
  worker, so it is worth running on every logic change.
* live (--live, spends tokens) — the full pipeline, scored on the thing that
  actually matters: how often the AI's answer matches the paper's own answer
  key.
"""
import logging
import time
import traceback

logger = logging.getLogger(__name__)

# Metrics with a direction. Everything else (timings, sizes, page counts,
# pages_classified, skipped) is reported as 'changed': it moves with the machine
# or with the corpus, and skipping MORE pages is the improvement one release and
# the regression the next — that judgement is the reader's, not the bench's.
# A rise in `errors` is always a regression.
HIGHER_IS_BETTER = {
    'images_rendered',      # lost a figure = lost a question's picture
    'key_rows',             # answers recovered from the paper itself
    'questions',
    'answer_accuracy_pct',  # the headline: AI answers matching the paper's key
}
LOWER_IS_BETTER = {
    'ai_calls',             # what the paper costs to classify
    'tokens',
    'cost_usd',
}


def _pseudo_questions(doc, pages):
    """Questions standing in for the AI's output, from each page's real figures.

    The crop path is the expensive, crash-prone half of extraction and it does
    not need the AI to exercise: every embedded image on the page is a figure a
    question could point at, so treat each as one. Real content, real
    coordinates, no tokens.
    """
    import fitz

    questions = []
    for page in doc:
        page_num = page.number + 1
        rendered = next((p for p in pages if p['page_num'] == page_num), None)
        if not rendered:
            continue
        scale_x = rendered['screenshot_w'] / page.rect.width
        scale_y = rendered['screenshot_h'] / page.rect.height
        seen = set()
        for image in page.get_images(full=True):
            for rect in page.get_image_rects(image[0]):
                key = (round(rect.x0), round(rect.y0))
                if key in seen or rect.width < 20 or rect.height < 20:
                    continue
                seen.add(key)
                questions.append({
                    'has_image': True,
                    'page_num': page_num,
                    'image_bbox': [rect.x0 * scale_x, rect.y0 * scale_y,
                                   rect.x1 * scale_x, rect.y1 * scale_y],
                })
    return questions


def measure_offline(pdf_path):
    """Run everything up to the AI call over one PDF and report what happened."""
    import fitz

    from . import services
    from .answer_key import parse_answer_key

    result = {'mode': 'offline', 'errors': []}
    doc = None
    try:
        # Opening is inside the try: an unreadable paper is a result to report,
        # not a reason to abandon the rest of the corpus.
        doc = fitz.open(str(pdf_path))
        result['pages'] = len(doc)

        started = time.perf_counter()
        extracted = services.extract_worksheet_pages(doc)
        result['extract_s'] = round(time.perf_counter() - started, 2)
        result['screenshot_mb'] = round(
            sum(len(p['screenshot']) for p in extracted['pages']) / 1e6, 2)

        # Page roles: what would be sent to the AI, and what would be skipped.
        kept, skipped = services._split_question_pages(extracted['pages'])
        result['pages_classified'] = len(kept)
        result['skipped'] = [{'page': page['page_num'], 'reason': role}
                             for page, role in skipped]
        result['ai_calls'] = -(-len(kept) // services.WORKSHEET_CHUNK_SIZE)

        # Answers the paper itself supplies.
        rows = {}
        for page, role in skipped:
            if role == services.PAGE_ROLE_ANSWER_KEY:
                rows.update(parse_answer_key(page.get('text', '')))
        result['key_rows'] = len(rows)

        # The crop path — where a bad PDF takes the worker down with it.
        questions = _pseudo_questions(doc, extracted['pages'])
        result['figures_found'] = len(questions)
        started = time.perf_counter()
        _, images = services.render_question_images(
            doc, extracted, {'questions': questions})
        result['render_s'] = round(time.perf_counter() - started, 2)
        result['images_rendered'] = len(images)
        result['images_mb'] = round(sum(len(v) for v in images.values()) / 1e6, 2)
        result['largest_image_kb'] = round(
            max((len(v) for v in images.values()), default=0) / 1024)
    except Exception as exc:
        # A bench that dies on one paper should still report the rest.
        result['errors'].append(f'{type(exc).__name__}: {exc}')
        logger.debug('offline bench failed on %s\n%s', pdf_path, traceback.format_exc())
    finally:
        if doc is not None:
            doc.close()
    return result


def measure_live(pdf_path, existing_topics=None, existing_levels=None):
    """Run the real pipeline over one PDF, scored against its own answer key.

    Spends tokens. The headline number is answer_accuracy_pct: of the answers
    the paper's key supplies, how many the AI got right on its own.
    """
    from .services import extract_and_classify_worksheet

    result = {'mode': 'live', 'errors': []}
    started = time.perf_counter()
    try:
        with open(pdf_path, 'rb') as handle:
            output = extract_and_classify_worksheet(
                handle, existing_topics or [], existing_levels or [])
    except Exception as exc:
        result['errors'].append(f'{type(exc).__name__}: {exc}')
        result['total_s'] = round(time.perf_counter() - started, 2)
        logger.debug('live bench failed on %s\n%s', pdf_path, traceback.format_exc())
        return result

    result['total_s'] = round(time.perf_counter() - started, 2)
    classified = output['result']
    questions = classified.get('questions', [])
    result['pages'] = output['page_count']
    result['questions'] = len(questions)
    result['questions_with_image'] = sum(1 for q in questions if q.get('image_ref'))
    result['images_rendered'] = len(output['extracted_images'])
    result['needs_review'] = sum(1 for q in questions if q.get('needs_review'))
    result['skipped'] = classified.get('skipped_pages', [])
    result['pages_classified'] = output['page_count'] - len(result['skipped'])

    usage = classified.get('usage', {})
    result['tokens'] = usage.get('total_tokens', 0)
    from taskqueue.services import estimate_cost_usd
    result['cost_usd'] = float(estimate_cost_usd(
        usage.get('input_tokens', 0), usage.get('output_tokens', 0)))

    # The quality number. apply_answer_key already counted how often the AI
    # agreed with the paper, so scoring is free.
    key = classified.get('answer_key') or {}
    result['key_rows'] = key.get('rows_found', 0)
    scored = key.get('agreed', 0) + key.get('corrected', 0)
    result['answers_scored'] = scored
    result['answer_accuracy_pct'] = (
        round(key.get('agreed', 0) / scored * 100, 1) if scored else None)
    return result


def compare(baseline, current):
    """[(paper, metric, before, after, verdict)] for every metric that moved.

    verdict is 'better', 'worse' or 'changed' — 'changed' for metrics with no
    inherent direction (timings move with the machine, page counts don't move
    at all unless the corpus did).
    """
    rows = []
    for paper, after in sorted(current.items()):
        before = baseline.get(paper)
        if before is None:
            rows.append((paper, '(new paper)', None, None, 'changed'))
            continue
        for metric in sorted(set(before) | set(after)):
            old, new = before.get(metric), after.get(metric)
            if metric == 'errors':
                old, new = len(old or []), len(new or [])
                if old == new:
                    continue
                verdict = 'worse' if new > old else 'better'
            elif metric == 'skipped':
                old, new = len(old or []), len(new or [])
                if old == new:
                    continue
                verdict = 'changed'
            elif old == new or not isinstance(new, (int, float)) \
                    or not isinstance(old, (int, float)):
                continue
            elif metric in HIGHER_IS_BETTER:
                verdict = 'better' if new > old else 'worse'
            elif metric in LOWER_IS_BETTER:
                verdict = 'better' if new < old else 'worse'
            else:
                verdict = 'changed'
            rows.append((paper, metric, old, new, verdict))
    return rows
