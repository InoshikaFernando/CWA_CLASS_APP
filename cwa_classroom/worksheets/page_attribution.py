"""Pin every extracted question to the ABSOLUTE PDF page it came from.

Both PDF importers send the model a few pages per request — the homework /
worksheet upload four at a time (``WORKSHEET_CHUNK_SIZE``), the AI import
twenty (``AI_IMPORT_PAGE_CHUNK``) — and ask it to say which page each question
is on. The renderer then crops that question's figure from *that* page. Every
page is labelled with its real number in the prompt, but the model sometimes
answers with the page's POSITION IN THE REQUEST instead: page 7, sent as the
third screenshot of the chunk covering pages 5–8, comes back as ``page_num: 3``.
Trusted as an absolute number, that cropped the figure box from page 3 — a
Year 7 statistics question about a column graph arrived with a crop of a
student's handwritten notes from four pages earlier.

The requests already pin the field to the chunk's pages with a schema ``enum``,
so the model is steered to the right numbers in the first place. This module
is the deterministic backstop for when it still gets it wrong: a page number
that is not one of the pages in the request cannot be right, and when it is a
valid *position* in the request, the page at that position is what was meant.
"""
import copy
import logging

logger = logging.getLogger(__name__)


def _as_page(value):
    """``value`` as a positive int page number, else None. Booleans are not pages."""
    if isinstance(value, bool):
        return None
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _in_sequence(prev_page, page, next_page):
    """Whether ``page`` sits between its neighbours in reading order."""
    return ((prev_page is None or prev_page <= page)
            and (next_page is None or page <= next_page))


def resolve_page_number(value, chunk_pages):
    """Map one model-reported page number onto the chunk's absolute pages.

    ``chunk_pages`` is the ordered list of absolute page numbers that were in
    the request. Returns ``(page, how)`` where ``how`` is one of:

    - ``'kept'``     — already one of the chunk's pages;
    - ``'relative'`` — not one of them, but a valid 1-based position in the
      request, so the page at that position is returned;
    - ``'filled'``   — missing, but the request held a single page, so that is
      the only page it can be;
    - ``'unresolved'`` — missing or impossible (e.g. the paper's own printed
      page number); ``page`` is then None so no figure is cropped from a page
      the model never named.
    """
    order = [p for p in (_as_page(p) for p in chunk_pages) if p is not None]
    if not order:
        return _as_page(value), 'kept' if _as_page(value) else 'unresolved'
    page = _as_page(value)
    if page is None:
        if len(order) == 1:
            return order[0], 'filled'
        return None, 'unresolved'
    if page in order:
        return page, 'kept'
    if page <= len(order):
        return order[page - 1], 'relative'
    return None, 'unresolved'


def resolve_chunk_pages(questions, chunk_pages, field='page_num',
                        figure_field=None):
    """Normalise the page numbers on one request's questions, in place.

    ``field`` is the question's own page (``page_num`` for the worksheet
    importer, ``source_page`` for the AI import); ``figure_field`` is an
    optional second page field naming where a drawn figure lives
    (``image_page`` in the AI import), resolved the same way and then held to
    the question's own page — the importers only ever crop a figure from the
    page the question is on, so a figure page that only matches it under the
    positional reading takes that reading.

    After the per-value mapping, a second pass uses READING ORDER: the model
    lists questions in page order, so a page that is out of sequence with both
    its neighbours while its positional reading is in sequence was a position
    all along (page "3" between two page-6 questions in the chunk 3–6 meant the
    third page, 5). A question with no usable page inherits its neighbours'
    page when they agree, otherwise it is left without one.

    Returns a count dict ``{'kept', 'relative', 'filled', 'unresolved'}`` for
    the primary field so callers can log what was corrected.
    """
    order = [p for p in (_as_page(p) for p in chunk_pages) if p is not None]
    counts = {'kept': 0, 'relative': 0, 'filled': 0, 'unresolved': 0}
    rows = [q for q in questions if isinstance(q, dict)]

    for q in rows:
        page, how = resolve_page_number(q.get(field), order)
        counts[how] += 1
        q[field] = page

    # Reading-order pass on the primary field.
    for idx, q in enumerate(rows):
        page = q.get(field)
        prev_page = next((r.get(field) for r in reversed(rows[:idx])
                          if r.get(field) is not None), None)
        next_page = next((r.get(field) for r in rows[idx + 1:]
                          if r.get(field) is not None), None)
        if page is None:
            if prev_page is not None and prev_page == next_page:
                q[field] = prev_page
                counts['unresolved'] -= 1
                counts['filled'] += 1
            continue
        neighbours_consistent = (prev_page is None or next_page is None
                                 or prev_page <= next_page)
        if not neighbours_consistent or _in_sequence(prev_page, page, next_page):
            continue
        # Out of sequence. Does reading it as a position in the request fit?
        if order and page <= len(order):
            alt = order[page - 1]
            if alt != page and _in_sequence(prev_page, alt, next_page):
                q[field] = alt
                counts['kept'] -= 1
                counts['relative'] += 1

    if figure_field:
        for q in rows:
            raw = q.get(figure_field)
            if raw is None:
                continue
            own = q.get(field)
            page, _how = resolve_page_number(raw, order)
            raw_page = _as_page(raw)
            if (own is not None and page != own and raw_page is not None
                    and raw_page <= len(order) and order[raw_page - 1] == own):
                page = own       # only matches the question's page positionally
            q[figure_field] = page

    corrected = counts['relative'] + counts['filled']
    if corrected or counts['unresolved']:
        logger.warning(
            'Page attribution over pages %s: %s question(s) reported a position '
            'in the request rather than a page number (remapped), %s had no page '
            'and were filled in, %s left without a page.',
            order, counts['relative'], counts['filled'], counts['unresolved'])
    return counts


def pin_page_enum(tool, field_names, chunk_pages, nullable=()):
    """A copy of a classification ``tool`` whose page fields are pinned to
    ``chunk_pages`` with an ``enum``, so the model is asked for one of the real
    page numbers rather than free to answer with a position in the request.

    ``field_names`` are keys under ``input_schema.properties.questions.items.
    properties``; those also in ``nullable`` (a figure page that is legitimately
    absent on a text-only question) keep ``null`` as an allowed value. The
    stored constant is never mutated — each request gets its own copy — and a
    tool without that shape is returned unchanged.
    """
    order = [p for p in (_as_page(p) for p in chunk_pages) if p is not None]
    if not order:
        return tool
    pinned = copy.deepcopy(tool)
    try:
        props = (pinned['input_schema']['properties']['questions']
                 ['items']['properties'])
    except (KeyError, TypeError):
        return tool
    listed = ', '.join(str(p) for p in order)
    for name in field_names:
        spec = props.get(name)
        if not isinstance(spec, dict):
            continue
        if name in nullable:
            spec['type'] = ['integer', 'null']
            spec['enum'] = list(order) + [None]
        else:
            spec['type'] = 'integer'
            spec['enum'] = list(order)
        spec['description'] = (
            (spec.get('description') or '').rstrip()
            + f' Must be one of the ABSOLUTE page numbers in this request — '
              f'{listed} — exactly as printed in the "[Page N …]" label under '
              f'each screenshot. It is NEVER the screenshot\'s position in '
              f'this request.'
        ).strip()
    return pinned
