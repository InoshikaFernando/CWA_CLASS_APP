"""Shared view helpers for the teacher "Adjust image" tool.

The homework, worksheet and ai_import review editors all let a teacher re-crop
an extracted question image straight from the source PDF — recovering detail the
auto-crop cut off, or excluding junk it pulled in — without re-uploading. All
three session models expose the same shape (``pdf_file``, ``extracted_data``,
``extracted_images``, ``page_count``), so the logic lives here once and each app
adds a thin, ownership-checked view that delegates to these functions.
"""
import base64
import json
import uuid

from django.http import JsonResponse

from .services import pdf_bytes_from, recrop_pdf_region, render_pdf_page_png

# DPI for the page image shown in the Adjust modal. Only needs to be legible for
# the teacher to place a box; the final crop re-renders at IMAGE_RENDER_DPI.
_MODAL_PAGE_DPI = 130


def page_image_response(session, request):
    """GET: render one full source page as PNG for the Adjust modal.

    Query param ``page`` is 1-based (clamped to the PDF). Returns the page image
    (base64 PNG) plus its point dimensions so the client can map a drag box back
    to page fractions independently of the preview DPI.
    """
    try:
        page = int(request.GET.get('page', 1))
    except (TypeError, ValueError):
        page = 1
    total = session.page_count or 1
    page = max(1, min(total, page))

    if not session.pdf_file:
        return JsonResponse({'error': 'This upload has no stored PDF to re-crop from.'},
                            status=400)
    try:
        pdf_bytes = pdf_bytes_from(session.pdf_file)
        png, pw, ph = render_pdf_page_png(pdf_bytes, page - 1, dpi=_MODAL_PAGE_DPI)
    except Exception as exc:
        return JsonResponse({'error': f'Could not render page {page}: {exc}'}, status=400)

    return JsonResponse({
        'page': page,
        'page_count': total,
        'page_w': pw,
        'page_h': ph,
        'image_b64': base64.b64encode(png).decode('utf-8'),
    })


def recrop_response(session, request):
    """POST: re-render a question image from a teacher-drawn box on the PDF.

    JSON body: ``{q_idx:int, page:int(1-based), box:[x0,y0,x1,y1] fractions,
    snap?:bool}``. Stores the new PNG on the session under a fresh ref, points
    the question at it, and returns ``{ref, image_b64, page}``.
    """
    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Malformed request.'}, status=400)

    try:
        q_idx = int(payload['q_idx'])
        page = int(payload['page'])
        box = [float(v) for v in payload['box']]
    except (KeyError, TypeError, ValueError):
        return JsonResponse({'error': 'Missing or invalid crop fields.'}, status=400)
    if len(box) != 4:
        return JsonResponse({'error': 'Crop box must have four values.'}, status=400)

    data = session.extracted_data or {}
    questions = data.get('questions', [])
    if not (0 <= q_idx < len(questions)):
        return JsonResponse({'error': 'Question no longer exists — reload the page.'},
                            status=400)

    total = session.page_count or 1
    page = max(1, min(total, page))

    if not session.pdf_file:
        return JsonResponse({'error': 'This upload has no stored PDF to re-crop from.'},
                            status=400)
    try:
        pdf_bytes = pdf_bytes_from(session.pdf_file)
        png = recrop_pdf_region(pdf_bytes, page - 1, box, snap=bool(payload.get('snap')))
    except ValueError:
        return JsonResponse({'error': 'That crop area is too small — draw a larger box.'},
                            status=400)
    except Exception as exc:
        return JsonResponse({'error': f'Re-crop failed: {exc}'}, status=400)

    b64 = base64.b64encode(png).decode('utf-8')
    ref = f'adjust_{uuid.uuid4().hex[:10]}.png'

    if session.extracted_images is None:
        session.extracted_images = {}
    session.extracted_images[ref] = b64

    q = questions[q_idx]
    q['image_ref'] = ref
    q['has_image'] = True
    q['image_page'] = page
    q['image_bbox_frac'] = [round(v, 4) for v in box]
    data['questions'] = questions
    session.extracted_data = data
    session.save(update_fields=['extracted_data', 'extracted_images'])

    return JsonResponse({'ref': ref, 'image_b64': b64, 'page': page})


def reuse_previous_image_response(session, request):
    """POST: copy an earlier question's image onto this question under a NEW ref.

    JSON body: ``{q_idx:int, source_ref:str, page?:int, bbox_frac?:[x0,y0,x1,y1]}``.
    The teacher clicks "Same image as previous" when several consecutive
    questions share one figure the extractor didn't group — this duplicates the
    bytes stored under ``source_ref`` to a fresh ref and points ``q_idx`` at it.

    A *fresh* ref is deliberate, not incidental: the homework confirm step dedups
    image questions by their image PATH (derived from the ref), so two questions
    pointing at the SAME ref would collapse into a single row — silently dropping
    the second question. Distinct refs over identical bytes keep the questions
    separate while showing the same picture. Returns ``{ref, image_b64, page}``.
    """
    try:
        payload = json.loads((request.body or b'{}').decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return JsonResponse({'error': 'Malformed request.'}, status=400)

    try:
        q_idx = int(payload['q_idx'])
    except (KeyError, TypeError, ValueError):
        return JsonResponse({'error': 'Missing question index.'}, status=400)

    source_ref = payload.get('source_ref')
    images = session.extracted_images or {}
    b64 = images.get(source_ref) if source_ref else None
    if not b64:
        return JsonResponse(
            {'error': 'That question has no stored image to reuse.'}, status=400)

    data = session.extracted_data or {}
    questions = data.get('questions', [])
    if not (0 <= q_idx < len(questions)):
        return JsonResponse(
            {'error': 'Question no longer exists — reload the page.'}, status=400)

    ref = f'reuse_{uuid.uuid4().hex[:10]}.png'
    if session.extracted_images is None:
        session.extracted_images = {}
    session.extracted_images[ref] = b64

    q = questions[q_idx]
    q['image_ref'] = ref
    q['has_image'] = True

    # Carry the source's crop origin so a later re-crop of THIS question opens on
    # the same page/box. Best-effort — reuse still works without it.
    page = payload.get('page')
    try:
        if page is not None:
            q['image_page'] = int(page)
    except (TypeError, ValueError):
        pass
    frac = payload.get('bbox_frac')
    if isinstance(frac, list) and len(frac) == 4:
        try:
            q['image_bbox_frac'] = [round(float(v), 4) for v in frac]
        except (TypeError, ValueError):
            pass

    data['questions'] = questions
    session.extracted_data = data
    session.save(update_fields=['extracted_data', 'extracted_images'])

    return JsonResponse({'ref': ref, 'image_b64': b64, 'page': q.get('image_page')})
