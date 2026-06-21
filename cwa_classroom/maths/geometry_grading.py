"""Grading helpers for geometry/measurement question types (CPP-330).

Pure functions — no DB, no request — so every delivery surface (homework,
worksheets, the maths plugin) grades identically, the same way
``Question.grade_text_answer`` is centralised on the model.

CPP-332 adds ``grade_measure`` for the ``measure`` question type; CPP-337 adds
``grade_draw_on_grid`` for the ``draw_on_grid`` type (set-comparison grading).
"""
import json
import re
from decimal import Decimal, InvalidOperation


def _to_decimal(raw):
    """Best-effort parse of a typed measurement into a Decimal.

    Strips any non-numeric unit characters (``135°`` -> ``135``) and a
    leading ``+``. Returns ``None`` if nothing numeric remains.
    """
    if raw is None:
        return None
    # Keep ASCII digits, sign, and a decimal point; drop unit letters/symbols.
    # ASCII-only on purpose: str.isdigit() is True for unicode superscripts
    # ('²') and full-width digits, which would corrupt the parsed value.
    cleaned = ''.join(c for c in str(raw).strip() if c in '0123456789.-+')
    if cleaned in ('', '+', '-', '.', '-.', '+.'):
        return None
    try:
        return Decimal(cleaned)
    except (InvalidOperation, ValueError):
        return None


def grade_measure(question, raw):
    """True if the student's typed value is within tolerance of the answer.

    ``correct`` when ``|value - numeric_answer| <= tolerance``, where
    ``tolerance`` is ``answer_tolerance`` or 0 (NULL tolerance = exact match).
    Returns ``False`` on a missing target or an unparseable answer — never
    raises, so a malformed submission is simply wrong, not a 500.
    """
    target = question.numeric_answer
    if target is None:
        return False
    value = _to_decimal(raw)
    if value is None:
        return False
    tolerance = question.answer_tolerance or Decimal('0')
    return abs(value - target) <= tolerance


_GRID_MODES = ('segments', 'points', 'shape_complete')
_TARGET_KEY_FOR_MODE = {
    'segments': 'segments',
    'shape_complete': 'expected_extra_segments',
    'points': 'points',
}


def validate_grid_spec(grid_spec):
    """Validate a ``draw_on_grid`` ``grid_spec``; raise ``ValueError`` if invalid.

    Pure and framework-agnostic (no Django import) so it can be reused by the
    model's ``clean()`` AND by the JSON-bank importer before bulk-create, so a
    malformed spec can't slip in through either path. Checks structure, a known
    ``mode``, a non-empty ``target`` for that mode, and that every coordinate
    (shape + target) is an integer inside the declared grid.
    """
    if not isinstance(grid_spec, dict):
        raise ValueError('grid_spec must be a JSON object.')

    grid = grid_spec.get('grid')
    if not isinstance(grid, dict):
        raise ValueError("grid_spec.grid must be an object with 'cols' and 'rows'.")
    cols, rows = grid.get('cols'), grid.get('rows')
    if not (isinstance(cols, int) and isinstance(rows, int) and cols > 0 and rows > 0):
        raise ValueError('grid_spec.grid.cols and .rows must be positive integers.')

    if not isinstance(grid_spec.get('shape'), dict):
        raise ValueError('grid_spec.shape must be an object.')

    mode = grid_spec.get('mode')
    if mode not in _GRID_MODES:
        raise ValueError(f'grid_spec.mode must be one of {_GRID_MODES}.')

    target = grid_spec.get('target')
    if not isinstance(target, dict):
        raise ValueError('grid_spec.target must be an object.')

    def _check_point(p):
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError(f'Point must be [x, y]; got {p!r}.')
        x, y = p
        if not (isinstance(x, int) and isinstance(y, int)):
            raise ValueError(f'Point coordinates must be integers; got {p!r}.')
        if not (0 <= x < cols and 0 <= y < rows):
            raise ValueError(f'Point {p!r} is outside the {cols}x{rows} grid.')

    def _check_segment(s):
        if not isinstance(s, dict):
            raise ValueError(f'Segment must be an object; got {s!r}.')
        try:
            pts = [(s['x1'], s['y1']), (s['x2'], s['y2'])]
        except (KeyError, TypeError):
            raise ValueError(f'Segment must have x1, y1, x2, y2; got {s!r}.')
        for p in pts:
            _check_point(list(p))
        if pts[0] == pts[1]:
            raise ValueError(f'Segment endpoints must differ; got {s!r}.')

    # Shape points (if present) must be in-bounds too.
    for p in grid_spec['shape'].get('points', []):
        _check_point(p)

    key = _TARGET_KEY_FOR_MODE[mode]
    items = target.get(key)
    if not isinstance(items, list) or not items:
        raise ValueError(f"grid_spec.target.{key} must be a non-empty list for mode '{mode}'.")
    if mode == 'points':
        for p in items:
            _check_point(p)
    else:
        for s in items:
            _check_segment(s)


def _segment_key(seg):
    """Canonical, order-independent key for a grid segment.

    A line drawn dot-A→dot-B must equal the same line drawn dot-B→dot-A, so we
    sort the two endpoints. Endpoints are integer grid indices.
    """
    p1 = (int(seg['x1']), int(seg['y1']))
    p2 = (int(seg['x2']), int(seg['y2']))
    return tuple(sorted((p1, p2)))


def _point_key(pt):
    """Canonical key for a marked grid point (a 2-element [x, y])."""
    return (int(pt[0]), int(pt[1]))


def grade_draw_on_grid(grid_spec, payload):
    """True if the student's marks match the target set for the grid question.

    Grading is a deterministic SET comparison — the same order-independent
    philosophy as the prime-factorisation grader. The interaction ``mode`` in
    ``grid_spec`` selects what is compared:

      - ``segments`` (default) / ``shape_complete`` → set of canonicalised line
        segments (``target.segments`` / ``target.expected_extra_segments``).
      - ``points`` → set of marked dots (``target.points``).

    ``allow_extra`` (default False): when False the student set must EQUAL the
    target (drawing an extra line is wrong — "draw *all* lines of symmetry");
    when True the target must be a SUBSET of the student's marks.

    ``payload`` is the student submission as a JSON string (or already-parsed
    dict) shaped like the target: ``{"segments": [...]}`` or ``{"points": [...]}``.
    Returns ``False`` on a malformed/empty payload or an empty target — never
    raises, so a bad submission is simply wrong, not a 500.
    """
    # Defensive against specs that bypassed Model.clean() (raw admin JSON,
    # fixtures, bulk import): a non-dict grid_spec/target must not 500 the
    # grade view — the docstring promises this never raises.
    if not isinstance(grid_spec, dict):
        return False
    mode = grid_spec.get('mode') or 'segments'
    target = grid_spec.get('target')
    if not isinstance(target, dict):
        return False
    allow_extra = bool(grid_spec.get('allow_extra'))

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False

    try:
        if mode == 'points':
            want = {_point_key(p) for p in target.get('points', [])}
            got = {_point_key(p) for p in data.get('points', [])}
        else:  # 'segments' or 'shape_complete'
            target_key = 'expected_extra_segments' if mode == 'shape_complete' else 'segments'
            want = {_segment_key(s) for s in target.get(target_key, [])}
            got = {_segment_key(s) for s in data.get('segments', [])}
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return False

    if not want:
        return False
    return want.issubset(got) if allow_extra else want == got


# ── shape_select (CPP — find & colour shapes) ────────────────────────────
# A scene of mixed 2D shapes where the student colours the ones matching a
# target type ("colour all the triangles"). Same set-comparison philosophy as
# draw_on_grid: the spec is server-authoritative (the shapes and their types
# are stored), the target id set is DERIVED (shapes whose type == target_type),
# and grading compares the student's coloured-id set to it.
SHAPE_TYPES = ('triangle', 'circle', 'square', 'rectangle', 'ellipse', 'rhombus')


def shape_target_ids(shape_spec):
    """Set of shape ids whose type is the spec's ``target_type``.

    Derived, never stored — so the answer key can't drift from the figure.
    Defensive: returns an empty set for a malformed spec, so grading and the
    render helper never raise on a spec that bypassed ``validate_shape_spec``.
    """
    if not isinstance(shape_spec, dict):
        return set()
    target = shape_spec.get('target_type')
    out = set()
    for s in shape_spec.get('shapes') or []:
        if isinstance(s, dict) and s.get('type') == target and s.get('id') is not None:
            out.add(str(s['id']))
    return out


def _is_number(v):
    """True for a real numeric coordinate. ``bool`` is an ``int`` subclass, so
    reject it explicitly — True/False must not pose as coordinates."""
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def shape_geometry_form(shape):
    """Which geometry form a shape uses: ``polygon``, ``ellipse`` or ``parametric``.

    Generated scenes use the parametric centre+size form; detected/traced shapes
    carry explicit geometry — a ``points`` list (polygon) or ``rx``/``ry`` (an
    ellipse). Both validation and the SVG builder dispatch on this, so the two
    authoring paths (generator vs image import) share one spec + one grader.
    """
    if 'points' in shape:
        return 'polygon'
    if 'rx' in shape or 'ry' in shape:
        return 'ellipse'
    return 'parametric'


def _validate_shape_geometry(sid, s):
    """Validate one shape's geometry by its form; raise ``ValueError`` if invalid."""
    form = shape_geometry_form(s)
    if form == 'polygon':
        pts = s.get('points')
        if not isinstance(pts, list) or len(pts) < 3:
            raise ValueError(f'Shape {sid!r} points must be a list of >= 3 [x, y].')
        for p in pts:
            if not (isinstance(p, (list, tuple)) and len(p) == 2
                    and all(_is_number(c) for c in p)):
                raise ValueError(f'Shape {sid!r} has a malformed point {p!r}.')
    elif form == 'ellipse':
        for k in ('cx', 'cy', 'rx', 'ry'):
            if not _is_number(s.get(k)):
                raise ValueError(f'Shape {sid!r} {k} must be a number; got {s.get(k)!r}.')
        if s['rx'] <= 0 or s['ry'] <= 0:
            raise ValueError(f'Shape {sid!r} rx/ry must be positive.')
        if not _is_number(s.get('rot', 0)):
            raise ValueError(f"Shape {sid!r} rot must be a number; got {s.get('rot')!r}.")
    else:  # parametric
        for k in ('cx', 'cy', 'size'):
            if not _is_number(s.get(k)):
                raise ValueError(f'Shape {sid!r} {k} must be a number; got {s.get(k)!r}.')
        if s['size'] <= 0:
            raise ValueError(f'Shape {sid!r} size must be positive.')
        if not _is_number(s.get('rot', 0)):
            raise ValueError(f"Shape {sid!r} rot must be a number; got {s.get('rot')!r}.")


def validate_shape_spec(shape_spec):
    """Validate a ``shape_select`` ``shape_spec``; raise ``ValueError`` if invalid.

    Pure and framework-agnostic (no Django import) so it is reused by the model's
    ``clean()`` AND by both authoring paths before a scene is stored — the
    procedural generator and the image importer — so a malformed spec can't slip
    in through any path. Mirrors ``validate_grid_spec``. Checks structure, a
    ``target_type`` in ``SHAPE_TYPES``, a non-empty ``shapes`` list of known-type
    shapes with unique string ids and valid geometry (parametric, polygon, or
    ellipse form — see ``shape_geometry_form``), and that at least one shape
    actually has the target type (else the question is unanswerable).
    """
    if not isinstance(shape_spec, dict):
        raise ValueError('shape_spec must be a JSON object.')

    target = shape_spec.get('target_type')
    if target not in SHAPE_TYPES:
        raise ValueError(f'shape_spec.target_type must be one of {SHAPE_TYPES}.')

    shapes = shape_spec.get('shapes')
    if not isinstance(shapes, list) or not shapes:
        raise ValueError('shape_spec.shapes must be a non-empty list.')

    seen = set()
    for s in shapes:
        if not isinstance(s, dict):
            raise ValueError(f'Each shape must be an object; got {s!r}.')
        sid = s.get('id')
        if not isinstance(sid, str) or not sid:
            raise ValueError(f'Shape id must be a non-empty string; got {sid!r}.')
        if sid in seen:
            raise ValueError(f'Duplicate shape id {sid!r}.')
        seen.add(sid)
        if s.get('type') not in SHAPE_TYPES:
            raise ValueError(f"Shape {sid!r} has unknown type {s.get('type')!r}.")
        _validate_shape_geometry(sid, s)

    if not any(isinstance(s, dict) and s.get('type') == target for s in shapes):
        raise ValueError(f"shape_spec has no shape of target_type '{target}'.")


def grade_shape_select(shape_spec, payload):
    """True if the student coloured exactly the shapes matching ``target_type``.

    Deterministic SET comparison — the same order-independent philosophy as
    ``grade_draw_on_grid``: the coloured-id set must EQUAL the target-id set
    (colouring an extra shape, or missing one, is wrong — "colour *all* the
    triangles"). ``payload`` is the student submission as a JSON string (or
    already-parsed dict) shaped ``{"selected": ["s0", "s3", ...]}``.

    Returns ``False`` on a malformed/empty payload or a spec with no target
    shapes — never raises, so a bad submission is simply wrong, not a 500.
    """
    want = shape_target_ids(shape_spec)
    if not want:
        return False
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    selected = data.get('selected')
    if not isinstance(selected, list):
        return False
    try:
        got = {str(x) for x in selected}
    except TypeError:
        return False
    return want == got


# ── plane_spec (CPP — Cartesian plane: plot / identify coordinates) ───────────
# A SIGNED coordinate plane (four quadrants, negatives allowed) shared by three
# question types: plot_points (tap dots), plot_line (tap dots that auto-connect
# into segments), and identify_coords (read plotted points, type them). Same
# set-comparison philosophy as draw_on_grid; the only logic difference is the
# bounds check accepts negatives (xmin <= x <= xmax) instead of 0 <= x < cols.
_PLANE_MODES = ('points', 'segments')


def _plane_bounds(plane_spec):
    """Return ``(xmin, xmax, ymin, ymax)`` as ints, or ``None`` if malformed.

    Shared by the validator, the grader and the render helper so "what is in
    bounds" is defined once.
    """
    if not isinstance(plane_spec, dict):
        return None
    b = plane_spec.get('bounds')
    if not isinstance(b, dict):
        return None
    try:
        xmin, xmax = int(b['xmin']), int(b['xmax'])
        ymin, ymax = int(b['ymin']), int(b['ymax'])
    except (KeyError, TypeError, ValueError):
        return None
    if xmin >= xmax or ymin >= ymax:
        return None
    return xmin, xmax, ymin, ymax


def validate_plane_spec(plane_spec):
    """Validate a ``plane_spec``; raise ``ValueError`` if invalid.

    Pure and framework-agnostic (no Django import) so it is reused by the model's
    ``clean()`` AND by both AI-PDF importers before a spec is stored — a
    malformed spec can't slip in through any path. Mirrors ``validate_grid_spec``
    but on SIGNED integer coordinates. Checks bounds, a known ``mode``, a
    non-empty ``target`` for that mode, and that every coordinate (given + target)
    is an integer inside the declared bounds.
    """
    if not isinstance(plane_spec, dict):
        raise ValueError('plane_spec must be a JSON object.')

    bounds = _plane_bounds(plane_spec)
    if bounds is None:
        raise ValueError(
            'plane_spec.bounds must have integer xmin<xmax and ymin<ymax.'
        )
    xmin, xmax, ymin, ymax = bounds

    mode = plane_spec.get('mode')
    if mode not in _PLANE_MODES:
        raise ValueError(f'plane_spec.mode must be one of {_PLANE_MODES}.')

    def _check_point(p):
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            raise ValueError(f'Point must be [x, y]; got {p!r}.')
        x, y = p
        if not (isinstance(x, int) and isinstance(y, int)
                and not isinstance(x, bool) and not isinstance(y, bool)):
            raise ValueError(f'Point coordinates must be integers; got {p!r}.')
        if not (xmin <= x <= xmax and ymin <= y <= ymax):
            raise ValueError(f'Point {p!r} is outside the plane bounds.')

    def _check_segment(s):
        if not isinstance(s, dict):
            raise ValueError(f'Segment must be an object; got {s!r}.')
        try:
            pts = [(s['x1'], s['y1']), (s['x2'], s['y2'])]
        except (KeyError, TypeError):
            raise ValueError(f'Segment must have x1, y1, x2, y2; got {s!r}.')
        for p in pts:
            _check_point(list(p))
        if pts[0] == pts[1]:
            raise ValueError(f'Segment endpoints must differ; got {s!r}.')

    # Given points (shown pre-plotted) must be in-bounds too.
    given = plane_spec.get('given_points') or []
    if not isinstance(given, list):
        raise ValueError('plane_spec.given_points must be a list.')
    for p in given:
        _check_point(p)

    target = plane_spec.get('target')
    if not isinstance(target, dict):
        raise ValueError('plane_spec.target must be an object.')
    if mode == 'points':
        items = target.get('points')
        if not isinstance(items, list) or not items:
            raise ValueError("plane_spec.target.points must be a non-empty list for mode 'points'.")
        for p in items:
            _check_point(p)
    else:  # segments
        items = target.get('segments')
        if not isinstance(items, list) or not items:
            raise ValueError("plane_spec.target.segments must be a non-empty list for mode 'segments'.")
        for s in items:
            _check_segment(s)


def grade_plane(plane_spec, payload):
    """True if the student's plotted marks match the target set for a plane question.

    Deterministic SET comparison — the signed-coordinate sibling of
    ``grade_draw_on_grid`` (and reuses ``_segment_key`` / ``_point_key``). The
    ``mode`` selects what is compared: ``points`` (plotted dots) or ``segments``
    (auto-connected line). ``allow_extra`` (default False): when False the
    student set must EQUAL the target; when True the target must be a SUBSET.

    ``payload`` is the student submission as a JSON string (or already-parsed
    dict) shaped ``{"points": [...]}`` or ``{"segments": [...]}``. Returns
    ``False`` on a malformed/empty payload or empty target — never raises.
    """
    if not isinstance(plane_spec, dict):
        return False
    mode = plane_spec.get('mode') or 'points'
    target = plane_spec.get('target')
    if not isinstance(target, dict):
        return False
    allow_extra = bool(plane_spec.get('allow_extra'))

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False

    try:
        if mode == 'segments':
            want = {_segment_key(s) for s in target.get('segments', [])}
            got = {_segment_key(s) for s in data.get('segments', [])}
        else:  # points
            want = {_point_key(p) for p in target.get('points', [])}
            got = {_point_key(p) for p in data.get('points', [])}
    except (AttributeError, KeyError, TypeError, ValueError, IndexError):
        return False

    if not want:
        return False
    return want.issubset(got) if allow_extra else want == got


# ── identify_coords — student TYPES the coordinates of plotted point(s) ───────
_COORD_PAIR_RE = re.compile(r'\(?\s*(-?\d+)\s*,\s*(-?\d+)\s*\)?')


def parse_coords(text):
    """Parse typed coordinates into a set of ``(x, y)`` integer tuples.

    Tolerant of the many ways a pupil writes a point: ``"(-2, 4)"``, ``"-2,4"``,
    ``" ( -2 , 4 ) "``, and several points ``"(1,2) (3,4)"`` or
    ``"(1,2); (3,4)"``. Pure and defensive — returns ``set()`` for anything
    unparseable, never raises (a bad answer is wrong, not a 500).
    """
    if not isinstance(text, str):
        return set()
    out = set()
    for m in _COORD_PAIR_RE.finditer(text):
        try:
            out.add((int(m.group(1)), int(m.group(2))))
        except (TypeError, ValueError):
            continue
    return out


def grade_identify_coords(plane_spec, text):
    """True if the typed coordinates equal the plane_spec's ``target.points`` set.

    The plane is rendered with the point(s) already plotted (``given_points``);
    the student reads and types them. Grading is exact SET equality of parsed
    coordinates against ``target.points``. Returns ``False`` on a malformed spec
    or unparseable answer — never raises.
    """
    if not isinstance(plane_spec, dict):
        return False
    target = plane_spec.get('target')
    if not isinstance(target, dict):
        return False
    try:
        want = {_point_key(p) for p in target.get('points', [])}
    except (TypeError, ValueError, IndexError):
        return False
    if not want:
        return False
    return parse_coords(text) == want


def validate_graph_spec(graph_spec):
    """Validate a ``read_graph`` ``graph_spec`` (render-only); raise ``ValueError``.

    Requires an ``x_axis`` and ``y_axis`` each with numeric ``min`` < ``max``,
    and a non-empty ``series`` whose every point is numeric and within axis
    range. Pure and framework-agnostic so it is reused by the model's
    ``clean()`` AND both importers. The *answer* is graded by ``grade_measure``
    (numeric_answer + tolerance) — this validates only the figure data.
    """
    if not isinstance(graph_spec, dict):
        raise ValueError('graph_spec must be a JSON object.')

    def _axis(name):
        ax = graph_spec.get(name)
        if not isinstance(ax, dict):
            raise ValueError(f'graph_spec.{name} must be an object.')
        lo, hi = ax.get('min'), ax.get('max')
        if not (_is_number(lo) and _is_number(hi)):
            raise ValueError(f'graph_spec.{name}.min and .max must be numbers.')
        if lo >= hi:
            raise ValueError(f'graph_spec.{name}.min must be less than .max.')
        return lo, hi

    xmin, xmax = _axis('x_axis')
    ymin, ymax = _axis('y_axis')

    series = graph_spec.get('series')
    if not isinstance(series, list) or not series:
        raise ValueError('graph_spec.series must be a non-empty list.')
    for s in series:
        if not isinstance(s, dict):
            raise ValueError(f'Each series must be an object; got {s!r}.')
        pts = s.get('points')
        if not isinstance(pts, list) or not pts:
            raise ValueError('Each series must have a non-empty points list.')
        for p in pts:
            if not (isinstance(p, (list, tuple)) and len(p) == 2
                    and _is_number(p[0]) and _is_number(p[1])):
                raise ValueError(f'Series point must be [x, y] numbers; got {p!r}.')
            if not (xmin <= p[0] <= xmax and ymin <= p[1] <= ymax):
                raise ValueError(f'Series point {p!r} is outside the axis range.')
