"""Turn an uploaded shapes image into a ``shape_select`` ``shape_spec``.

Two backends, tried in order — the "both / fallback" strategy:

  1. :func:`detect_shapes_opencv` — deterministic contour detection for clean
     line-art (the worksheet case). Free, no API calls; classifies each outline
     by its polygon vertex count and circularity.
  2. :func:`detect_shapes_ai` — Claude vision, used only when OpenCV finds no
     shape of the requested target type (hand-drawn / photographed / noisy
     sheets). Costs Anthropic tokens, so it is opt-in via ``allow_ai``.

Both return shapes in the ``shape_select`` traced-geometry forms (``points``
polygons / ``rx``/``ry`` ellipses); :func:`build_shape_spec_from_image` wraps
them into a validated ``shape_spec``. OpenCV / numpy are imported lazily so the
module (and the app) load even when OpenCV isn't installed — in that case the
flow simply falls back to the AI backend.
"""
import base64
import math

from maths.geometry_grading import SHAPE_TYPES, validate_shape_spec

# Classification thresholds (tuned for clean printed line-art).
_MIN_AREA_FRAC = 0.0015      # ignore specks below this fraction of the page
_MAX_AREA_FRAC = 0.95        # ignore a full-page border contour
_CIRCULARITY = 0.80          # 4·π·area / perimeter² above this reads as round
_SQUARENESS = 0.82           # min/max side ratio above this reads as a square


def _centroid(shape):
    """Representative centre of a shape, for stable id ordering."""
    if 'points' in shape:
        pts = shape['points']
        return (sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts))
    return (shape.get('cx', 0), shape.get('cy', 0))


def _assign_ids(shapes, *, row_height=60):
    """Assign stable ``s0``…``sN`` ids in reading order (top→bottom, left→right).

    Quantising y into bands keeps shapes on the same row ordered by x, so the
    same scene always yields the same ids regardless of detection order.
    """
    ordered = sorted(
        shapes,
        key=lambda s: (round(_centroid(s)[1] / row_height), _centroid(s)[0]),
    )
    for i, s in enumerate(ordered):
        s['id'] = f's{i}'
    return ordered


def _has_target(shapes, target_type):
    return any(s.get('type') == target_type for s in shapes)


# ── OpenCV backend ───────────────────────────────────────────────────────

def _classify_contour(approx, area, perimeter, fit_ellipse):
    """Map an approximated contour to a (type, geometry) pair, or None.

    ``approx`` is the cv2.approxPolyDP result; ``fit_ellipse`` is a callable
    returning ``(cx, cy, rx, ry, rot)`` (deferred so the ellipse is only fitted
    when the contour actually looks round). Returns None for a contour that
    doesn't map to one of ``SHAPE_TYPES`` (lowers confidence → AI fallback).
    """
    n = len(approx)
    pts = [[int(p[0][0]), int(p[0][1])] for p in approx]
    circularity = 4 * math.pi * area / (perimeter * perimeter) if perimeter else 0

    if n == 3:
        return 'triangle', {'points': pts}
    if n == 4:
        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        if not w or not h:
            return None
        cx, cy = sum(xs) / 4, sum(ys) / 4
        # A diamond points up/down/left/right: each vertex sits near the centre
        # line of one bbox edge rather than at a corner.
        near_mid = sum(
            1 for x, y in pts
            if abs(x - cx) < 0.18 * w or abs(y - cy) < 0.18 * h
        )
        if near_mid >= 4:
            return 'rhombus', {'points': pts}
        squareness = min(w, h) / max(w, h)
        return ('square' if squareness >= _SQUARENESS else 'rectangle'), {'points': pts}
    if circularity >= _CIRCULARITY:
        cx, cy, rx, ry, rot = fit_ellipse()
        if rx <= 0 or ry <= 0:
            return None
        kind = 'circle' if _SQUARENESS <= min(rx, ry) / max(rx, ry) else 'ellipse'
        return kind, {'cx': cx, 'cy': cy, 'rx': rx, 'ry': ry, 'rot': rot}
    return None


def detect_shapes_opencv(image_bytes):
    """Detect shapes in ``image_bytes``; return ``(width, height, shapes)``.

    Deterministic and token-free. Raises ``RuntimeError`` if OpenCV/numpy aren't
    installed, so the caller can fall back to the AI backend.
    """
    try:
        import cv2
        import numpy as np
    except ImportError as exc:  # pragma: no cover - exercised via fallback path
        raise RuntimeError('OpenCV/numpy not installed') from exc

    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise ValueError('Could not decode image.')
    height, width = img.shape[:2]
    page_area = float(width * height)

    blur = cv2.GaussianBlur(img, (5, 5), 0)
    # Shapes are dark outlines on a light page → invert so they're white.
    _, thresh = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    shapes = []
    for c in contours:
        area = cv2.contourArea(c)
        if not (_MIN_AREA_FRAC * page_area <= area <= _MAX_AREA_FRAC * page_area):
            continue
        perimeter = cv2.arcLength(c, True)
        approx = cv2.approxPolyDP(c, 0.02 * perimeter, True)

        def _fit():
            if len(c) < 5:
                x, y, w, h = cv2.boundingRect(c)
                return x + w / 2, y + h / 2, w / 2, h / 2, 0.0
            (ex, ey), (MA, ma), ang = cv2.fitEllipse(c)
            return ex, ey, MA / 2, ma / 2, ang

        result = _classify_contour(approx, area, perimeter, _fit)
        if result:
            stype, geom = result
            shapes.append({'type': stype, **geom})

    return width, height, shapes


# ── AI backend (Claude vision) ───────────────────────────────────────────

_REPORT_SHAPES_TOOL = {
    'name': 'report_shapes',
    'description': 'Report every distinct 2D shape outline found in the image.',
    'input_schema': {
        'type': 'object',
        'properties': {
            'shapes': {
                'type': 'array',
                'items': {
                    'type': 'object',
                    'properties': {
                        'type': {'type': 'string', 'enum': list(SHAPE_TYPES)},
                        'points': {
                            'type': 'array',
                            'description': 'Outline vertices as [x, y] fractions 0-1 of width/height.',
                            'items': {'type': 'array', 'items': {'type': 'number'}},
                        },
                    },
                    'required': ['type', 'points'],
                },
            },
        },
        'required': ['shapes'],
    },
}

_AI_SYSTEM = (
    'You are a geometry vision tool. Identify every separate 2D shape outline in '
    'the image. For each, give its type and its outline as [x, y] vertices in '
    'fractions of the image width/height (0-1). For a circle or ellipse, give 4 '
    'points at the topmost, rightmost, bottommost and leftmost extremes.'
)


def detect_shapes_ai(image_bytes, width, height, *, media_type='image/png'):
    """Detect shapes via Claude vision; return a list of traced shapes.

    Costs Anthropic tokens. Raises ``RuntimeError`` when no API key is
    configured. Kept token-free in tests by patching the Anthropic client.
    """
    import anthropic
    from django.conf import settings

    api_key = getattr(settings, 'ANTHROPIC_API_KEY', '')
    if not api_key:
        raise RuntimeError('ANTHROPIC_API_KEY not configured; cannot use AI fallback.')

    client = anthropic.Anthropic(api_key=api_key)
    b64 = base64.b64encode(image_bytes).decode('ascii')
    resp = client.messages.create(
        model='claude-haiku-4-5-20251001',
        max_tokens=2048,
        system=_AI_SYSTEM,
        tools=[_REPORT_SHAPES_TOOL],
        tool_choice={'type': 'tool', 'name': 'report_shapes'},
        messages=[{
            'role': 'user',
            'content': [
                {'type': 'image', 'source': {
                    'type': 'base64', 'media_type': media_type, 'data': b64}},
                {'type': 'text', 'text': 'Report every shape outline.'},
            ],
        }],
    )
    return _shapes_from_ai_response(resp, width, height)


def _shapes_from_ai_response(resp, width, height):
    """Convert a tool-use response into pixel-coord traced shapes (defensive)."""
    payload = None
    for block in getattr(resp, 'content', []) or []:
        if getattr(block, 'type', None) == 'tool_use':
            payload = block.input
            break
    if not isinstance(payload, dict):
        return []

    shapes = []
    for raw in payload.get('shapes', []):
        if not isinstance(raw, dict) or raw.get('type') not in SHAPE_TYPES:
            continue
        pts = raw.get('points')
        if not isinstance(pts, list) or len(pts) < 3:
            continue
        try:
            scaled = [[round(float(p[0]) * width, 1), round(float(p[1]) * height, 1)]
                      for p in pts]
        except (TypeError, ValueError, IndexError):
            continue
        shapes.append({'type': raw['type'], 'points': scaled})
    return shapes


# ── Orchestrator ─────────────────────────────────────────────────────────

def build_shape_spec_from_image(image_bytes, target_type, *, allow_ai=True,
                                media_type='image/png'):
    """Detect shapes in an image and return ``(shape_spec, backend)``.

    OpenCV first; if it finds no shape of ``target_type`` and ``allow_ai`` is
    set, fall back to Claude vision. Raises ``ValueError`` (via
    ``validate_shape_spec``) if no usable target shape is found by any backend —
    so the caller can tell the teacher "no <target> detected" rather than save an
    unanswerable question.
    """
    if target_type not in SHAPE_TYPES:
        raise ValueError(f'target_type must be one of {SHAPE_TYPES}.')

    backend = 'opencv'
    width = height = 0
    shapes = []
    try:
        width, height, shapes = detect_shapes_opencv(image_bytes)
    except RuntimeError:
        shapes = []  # OpenCV unavailable → go straight to AI below

    if not _has_target(shapes, target_type) and allow_ai:
        if not (width and height):
            width, height = _image_dimensions(image_bytes)
        ai_shapes = detect_shapes_ai(image_bytes, width, height, media_type=media_type)
        if _has_target(ai_shapes, target_type):
            shapes, backend = ai_shapes, 'ai'

    shapes = _assign_ids(shapes)
    spec = {'target_type': target_type, 'viewbox': [width, height], 'shapes': shapes}
    validate_shape_spec(spec)
    return spec, backend


def _image_dimensions(image_bytes):
    """(width, height) via Pillow — used when OpenCV didn't run."""
    import io

    from PIL import Image

    with Image.open(io.BytesIO(image_bytes)) as im:
        return im.size
