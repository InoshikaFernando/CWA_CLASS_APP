"""Print-dialog style page selection for PDF question extraction.

Why this exists
---------------
Real papers carry pages that hold no questions. ``detect_page_role`` (see
``worksheets/services.py``) already catches the two machine-recognisable cases —
a bubble multiple-choice answer sheet, and an A–D answer key — but plenty of
front and back matter reads like ordinary prose to a detector: a cover page, an
instruction sheet, a formula sheet, a worked marking scheme. Those pages get
sent to the AI, cost the school quota, and come back as junk "questions" the
teacher has to untick.

So the teacher gets to say which pages to extract, using the same syntax as a
print dialog::

    (blank)     every page — the default
    all         every page, spelled out
    2-          page 2 to the end (skips a cover / instruction sheet)
    1-8         pages 1 to 8 (skips a marking scheme at the back)
    -8          same as 1-8
    2-7, 9, 11- mix ranges and single pages freely

Selected pages are the *only* ones rendered and sent to the AI, so an excluded
page costs nothing. Page numbers stay absolute throughout the pipeline (a
question found on page 7 is still stamped ``page_num: 7``), which is what lets
image bounding boxes and the "Adjust image" modal keep working on a partial
extraction.

This module is deliberately free of Django and PyMuPDF imports at module level
so the parser can be unit-tested on its own.
"""
import re

# Longest spec we accept, and the ``max_length`` of the model fields that store
# it. A real selection is a handful of ranges; anything longer is a paste
# accident, and we would rather say so than truncate it silently.
MAX_SPEC_LENGTH = 200

# Any dash a teacher might actually type or paste — hyphen, en dash, em dash,
# minus sign. Copying "2–7" out of a Word document is the common case.
_DASHES = '-‐‑‒–—−'
_DASH_CLASS = f'[{_DASHES}]'

_SINGLE_RE = re.compile(r'^(\d{1,5})$')
_RANGE_RE = re.compile(rf'^(\d{{1,5}})\s*{_DASH_CLASS}\s*(\d{{1,5}})$')
_FROM_RE = re.compile(rf'^(\d{{1,5}})\s*{_DASH_CLASS}$')
_UNTIL_RE = re.compile(rf'^{_DASH_CLASS}\s*(\d{{1,5}})$')

_SYNTAX_HELP = 'Use page numbers and ranges, like "2-7, 9" or "2-" for page 2 to the end.'


class PageSelectionError(ValueError):
    """A page spec we couldn't use. The message is shown to the teacher verbatim."""


def parse_page_selection(spec, page_count):
    """Resolve a page spec into the sorted, de-duplicated 1-based pages to extract.

    ``spec`` is the raw form value (``None``, blank or ``"all"`` meaning every
    page); ``page_count`` is the number of pages in the PDF. Raises
    :class:`PageSelectionError` — with a message written for the teacher, naming
    the part that went wrong — rather than quietly dropping a page they asked
    for.
    """
    text = (spec or '').strip()

    # No selection asked for: hand back every page and stay out of the way. An
    # empty or unreadable document then fails downstream exactly where it always
    # did, rather than being re-diagnosed as a page-selection problem.
    if not text or text.lower() == 'all':
        return list(range(1, (page_count or 0) + 1))

    if page_count is None or page_count < 1:
        raise PageSelectionError('That PDF has no pages to extract.')

    if len(text) > MAX_SPEC_LENGTH:
        raise PageSelectionError(
            f'That page selection is too long ({len(text)} characters, '
            f'maximum {MAX_SPEC_LENGTH}). {_SYNTAX_HELP}'
        )

    # Close up spaces around a dash BEFORE splitting, so "2 - 4" is one range
    # token rather than three. Whitespace is a separator (see below), and these
    # two readings of a space would otherwise collide.
    text = re.sub(rf'\s*({_DASH_CLASS})\s*', r'\1', text)

    selected = set()
    # Commas are the documented separator; semicolons and bare whitespace are
    # accepted too because "2-7 9" is a natural thing to type.
    for token in re.split(r'[,;\s]+', text):
        if not token:
            continue
        selected.update(_parse_token(token, page_count))

    if not selected:
        raise PageSelectionError(f'No pages were selected. {_SYNTAX_HELP}')

    return sorted(selected)


def _parse_token(token, page_count):
    """The pages named by one comma-separated token."""
    match = _SINGLE_RE.match(token)
    if match:
        return [_check_page(int(match.group(1)), page_count, token)]

    match = _RANGE_RE.match(token)
    if match:
        start = _check_page(int(match.group(1)), page_count, token)
        end = _check_page(int(match.group(2)), page_count, token)
        if start > end:
            raise PageSelectionError(
                f'"{token}" runs backwards — write it as {end}-{start}.'
            )
        return list(range(start, end + 1))

    match = _FROM_RE.match(token)
    if match:
        start = _check_page(int(match.group(1)), page_count, token)
        return list(range(start, page_count + 1))

    match = _UNTIL_RE.match(token)
    if match:
        end = _check_page(int(match.group(1)), page_count, token)
        return list(range(1, end + 1))

    raise PageSelectionError(f'Couldn\'t understand "{token}". {_SYNTAX_HELP}')


def _check_page(page, page_count, token):
    """``page`` if it exists in the PDF, else a message naming the real range."""
    if page < 1:
        raise PageSelectionError(f'"{token}" — pages are numbered from 1.')
    if page > page_count:
        raise PageSelectionError(
            f'"{token}" is outside this PDF — it only has {page_count} '
            f'page{"" if page_count == 1 else "s"}.'
        )
    return page


def excluded_pages(selected, page_count):
    """The 1-based pages *not* in ``selected`` — what the teacher chose to skip."""
    chosen = set(selected or ())
    return [p for p in range(1, (page_count or 0) + 1) if p not in chosen]


def format_page_list(pages):
    """Render page numbers back as a compact range string: ``[1,2,3,7] -> "1-3, 7"``.

    Used to tell the teacher on the preview screen exactly which pages were read
    and which were left out, so a page missing from an import is never a mystery.
    """
    ordered = sorted(set(pages or ()))
    if not ordered:
        return ''

    parts, start, prev = [], ordered[0], ordered[0]
    for page in ordered[1:]:
        if page == prev + 1:
            prev = page
            continue
        parts.append(_format_run(start, prev))
        start = prev = page
    parts.append(_format_run(start, prev))
    return ', '.join(parts)


def _format_run(start, end):
    if start == end:
        return str(start)
    if end == start + 1:
        return f'{start}, {end}'
    return f'{start}-{end}'


def selection_summary(spec, selected, page_count):
    """The record stashed on a session's ``extracted_data['page_selection']``.

    Always written — including for a full extraction — so the preview screen can
    state plainly which pages were read instead of leaving the teacher to infer
    it from the questions that happen to be there.
    """
    excluded = excluded_pages(selected, page_count)
    return {
        'spec': (spec or '').strip(),
        'total': page_count,
        'selected': list(selected),
        'excluded': excluded,
        'selected_label': format_page_list(selected),
        'excluded_label': format_page_list(excluded),
    }


def describe_page_selection(extracted_data):
    """The preview-notice context, or ``None`` when every page was extracted.

    Mirrors ``worksheets.services.describe_skipped_pages`` — the templates take
    one small dict and don't reach into the stored payload themselves.
    """
    summary = (extracted_data or {}).get('page_selection') or {}
    if not summary.get('excluded'):
        return None
    return {
        'total': summary.get('total'),
        'selected_label': summary.get('selected_label') or '',
        'excluded_label': summary.get('excluded_label') or '',
        'selected_count': len(summary.get('selected') or []),
        'excluded_count': len(summary.get('excluded') or []),
        'spec': summary.get('spec') or '',
    }


def pdf_page_count(pdf_source):
    """Page count of a PDF given bytes, a path, or a file-like object.

    A file-like source has its stream position restored, so the caller can still
    hand the same upload to Django's storage afterwards.
    """
    import fitz  # PyMuPDF — imported lazily so the parser above stays dependency-free

    if isinstance(pdf_source, (bytes, bytearray)):
        pdf_bytes = bytes(pdf_source)
    elif hasattr(pdf_source, 'read'):
        position = pdf_source.tell() if hasattr(pdf_source, 'tell') else None
        pdf_bytes = pdf_source.read()
        if position is not None and hasattr(pdf_source, 'seek'):
            pdf_source.seek(position)
    else:
        with open(pdf_source, 'rb') as handle:
            pdf_bytes = handle.read()

    doc = fitz.open(stream=pdf_bytes, filetype='pdf')
    try:
        return doc.page_count
    finally:
        doc.close()


def clean_upload_selection(spec, pdf_source):
    """Validate a spec from an upload form against the PDF it was typed for.

    Returns ``(cleaned_spec, selected_pages, page_count)``. Raises
    :class:`PageSelectionError` so the upload view can reject the form
    immediately — a bad range should never reach the background worker, where
    the teacher would only see it as a failed job minutes later.

    An empty spec short-circuits without touching the PDF, so an upload that
    doesn't use the field costs exactly what it did before the field existed.
    ``selected_pages`` is then ``None`` (meaning "all") and ``page_count`` unknown.
    """
    text = (spec or '').strip()
    if not text or text.lower() == 'all':
        return '', None, None

    try:
        page_count = pdf_page_count(pdf_source)
    except PageSelectionError:
        raise
    except Exception as exc:  # unreadable / not a PDF
        raise PageSelectionError(
            f'That file couldn’t be read as a PDF ({exc}).'
        ) from exc

    selected = parse_page_selection(text, page_count)
    # Store "" rather than "all"/"1-N" when nothing is actually excluded, so the
    # default path is indistinguishable from an upload that never used the field.
    if len(selected) == page_count:
        text = ''
    return text, selected, page_count
