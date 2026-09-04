"""Grading helpers for geometry/measurement question types (CPP-330).

Pure functions — no DB, no request — so every delivery surface (homework,
worksheets, the maths plugin) grades identically, the same way
``Question.grade_text_answer`` is centralised on the model.

CPP-332 adds ``grade_measure`` for the ``measure`` question type; CPP-337 adds
``grade_draw_on_grid`` for the ``draw_on_grid`` type (set-comparison grading).
"""
import json
import re
from decimal import ROUND_FLOOR, Decimal, InvalidOperation


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
# Max axis span a plane may declare. cartesian_plane_svg refuses to draw a larger
# plane (it would emit thousands of grid lines / a node per lattice point), so the
# validator rejects it too — the figure and the validator share one limit.
_MAX_PLANE_SPAN = 40


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


# A point label is a name off the question text ("A", "B", "P₁"), not prose —
# a long one would overrun the grid it is drawn on.
_MAX_POINT_LABEL = 4


def given_point_parts(p):
    """Return ``(x, y, label)`` for one ``given_points`` entry; raise ``ValueError``.

    A given point is written either bare — ``[2, 2]`` — or named, as
    ``[2, 2, "A"]`` or ``{"x": 2, "y": 2, "label": "A"}``. The name matters:
    a question phrased "A is the point (2, 2), B is the point (8, 2) … write
    down the co-ordinates of the mid point of AB" draws three interchangeable
    dots without it, and no child can tell which one is A.

    The label is always a string (``''`` when unnamed); coordinates are returned
    untouched so the caller's own bounds/integer check reports on them.
    """
    label = ''
    if isinstance(p, dict):
        try:
            x, y = p['x'], p['y']
        except (KeyError, TypeError):
            raise ValueError(f'Given point must have x and y; got {p!r}.')
        raw = p.get('label')
    elif isinstance(p, (list, tuple)) and len(p) in (2, 3):
        x, y = p[0], p[1]
        raw = p[2] if len(p) == 3 else None
    else:
        raise ValueError(
            f'Given point must be [x, y], [x, y, label] or '
            f'{{"x", "y", "label"}}; got {p!r}.'
        )
    if raw is not None:
        if not isinstance(raw, str):
            raise ValueError(f'Given point label must be a string; got {raw!r}.')
        label = raw.strip()
    return x, y, label


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
    # Cap the span to match cartesian_plane_svg's render limit: beyond this the
    # backdrop SVG bails out (returning '') while the lattice still renders a node
    # per point — an axis-less plane and a huge DOM. Reject it at the source so a
    # plane that can't be drawn can't be stored.
    if (xmax - xmin) > _MAX_PLANE_SPAN or (ymax - ymin) > _MAX_PLANE_SPAN:
        raise ValueError(
            f'plane_spec bounds span must not exceed {_MAX_PLANE_SPAN} units per axis.'
        )

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

    # Given points (shown pre-plotted) must be in-bounds too. Each may carry a
    # LABEL — see given_point_parts: a question that names its points ("A is the
    # point (2, 2), B is (8, 2)") is unanswerable without them on the drawing.
    given = plane_spec.get('given_points') or []
    if not isinstance(given, list):
        raise ValueError('plane_spec.given_points must be a list.')
    for p in given:
        x, y, label = given_point_parts(p)
        _check_point([x, y])
        if len(label) > _MAX_POINT_LABEL:
            raise ValueError(
                f'given_points label must be at most {_MAX_POINT_LABEL} '
                f'characters; got {label!r}.'
            )

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

    # Optional: draw a smooth curve through the student's plotted points (plot_points
    # only — a visual "join the dots into a parabola" aid; grading is unchanged).
    curve = plane_spec.get('curve')
    if curve is not None and not isinstance(curve, bool):
        raise ValueError('plane_spec.curve must be a boolean.')


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


# ---------------------------------------------------------------------------
# number_line — mark a value on / read a value off a number line
# ---------------------------------------------------------------------------

_NUMBER_LINE_MODES = ('mark', 'read')
# Cap the tick count so an absurd spec (min -1000, max 1000, step 1) can't emit
# thousands of ticks; validate_number_line_spec enforces the same cap so a stored
# spec always renders.
_MAX_NUMBER_LINE_TICKS = 60


def _num_key(v):
    """Canonical comparison key for a number-line value (int-if-whole float).

    ``5`` and ``5.0`` must compare equal in a set, so both map to the same key.
    """
    f = float(v)
    return int(f) if f.is_integer() else round(f, 6)


def number_line_ticks(spec):
    """Return the list of tick VALUES for a number_line spec, or None if invalid.

    Ticks run ``min, min+step, … ≤ max``. Pure and defensive: returns None for a
    malformed/oversized spec so the model render helper and svg builder can guard
    with a single check (never raises). ``validate_number_line_spec`` is the strict
    gate used at import/clean time; this is the lenient render-time reader.
    """
    if not isinstance(spec, dict):
        return None
    lo, hi, step = spec.get('min'), spec.get('max'), spec.get('step', 1)
    if not (_is_number(lo) and _is_number(hi) and _is_number(step)):
        return None
    if step <= 0 or lo >= hi:
        return None
    # Round before truncating so a decimal step whose division lands just under
    # an integer (0.3 / 0.1 == 2.9999999999999996) doesn't drop the last tick.
    n = int(round((hi - lo) / step, 9))
    if n < 1 or n + 1 > _MAX_NUMBER_LINE_TICKS:
        return None
    ticks = [_num_key(lo + i * step) for i in range(n + 1)]
    return ticks


def validate_number_line_spec(spec):
    """Validate a ``number_line`` ``number_line_spec``; raise ``ValueError`` if bad.

    Pure and framework-agnostic (no Django import) so it is reused by the model's
    ``clean()`` AND by both PDF importers before persisting, so a malformed spec
    can't slip in through either path. Checks the scale (min < max, positive step,
    bounded tick count), a known ``mode``, and that the mode's required values are
    present, numeric, in range, and aligned to a tick (so a marked/read answer is
    actually reachable on the drawn line).
    """
    if not isinstance(spec, dict):
        raise ValueError('number_line_spec must be a JSON object.')
    lo, hi, step = spec.get('min'), spec.get('max'), spec.get('step', 1)
    if not (_is_number(lo) and _is_number(hi)):
        raise ValueError('number_line_spec.min and .max must be numbers.')
    if not _is_number(step) or step <= 0:
        raise ValueError('number_line_spec.step must be a positive number.')
    if lo >= hi:
        raise ValueError('number_line_spec.min must be less than .max.')
    ticks = number_line_ticks(spec)
    if ticks is None:
        raise ValueError(
            f'number_line_spec has too many ticks (max {_MAX_NUMBER_LINE_TICKS}); '
            'widen the step or narrow the range.'
        )
    tick_set = set(ticks)

    mode = spec.get('mode', 'mark')
    if mode not in _NUMBER_LINE_MODES:
        raise ValueError(f'number_line_spec.mode must be one of {_NUMBER_LINE_MODES}.')

    def _check_values(key, values):
        if not isinstance(values, list) or not values:
            raise ValueError(f'number_line_spec.{key} must be a non-empty list.')
        for v in values:
            if not _is_number(v):
                raise ValueError(f'number_line_spec.{key} value must be a number; got {v!r}.')
            if _num_key(v) not in tick_set:
                raise ValueError(
                    f'number_line_spec.{key} value {v!r} is not on a tick '
                    f'(min {lo}, max {hi}, step {step}).'
                )

    if mode == 'mark':
        # The student places marker(s); target is the required set.
        _check_values('target', spec.get('target'))
    else:  # read
        # The line shows marker(s) at given positions; the student types them.
        _check_values('given', spec.get('given'))
        # target defaults to given; if supplied explicitly it must also be valid.
        if spec.get('target') is not None:
            _check_values('target', spec.get('target'))

    tol = spec.get('tolerance')
    if tol is not None and (not _is_number(tol) or tol < 0):
        raise ValueError('number_line_spec.tolerance must be a non-negative number.')


def _number_line_targets(spec):
    """The set of correct values for grading: ``target`` (or ``given`` if target
    is omitted, e.g. a read question whose answer is exactly the drawn marks)."""
    targets = spec.get('target')
    if targets is None:
        targets = spec.get('given') or []
    return targets


def grade_number_line(spec, payload):
    """Grade a number_line answer. Returns ``True``/``False``, never raises.

    - ``mark`` mode: ``payload`` is the JSON the client serialises,
      ``{"marks": [values...]}``. Correct when the marked set equals the target
      set (exact, on-tick — no tolerance, since taps land on ticks).
    - ``read`` mode: ``payload`` is the typed text (e.g. ``"3"`` or ``"3, 5"``).
      Correct when the parsed values match the target multiset within
      ``tolerance`` (``0`` = exact).

    A malformed spec or unparseable answer simply grades wrong.
    """
    if not isinstance(spec, dict):
        return False
    mode = spec.get('mode', 'mark')
    targets = _number_line_targets(spec)
    if not targets:
        return False

    if mode == 'mark':
        try:
            data = json.loads(payload) if isinstance(payload, str) else payload
        except (ValueError, TypeError):
            return False
        if not isinstance(data, dict):
            return False
        marks = data.get('marks')
        if not isinstance(marks, list):
            return False
        try:
            got = {_num_key(m) for m in marks}
        except (TypeError, ValueError):
            return False
        want = {_num_key(t) for t in targets}
        return got == want

    # read mode — parse the typed numbers and multiset-compare within tolerance.
    if not isinstance(payload, str):
        return False
    tol = spec.get('tolerance') or 0
    try:
        tol = Decimal(str(tol))
    except (InvalidOperation, ValueError):
        tol = Decimal('0')
    got = [d for d in (_to_decimal(tok) for tok in re.split(r'[,;\s]+', payload.strip())) if d is not None]
    want = [Decimal(str(t)) for t in targets]
    if len(got) != len(want):
        return False
    # Greedy match: each typed value must pair with a distinct target within tol.
    remaining = list(want)
    for g in got:
        hit = next((w for w in remaining if abs(g - w) <= tol), None)
        if hit is None:
            return False
        remaining.remove(hit)
    return not remaining


# ---------------------------------------------------------------------------
# table_of_values — fill in a table of values (e.g. compute y for each x)
# ---------------------------------------------------------------------------

# Cap the table size so an absurd spec can't emit a huge DOM / grade forever. A
# worksheet table of values is small — a handful of columns, a dozen-odd rows.
_MAX_TABLE_COLS = 8
_MAX_TABLE_ROWS = 20


def _table_cell_kind(cell):
    """Classify one table cell, or return ``None`` if malformed.

    A cell is a JSON object carrying EXACTLY ONE of ``given`` (a value shown
    pre-filled and read-only, e.g. the x column) or ``answer`` (the value the
    student must type, e.g. the y column). Returns ``(role, value)`` where
    ``role`` is ``'given'`` or ``'answer'``, else ``None`` (missing both, or
    carrying both — an ambiguous cell). Shared by the validator, the grader and
    the model render helper so "what a cell means" is defined once.
    """
    if not isinstance(cell, dict):
        return None
    has_given = 'given' in cell
    has_answer = 'answer' in cell
    if has_given == has_answer:  # neither, or both → malformed
        return None
    return ('given', cell['given']) if has_given else ('answer', cell['answer'])


def validate_table_spec(table_spec):
    """Validate a ``table_of_values`` ``table_spec``; raise ``ValueError`` if bad.

    Pure and framework-agnostic (no Django import) so it is reused by the model's
    ``clean()`` AND by any importer before persisting, so a malformed spec can't
    slip in through either path. Mirrors ``validate_number_line_spec``.

    Shape::

        {"headers": ["x", "y"],
         "rows": [[{"given": "-3"}, {"answer": "7"}], ...],
         "tolerance": 0}

    Every row must carry one cell per header; each cell has exactly one of
    ``given`` (shown, read-only) or ``answer`` (a blank the student fills). Every
    ``answer`` value must be numeric (grading is numeric-within-tolerance) and at
    least one ``answer`` cell must exist (else the table is unanswerable).
    """
    if not isinstance(table_spec, dict):
        raise ValueError('table_spec must be a JSON object.')

    headers = table_spec.get('headers')
    if not isinstance(headers, list) or not headers:
        raise ValueError('table_spec.headers must be a non-empty list.')
    if len(headers) > _MAX_TABLE_COLS:
        raise ValueError(f'table_spec.headers must not exceed {_MAX_TABLE_COLS} columns.')
    for h in headers:
        if not isinstance(h, str):
            raise ValueError(f'table_spec.headers value must be a string; got {h!r}.')
    ncols = len(headers)

    rows = table_spec.get('rows')
    if not isinstance(rows, list) or not rows:
        raise ValueError('table_spec.rows must be a non-empty list.')
    if len(rows) > _MAX_TABLE_ROWS:
        raise ValueError(f'table_spec.rows must not exceed {_MAX_TABLE_ROWS} rows.')

    answer_count = 0
    for r, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != ncols:
            raise ValueError(
                f'table_spec.rows[{r}] must be a list of {ncols} cells (one per header).'
            )
        for c, cell in enumerate(row):
            kind = _table_cell_kind(cell)
            if kind is None:
                raise ValueError(
                    f'table_spec cell [{r},{c}] must have exactly one of "given" or "answer".'
                )
            role, value = kind
            if role == 'answer':
                if _to_decimal(value) is None:
                    raise ValueError(
                        f'table_spec answer cell [{r},{c}] value must be numeric; got {value!r}.'
                    )
                answer_count += 1

    if answer_count == 0:
        raise ValueError('table_spec must have at least one "answer" cell.')

    tol = table_spec.get('tolerance')
    if tol is not None and (not _is_number(tol) or tol < 0):
        raise ValueError('table_spec.tolerance must be a non-negative number.')


def grade_table(table_spec, payload):
    """Grade a ``table_of_values`` answer. Returns ``True``/``False``, never raises.

    Correct when EVERY ``answer`` cell's typed value is within ``tolerance`` of
    the stored value (``tolerance`` 0 = exact) — a table is right only when
    fully right. ``payload`` is the JSON the client serialises,
    ``{"cells": {"<r>,<c>": "<typed>"}}`` keyed by each answer cell's row,col. A
    malformed spec/payload or a missing/blank/unparseable cell simply grades
    wrong.

    This is the boolean view of :func:`grade_table_parts`, which grades the same
    cells one at a time so a chart with one cell wrong is worth all but that
    cell rather than nothing.
    """
    grade = grade_table_parts(table_spec, payload)
    return grade is not None and grade.is_correct


def grade_table_parts(table_spec, payload):
    """Grade a ``table_of_values`` answer cell by cell, for partial credit.

    Returns a :class:`~maths.partial_credit.PartialGrade` — one
    :class:`~maths.partial_credit.Part` per ``answer`` cell, in reading order,
    labelled by the row's given value and the column's header ("Decimal form
    for 56") so a wrong cell can be pointed at on the student's screen — or
    ``None`` when there is nothing to grade against: a malformed spec, a
    malformed payload, or a spec with no answer cells (which is unanswerable,
    and must never come back "correct").

    A cell left blank or unparseable is one wrong part, not a wrecked answer:
    the other cells still count. Never raises.
    """
    from maths.partial_credit import Part, PartialGrade

    if not isinstance(table_spec, dict):
        return None
    headers = table_spec.get('headers')
    rows = table_spec.get('rows')
    if not isinstance(headers, list) or not isinstance(rows, list):
        return None

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    cells = data.get('cells')
    if not isinstance(cells, dict):
        return None

    tol = table_spec.get('tolerance') or 0
    try:
        tol = Decimal(str(tol))
    except (InvalidOperation, ValueError):
        tol = Decimal('0')

    parts = []
    for r, row in enumerate(rows):
        if not isinstance(row, list):
            return None
        # The row's first given value is what the row is called on screen —
        # "56" in a money chart, "-3" in a table of values.
        row_label = _table_row_label(row)
        for c, cell in enumerate(row):
            kind = _table_cell_kind(cell)
            if kind is None:
                return None
            role, value = kind
            if role != 'answer':
                continue
            want = _to_decimal(value)
            if want is None:
                # A non-numeric answer cell is a content defect, not a student
                # mistake, and there is no honest fraction to give for it.
                return None
            typed = cells.get(f'{r},{c}')
            got = _to_decimal(typed)
            header = str(headers[c]) if c < len(headers) else f'Column {c + 1}'
            label = f'{header} for {row_label}' if row_label else f'{header}, row {r + 1}'
            parts.append(Part(
                label=label,
                typed='' if typed is None else str(typed),
                expected=str(value),
                is_correct=got is not None and abs(got - want) <= tol,
            ))

    # A spec with no answer cells is unanswerable — never silently "correct".
    if not parts:
        return None
    return PartialGrade(parts, noun='cell')


def _table_row_label(row):
    """What to call a table row in feedback: its first ``given`` value, or ''."""
    for cell in row:
        kind = _table_cell_kind(cell)
        if kind and kind[0] == 'given':
            return str(kind[1]).strip()
    return ''


# ── sketch_spec (sketch a graph and state its key features) ───────────────────
# "Sketch the graph of y = x² + x − 2 showing the coordinates of the vertex, the
# x-axis and y-axis intercepts and the equation of the axis of symmetry."
#
# The student cannot draw a curve in this app, and a hand-drawn parabola is not
# what such a question is actually marked on: the marks are for the KEY FEATURES
# named in the stem. So the app draws the blank plane the worksheet printed and
# takes one typed value per feature — the vertex, the intercepts, the axis of
# symmetry — and grades each one. That makes the whole family of "sketch the
# graph showing…" questions answerable and auto-marked instead of being routed
# to the teacher as an un-gradeable drawing (worksheets.services rule 17).
#
# Feature values are NOT integers: the vertex of y = x² + x − 2 is (−½, −2¼), so
# everything here parses and compares decimals (and the fractions a pupil writes
# them as) within a tolerance, the way ``measure`` does.
SKETCH_FEATURE_KINDS = ('vertex', 'x_intercept', 'y_intercept', 'axis_of_symmetry')

# What each feature is called on the student's screen and in feedback. The
# labels are the worksheet's own words so a pupil can match box to question.
SKETCH_FEATURE_LABELS = {
    'vertex': 'Vertex (turning point)',
    'x_intercept': 'x-axis intercept(s)',
    'y_intercept': 'y-axis intercept',
    'axis_of_symmetry': 'Equation of the axis of symmetry',
}

# Features whose answer is a coordinate (or several); the odd one out is
# axis_of_symmetry, which is a vertical line "x = a" and carries a single value.
SKETCH_POINT_KINDS = ('vertex', 'x_intercept', 'y_intercept')

# A parabola crosses the x-axis at most twice; a spec listing more coordinates
# than this for one feature is a mis-read, not a question.
_MAX_SKETCH_POINTS = 4

# Default ± band for a typed feature value. Small on purpose: the answers are
# exact numbers the student works out (−0.5, −2.25), not measurements. It exists
# so a value written to a sensible number of places still marks correct.
DEFAULT_SKETCH_TOLERANCE = Decimal('0.01')

# One number as a pupil writes it: "3", "-0.5", "-1/2", "-2 1/4", "+4".
_SKETCH_NUM = r'[-+]?\d+(?:\s+\d+\s*/\s*\d+|\s*/\s*\d+|\.\d+)?'
_SKETCH_PAIR_RE = re.compile(
    r'\(?\s*(' + _SKETCH_NUM + r')\s*,\s*(' + _SKETCH_NUM + r')\s*\)?'
)
_SKETCH_NUM_RE = re.compile(_SKETCH_NUM)


def sketch_number(raw):
    """Parse one typed number into a ``Decimal``, or ``None``.

    Accepts the forms a pupil actually writes a non-integer answer in: a decimal
    (``-2.25``), a vulgar fraction (``-9/4``, ``- 1/2``) and a mixed number
    (``-2 1/4``). ``_to_decimal`` cannot: it strips ``/`` along with the units,
    turning ``-9/4`` into ``-94``. Vertices of the quadratics these questions use
    are quarters and halves far more often than whole numbers, so a grader that
    only reads decimals marks a correct fraction wrong.

    Returns ``None`` for anything unparseable (including division by zero) —
    never raises, so a malformed answer is wrong, not a 500.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace('−', '-')  # unicode minus → ASCII
    m = re.fullmatch(r'\s*(' + _SKETCH_NUM + r')\s*', text)
    if not m:
        return None
    return _sketch_number_from_token(m.group(1))


def _sketch_number_from_token(token):
    """``Decimal`` for one token already matched by ``_SKETCH_NUM``, or None.

    The three written forms are kept apart deliberately: "2 1/4" is two and a
    quarter, not twenty-one quarters, and collapsing the space would silently
    turn one into the other.
    """
    token = str(token).strip()
    sign = -1 if token.startswith('-') else 1
    token = token.lstrip('+-').strip()
    try:
        mixed = re.fullmatch(r'(\d+)\s+(\d+)\s*/\s*(\d+)', token)
        if mixed:
            whole, num, denom = (Decimal(mixed.group(i)) for i in (1, 2, 3))
            if denom == 0:
                return None
            return sign * (whole + num / denom)
        fraction = re.fullmatch(r'(\d+)\s*/\s*(\d+)', token)
        if fraction:
            num, denom = Decimal(fraction.group(1)), Decimal(fraction.group(2))
            if denom == 0:
                return None
            return sign * (num / denom)
        return sign * Decimal(token)
    except (InvalidOperation, ValueError):
        return None


def parse_sketch_points(text):
    """Parse typed coordinates into a list of ``(Decimal, Decimal)`` pairs.

    The decimal sibling of :func:`parse_coords`: tolerant of ``(-2, 0) (1, 0)``,
    ``(-2,0), (1,0)``, ``-2,0; 1,0`` and of fractional coordinates
    (``(-1/2, -9/4)``). Returns ``[]`` for anything unparseable — never raises.
    """
    if not isinstance(text, str):
        return []
    out = []
    for m in _SKETCH_PAIR_RE.finditer(text.replace('−', '-')):
        x = _sketch_number_from_token(m.group(1))
        y = _sketch_number_from_token(m.group(2))
        if x is None or y is None:
            continue
        out.append((x, y))
    return out


def parse_axis_of_symmetry(text):
    """The ``a`` of a typed axis of symmetry ``x = a``, as a ``Decimal`` or None.

    Accepts ``x = -0.5``, ``x=-1/2`` and the bare value ``-0.5`` — the equation
    is what the question asks for, but a pupil who writes only the number has
    given the same answer and should not lose the mark for the ``x =``.
    """
    if not isinstance(text, str):
        return None
    body = text.replace('−', '-').strip()
    # Drop a leading "x =" / "X:" and anything before an equals sign.
    if '=' in body:
        body = body.split('=')[-1]
    body = body.strip().lstrip('xX').strip().lstrip(':').strip()
    return sketch_number(body)


def _fmt_sketch_number(value):
    """Format a spec number compactly: ``-2.25``, ``-2``, ``0.5``."""
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return str(value)
    text = format(d.normalize(), 'f')
    return text if text != '-0' else '0'


def _fmt_sketch_point(point):
    return f'({_fmt_sketch_number(point[0])}, {_fmt_sketch_number(point[1])})'


def sketch_feature_expected(feature):
    """What a feature's correct answer looks like written out, e.g. ``(-2, 0), (1, 0)``.

    Shared by the grader's feedback and the answer figure so the value a student
    is told they should have written is the same one the drawing labels.
    """
    kind = (feature or {}).get('kind')
    if kind == 'axis_of_symmetry':
        return f"x = {_fmt_sketch_number(feature.get('value'))}"
    points = feature.get('points') or []
    return ', '.join(_fmt_sketch_point(p) for p in points)


def _sketch_points(feature):
    """A point feature's coordinates as ``[(Decimal, Decimal), ...]``, or None."""
    raw = feature.get('points')
    if not isinstance(raw, list) or not raw:
        return None
    out = []
    for p in raw:
        if not (isinstance(p, (list, tuple)) and len(p) == 2):
            return None
        x, y = _to_decimal_strict(p[0]), _to_decimal_strict(p[1])
        if x is None or y is None:
            return None
        out.append((x, y))
    return out


def _to_decimal_strict(value):
    """``Decimal`` for a spec number (int/float/numeric string), else ``None``.

    Stricter than ``_to_decimal``, which strips stray characters out of a
    student's typing: a spec value is authored data, so ``"3cm"`` is a defect to
    reject, not a 3 to guess at.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, str):
        return sketch_number(value)
    return None


def validate_sketch_spec(sketch_spec):
    """Validate a ``sketch_graph`` ``sketch_spec``; raise ``ValueError`` if bad.

    Pure and framework-agnostic (no Django import) so the model's ``clean()``
    and every importer share one definition of a usable spec — a malformed one
    cannot slip in through any path. Mirrors ``validate_table_spec``.

    Shape::

        {"equation": "y = x^2 + x - 2",
         "bounds": {"xmin": -6, "xmax": 6, "ymin": -4, "ymax": 8},
         "curve": {"type": "quadratic", "a": 1, "b": 1, "c": -2},
         "features": [{"kind": "vertex", "points": [[-0.5, -2.25]]},
                      {"kind": "x_intercept", "points": [[-2, 0], [1, 0]]},
                      {"kind": "y_intercept", "points": [[0, -2]]},
                      {"kind": "axis_of_symmetry", "value": -0.5}],
         "tolerance": 0.01}

    ``features`` is what the question asks the student to show, in the order the
    boxes appear; every one must be answerable, so each carries the value it is
    marked against. ``curve`` is optional and render-only — it lets the result
    page draw the curve the sketch should have been.
    """
    if not isinstance(sketch_spec, dict):
        raise ValueError('sketch_spec must be a JSON object.')

    equation = sketch_spec.get('equation')
    if equation is not None and not isinstance(equation, str):
        raise ValueError('sketch_spec.equation must be a string.')

    bounds = _plane_bounds(sketch_spec)
    if bounds is None:
        raise ValueError(
            'sketch_spec.bounds must have integer xmin<xmax and ymin<ymax.'
        )
    xmin, xmax, ymin, ymax = bounds
    # Same cap as a plane question: cartesian_plane_svg draws this backdrop and
    # bails out above it, so a spec that cannot be drawn must not be stored.
    if (xmax - xmin) > _MAX_PLANE_SPAN or (ymax - ymin) > _MAX_PLANE_SPAN:
        raise ValueError(
            f'sketch_spec bounds span must not exceed {_MAX_PLANE_SPAN} units per axis.'
        )

    features = sketch_spec.get('features')
    if not isinstance(features, list) or not features:
        raise ValueError('sketch_spec.features must be a non-empty list.')

    seen = set()
    for feature in features:
        if not isinstance(feature, dict):
            raise ValueError('sketch_spec.features entries must be objects.')
        kind = feature.get('kind')
        if kind not in SKETCH_FEATURE_KINDS:
            raise ValueError(
                f'sketch_spec feature kind must be one of {SKETCH_FEATURE_KINDS}; '
                f'got {kind!r}.'
            )
        if kind in seen:
            raise ValueError(f'sketch_spec lists the {kind} feature twice.')
        seen.add(kind)

        if kind == 'axis_of_symmetry':
            value = _to_decimal_strict(feature.get('value'))
            if value is None:
                raise ValueError(
                    'sketch_spec axis_of_symmetry needs a numeric "value" '
                    '(the a of x = a).'
                )
            if not (xmin <= value <= xmax):
                raise ValueError(
                    f'sketch_spec axis of symmetry x = {value} is outside the '
                    f'plane bounds.'
                )
            continue

        points = _sketch_points(feature)
        if points is None:
            raise ValueError(
                f'sketch_spec {kind} needs a non-empty "points" list of numeric '
                f'[x, y] pairs.'
            )
        if len(points) > _MAX_SKETCH_POINTS:
            raise ValueError(
                f'sketch_spec {kind} must not list more than '
                f'{_MAX_SKETCH_POINTS} points.'
            )
        for x, y in points:
            if not (xmin <= x <= xmax and ymin <= y <= ymax):
                raise ValueError(
                    f'sketch_spec {kind} point ({x}, {y}) is outside the plane bounds.'
                )
        # A y-axis intercept sits ON the y-axis and an x-axis intercept ON the
        # x-axis. Getting that wrong means the extractor read the wrong number,
        # and the student would be marked against it.
        if kind == 'y_intercept':
            if len(points) != 1:
                raise ValueError('sketch_spec y_intercept must list exactly one point.')
            if points[0][0] != 0:
                raise ValueError('sketch_spec y_intercept must have x = 0.')
        if kind == 'x_intercept' and any(y != 0 for _x, y in points):
            raise ValueError('sketch_spec x_intercept points must have y = 0.')
        if kind == 'vertex' and len(points) != 1:
            raise ValueError('sketch_spec vertex must list exactly one point.')

    curve = sketch_spec.get('curve')
    if curve is not None:
        _validate_sketch_curve(curve)

    tol = sketch_spec.get('tolerance')
    if tol is not None and (not _is_number(tol) or tol < 0):
        raise ValueError('sketch_spec.tolerance must be a non-negative number.')


# Curve families the answer figure can redraw from coefficients. Kept small on
# purpose: an equation the app cannot draw is still a perfectly gradeable
# question (the features carry the marks), so ``curve`` stays optional.
_SKETCH_CURVE_COEFFS = {
    'quadratic': ('a', 'b', 'c'),   # y = ax² + bx + c
    'linear': ('m', 'c'),           # y = mx + c
}


def _validate_sketch_curve(curve):
    if not isinstance(curve, dict):
        raise ValueError('sketch_spec.curve must be a JSON object.')
    ctype = curve.get('type')
    if ctype not in _SKETCH_CURVE_COEFFS:
        raise ValueError(
            f'sketch_spec.curve.type must be one of '
            f'{tuple(_SKETCH_CURVE_COEFFS)}; got {ctype!r}.'
        )
    for name in _SKETCH_CURVE_COEFFS[ctype]:
        if _to_decimal_strict(curve.get(name)) is None:
            raise ValueError(f'sketch_spec.curve.{name} must be a number.')
    if ctype == 'quadratic' and _to_decimal_strict(curve.get('a')) == 0:
        raise ValueError('sketch_spec.curve.a must not be zero for a quadratic.')


def sketch_tolerance(sketch_spec):
    """The ± band a sketch's typed values are marked within, as a ``Decimal``."""
    tol = (sketch_spec or {}).get('tolerance')
    if tol is None:
        return DEFAULT_SKETCH_TOLERANCE
    try:
        value = Decimal(str(tol))
    except (InvalidOperation, ValueError, TypeError):
        return DEFAULT_SKETCH_TOLERANCE
    return value if value >= 0 else DEFAULT_SKETCH_TOLERANCE


# ── the sketch itself: the curve the student draws ────────────────────────────
# "Sketch the graph … showing the vertex and the intercepts" asks for two things,
# and the app used to take only one of them. The named features were typed into
# boxes; the CURVE — the thing the verb "sketch" actually names — had nowhere to
# go, so the plane sat inert beside the boxes and a pupil told to sketch a graph
# could not sketch anything. They now plot lattice points on that plane (the
# widget joins them into a smooth curve, the way a plot_points question does),
# and this is where those points are marked.
#
# What is asked of the sketch is what a teacher asks of one on paper: enough
# points, every one of them on the curve, and — for a parabola — points either
# side of the turn, because three dots up one arm do not show its shape.

SKETCH_DRAWING_LABEL = 'The sketch (points on the curve)'

# How far off the curve one plotted point may sit, in plane units. Half a square:
# the points are LATTICE points, so where the curve passes between two of them
# the nearer one must still count. Per-question override: ``curve_tolerance``.
DEFAULT_SKETCH_CURVE_TOLERANCE = Decimal('0.5')

# How many points make a sketch: a parabola needs three (an arm, the turn, the
# other arm), a straight line is fixed by two.
_MIN_DRAWING_POINTS = {'quadratic': 3, 'linear': 2}

# Plotted points beyond this are a scribble, not a sketch, and only slow the
# page down. The widget stops accepting them at the same count.
MAX_DRAWN_POINTS = 40


def sketch_curve_value(curve, x):
    """The curve's y at ``x`` as a ``Decimal``, or ``None`` if it won't evaluate.

    The one definition of what these curves ARE — the families
    ``validate_sketch_spec`` accepts, a quadratic ``y = ax² + bx + c`` and a line
    ``y = mx + c``. The grader marks the student's points against this and
    ``svg_geometry.sketch_curve_y`` samples the drawn curve from it, so the mark
    and the picture can never disagree about where the curve goes.
    """
    if not isinstance(curve, dict):
        return None
    xd = _to_decimal_strict(x)
    if xd is None:
        return None
    coeffs = {}
    for name in _SKETCH_CURVE_COEFFS.get(curve.get('type'), ()):
        value = _to_decimal_strict(curve.get(name))
        if value is None:
            return None
        coeffs[name] = value
    if curve.get('type') == 'quadratic':
        return coeffs['a'] * xd * xd + coeffs['b'] * xd + coeffs['c']
    if curve.get('type') == 'linear':
        return coeffs['m'] * xd + coeffs['c']
    return None


def sketch_curve_tolerance(sketch_spec):
    """The ± band, in plane units, a plotted point is allowed off the curve."""
    raw = (sketch_spec or {}).get('curve_tolerance')
    if raw is None:
        return DEFAULT_SKETCH_CURVE_TOLERANCE
    value = _to_decimal_strict(raw)
    if value is None or value < 0:
        return DEFAULT_SKETCH_CURVE_TOLERANCE
    return value


def sketch_curve(sketch_spec):
    """The curve this sketch is of: the stored ``curve``, else one derived.

    ``curve`` is optional in a spec and an importer often leaves it out, but
    without it there is nothing for a drawn sketch to be right or wrong against.
    The features carry enough to recover it — a parabola is fixed by its vertex
    and any second point on it, a line by its two intercepts — so a spec that
    names them is sketchable whether or not the coefficients were written down.

    A stored curve wins (it is what the author meant, and what the answer figure
    already draws). Returns ``None`` when neither is available, which is the
    signal to leave the plane un-plottable rather than mark a student against a
    curve nobody knows.
    """
    if not isinstance(sketch_spec, dict):
        return None
    curve = sketch_spec.get('curve')
    if isinstance(curve, dict):
        try:
            _validate_sketch_curve(curve)
        except ValueError:
            curve = None   # unusable as authored — derive one instead
        else:
            return curve
    return _curve_from_features(sketch_spec)


def _sketch_feature_points(sketch_spec):
    """``{kind: [(x, y), ...]}`` for the spec's point features, skipping bad ones."""
    out = {}
    for feature in (sketch_spec.get('features') or []):
        if not isinstance(feature, dict):
            continue
        kind = feature.get('kind')
        if kind not in SKETCH_POINT_KINDS:
            continue
        points = _sketch_points(feature)
        if points:
            out[kind] = points
    return out


def _curve_from_features(sketch_spec):
    """Recover the curve's coefficients from the features, or ``None``.

    Three cases, in the order they identify a curve unambiguously:

    * vertex ``(h, k)`` + any second point ``(x₀, y₀)`` with ``x₀ ≠ h`` →
      ``a = (y₀ − k)/(x₀ − h)²``, and ``y = a(x − h)² + k`` expanded.
    * both roots ``r₁, r₂`` + the y-intercept ``(0, c)``, ``r₁r₂ ≠ 0`` →
      ``a = c/(r₁r₂)`` and ``y = a(x − r₁)(x − r₂)``.
    * one root ``(r, 0)`` + the y-intercept ``(0, c)``, ``r ≠ 0``, and no vertex
      → the line ``y = (−c/r)x + c``.
    """
    features = _sketch_feature_points(sketch_spec)
    vertex = (features.get('vertex') or [None])[0]
    y_int = (features.get('y_intercept') or [None])[0]
    roots = features.get('x_intercept') or []

    if vertex is not None:
        h, k = vertex
        for x0, y0 in ([y_int] if y_int else []) + list(roots):
            if x0 == h:
                continue     # the same point again fixes nothing
            a = (y0 - k) / ((x0 - h) ** 2)
            if a == 0:
                continue     # a flat "parabola" is not one; try another point
            return {'type': 'quadratic', 'a': float(a),
                    'b': float(-2 * a * h), 'c': float(a * h * h + k)}
        return None

    if y_int is not None:
        c = y_int[1]
        if len(roots) >= 2:
            r1, r2 = roots[0][0], roots[1][0]
            if r1 != r2 and r1 * r2 != 0:
                a = c / (r1 * r2)
                if a != 0:
                    return {'type': 'quadratic', 'a': float(a),
                            'b': float(-a * (r1 + r2)), 'c': float(c)}
        if len(roots) == 1 and roots[0][0] != 0:
            return {'type': 'linear', 'm': float(-c / roots[0][0]),
                    'c': float(c)}
    return None


def sketch_axis_x(sketch_spec, curve):
    """The x the curve turns at, as a ``Decimal``, or ``None`` if it doesn't.

    Prefers what the spec says (the vertex, then the axis of symmetry) over
    ``-b/2a``, so a sketch is marked against the same turning point the boxes
    are.
    """
    vertex = (_sketch_feature_points(sketch_spec).get('vertex') or [None])[0]
    if vertex is not None:
        return vertex[0]
    for feature in (sketch_spec.get('features') or []):
        if isinstance(feature, dict) and feature.get('kind') == 'axis_of_symmetry':
            value = _to_decimal_strict(feature.get('value'))
            if value is not None:
                return value
    if isinstance(curve, dict) and curve.get('type') == 'quadratic':
        a = _to_decimal_strict(curve.get('a'))
        b = _to_decimal_strict(curve.get('b'))
        if a not in (None, 0) and b is not None:
            return -b / (2 * a)
    return None


def sketch_plottable_points(sketch_spec, curve=None):
    """Every lattice point of the plane a correct sketch could be plotted on.

    One per whole-number x whose curve value is inside the plane and within
    tolerance of a whole-number y — the points the student can actually tap.
    Doubles as the check that the sketch is answerable AT ALL: a curve that
    leaves the grid almost at once offers too few to sketch with, and a question
    that cannot be sketched must not be marked as though it could be.
    """
    curve = curve if curve is not None else sketch_curve(sketch_spec)
    bounds = _plane_bounds(sketch_spec)
    if not curve or bounds is None:
        return []
    xmin, xmax, ymin, ymax = bounds
    tol = sketch_curve_tolerance(sketch_spec)
    out = []
    for x in range(xmin, xmax + 1):
        y = sketch_curve_value(curve, x)
        if y is None:
            return []
        nearest = int((y + Decimal('0.5')).to_integral_value(rounding=ROUND_FLOOR))
        if abs(y - nearest) <= tol and ymin <= nearest <= ymax:
            out.append((Decimal(x), Decimal(nearest)))
    return out


def parse_drawn_points(raw):
    """The ``points`` of a sketch payload as ``[(Decimal, Decimal), ...]``.

    Anything malformed is DROPPED rather than raised on: a stray entry must not
    cost a student the features they typed beside it.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw[:MAX_DRAWN_POINTS]:
        if not (isinstance(item, (list, tuple)) and len(item) == 2):
            continue
        x, y = _to_decimal_strict(item[0]), _to_decimal_strict(item[1])
        if x is None or y is None:
            continue
        if (x, y) not in out:
            out.append((x, y))
    return out


def sketch_drawing_part(sketch_spec, drawn, curve=None):
    """The student's drawn sketch as one graded ``Part``, or ``None``.

    ``None`` — no part, no mark either way — when the question cannot be
    sketched: no curve to mark against, or too few lattice points on it inside
    the plane to make a sketch out of. Everything else is graded:

    * enough points (three for a curve, two for a line),
    * every one of them on the curve and inside the plane, within
      ``curve_tolerance``,
    * and, for a parabola whose plane shows both arms, points either side of the
      turning point.
    """
    from maths.partial_credit import Part

    curve = curve if curve is not None else sketch_curve(sketch_spec)
    bounds = _plane_bounds(sketch_spec)
    targets = sketch_plottable_points(sketch_spec, curve)
    needed = _MIN_DRAWING_POINTS.get((curve or {}).get('type'), 3)
    if bounds is None or len(targets) < needed:
        return None
    xmin, xmax, ymin, ymax = bounds

    axis_x = sketch_axis_x(sketch_spec, curve)
    both_arms = (
        curve.get('type') == 'quadratic' and axis_x is not None
        and any(x < axis_x for x, _y in targets)
        and any(x > axis_x for x, _y in targets)
    )

    tol = sketch_curve_tolerance(sketch_spec)
    on_curve = []
    off_curve = False
    for x, y in drawn:
        want = sketch_curve_value(curve, x)
        on_plane = xmin <= x <= xmax and ymin <= y <= ymax
        if not on_plane or want is None or abs(y - want) > tol:
            off_curve = True
        else:
            on_curve.append((x, y))

    xs = {x for x, _y in on_curve}
    is_correct = (
        not off_curve
        and len(xs) >= needed
        and (not both_arms
             or (any(x < axis_x for x in xs) and any(x > axis_x for x in xs)))
    )

    if both_arms:
        expected = (f'{needed} or more points on the curve, either side of '
                    f'x = {_fmt_sketch_number(axis_x)} — e.g. '
                    + ', '.join(_fmt_sketch_point(p) for p in targets[:5]))
    else:
        expected = (f'{needed} or more points on the curve — e.g. '
                    + ', '.join(_fmt_sketch_point(p) for p in targets[:5]))

    return Part(
        label=SKETCH_DRAWING_LABEL,
        typed=', '.join(_fmt_sketch_point(p) for p in drawn),
        expected=expected,
        is_correct=is_correct,
    )


def _points_match(want, got, tol):
    """True when two coordinate lists are the same set within ``tol``.

    Order-insensitive (the two x-intercepts may be written either way round) and
    one-to-one: a student who writes the same root twice has not given both.
    """
    if len(want) != len(got):
        return False
    remaining = list(got)
    for wx, wy in want:
        for i, (gx, gy) in enumerate(remaining):
            if abs(gx - wx) <= tol and abs(gy - wy) <= tol:
                del remaining[i]
                break
        else:
            return False
    return True


def grade_sketch_parts(sketch_spec, payload):
    """Grade a ``sketch_graph`` answer feature by feature, for partial credit.

    Returns a :class:`~maths.partial_credit.PartialGrade` — one
    :class:`~maths.partial_credit.Part` per feature the question asks for, in
    the order the boxes appear, labelled the way they are labelled on screen
    ("Vertex (turning point)") so a wrong one can be pointed at. Returns
    ``None`` when there is nothing to grade against: a malformed spec, a
    malformed payload, or a spec with no usable features.

    A student who finds the intercepts but misses the vertex has shown three
    quarters of the question, so each feature is one part and is worth its
    share — the same rule as a table of values. Never raises.

    The SKETCH is one more part, first, whenever the question can be sketched
    (:func:`sketch_drawing_part`) — the drawing is what the stem asks for, and
    marking only the boxes beside it left the verb "sketch" worth nothing.

    ``payload`` is the JSON the client serialises,
    ``{"features": {"vertex": "(-0.5, -2.25)", ...}, "points": [[-2, 5], ...]}``
    — the typed boxes keyed by feature kind, and the points plotted on the plane.
    """
    from maths.partial_credit import Part, PartialGrade

    if not isinstance(sketch_spec, dict):
        return None
    features = sketch_spec.get('features')
    if not isinstance(features, list) or not features:
        return None

    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    typed_map = data.get('features')
    if not isinstance(typed_map, dict):
        return None

    tol = sketch_tolerance(sketch_spec)

    parts = []
    drawing = sketch_drawing_part(sketch_spec, parse_drawn_points(data.get('points')))
    if drawing is not None:
        parts.append(drawing)
    for feature in features:
        if not isinstance(feature, dict):
            return None
        kind = feature.get('kind')
        if kind not in SKETCH_FEATURE_KINDS:
            return None
        typed = typed_map.get(kind)
        typed_text = '' if typed is None else str(typed)

        if kind == 'axis_of_symmetry':
            want = _to_decimal_strict(feature.get('value'))
            if want is None:
                # An unanswerable feature is a content defect: there is no
                # honest fraction to award, so no part-grade at all.
                return None
            got = parse_axis_of_symmetry(typed_text)
            is_correct = got is not None and abs(got - want) <= tol
        else:
            want_points = _sketch_points(feature)
            if want_points is None:
                return None
            got_points = parse_sketch_points(typed_text)
            is_correct = bool(got_points) and _points_match(want_points, got_points, tol)

        parts.append(Part(
            label=SKETCH_FEATURE_LABELS.get(kind, kind.replace('_', ' ').title()),
            typed=typed_text,
            expected=sketch_feature_expected(feature),
            is_correct=is_correct,
        ))

    if not parts:
        return None
    return PartialGrade(parts, noun='feature')


def grade_sketch(sketch_spec, payload):
    """Grade a ``sketch_graph`` answer. Returns ``True``/``False``, never raises.

    Correct only when EVERY feature the question asks for is right — the
    boolean view of :func:`grade_sketch_parts`, which marks the same features
    one at a time so three of four earns three quarters rather than nothing.
    """
    grade = grade_sketch_parts(sketch_spec, payload)
    return grade is not None and grade.is_correct


def describe_sketch_answer(payload, sketch_spec=None):
    """A student's ``sketch_graph`` payload as readable text for review surfaces.

    ``{"features": {"vertex": "(-0.5, -2.25)"}}`` →
    ``"Vertex (turning point): (-0.5, -2.25)"``. Follows the spec's feature
    order when one is given, so the review list reads in the same order as the
    boxes the student filled in; a feature left empty shows as "—" rather than
    vanishing, so a partly-answered question reads as partly answered. Returns
    the raw payload unchanged when it isn't a features payload at all, so a
    review page that calls this on every typed answer still shows something
    truthful rather than nothing.
    """
    try:
        data = json.loads(payload) if isinstance(payload, str) else payload
    except (ValueError, TypeError):
        return payload if isinstance(payload, str) else ''
    if not isinstance(data, dict) or not isinstance(data.get('features'), dict):
        return payload if isinstance(payload, str) else ''
    typed = data['features']

    kinds = [f.get('kind') for f in (sketch_spec or {}).get('features') or []
             if isinstance(f, dict)]
    kinds = [k for k in kinds if k in SKETCH_FEATURE_KINDS]
    if not kinds:
        kinds = [k for k in SKETCH_FEATURE_KINDS if k in typed]

    out = [
        f'{SKETCH_FEATURE_LABELS.get(k, k)}: '
        f'{(str(typed.get(k) or "").strip() or "—")}'
        for k in kinds
    ]
    # The sketch itself, when they plotted one. A review page that showed only
    # the typed boxes would report a student who drew the curve as having drawn
    # nothing.
    drawn = parse_drawn_points(data.get('points'))
    if drawn:
        out.insert(0, f'{SKETCH_DRAWING_LABEL}: '
                      + ', '.join(_fmt_sketch_point(p) for p in drawn))
    return '; '.join(out)


def describe_sketch_spec(sketch_spec):
    """The correct features as readable text, e.g. ``"Vertex …: (-0.5, -2.25); …"``.

    The counterpart of :func:`describe_sketch_answer` for the answer side, so a
    result page can print what the sketch should have shown. These questions
    store no Answer rows — the values live in the spec — so without this the
    student is shown a blank where the correct answer belongs.
    """
    if not isinstance(sketch_spec, dict):
        return ''
    out = []
    for feature in (sketch_spec.get('features') or []):
        if not isinstance(feature, dict):
            continue
        kind = feature.get('kind')
        if kind not in SKETCH_FEATURE_KINDS:
            continue
        out.append(f'{SKETCH_FEATURE_LABELS[kind]}: {sketch_feature_expected(feature)}')
    return '; '.join(out)
