"""Programmatic SVG figures for geometry/measurement questions (CPP-330).

CPP-333 renders a `measure` angle from its stored value, so authors never
upload an image and the printed figure is guaranteed true-to-scale: the
angle between the two drawn rays is exactly the requested degrees,
independent of render size (the SVG uses a viewBox, no rasterisation).

Pure functions — value in, SVG/coords out — no DB, no request.
"""
import math
import re

from maths.geometry_grading import SHAPE_TYPES, shape_geometry_form


def angle_ray_points(degrees, *, size=240):
    """Return ``(vertex, baseline_end, ray_end)`` for an angle figure.

    The vertex sits low-centre. One ray (the baseline) runs horizontally to
    the right; the second is rotated ``degrees`` counter-clockwise from it.
    Coordinates are in SVG user units (y grows downward). Factored out of
    ``angle_svg`` so the geometry is unit-testable without parsing SVG.
    """
    theta = math.radians(float(degrees))
    cx, cy = size * 0.5, size * 0.8
    length = size * 0.4
    vertex = (cx, cy)
    baseline_end = (cx + length, cy)
    ray_end = (cx + length * math.cos(theta), cy - length * math.sin(theta))
    return vertex, baseline_end, ray_end


def _f(n):
    """Format a coordinate compactly (2 dp, no trailing zeros)."""
    return f'{n:.2f}'.rstrip('0').rstrip('.')


def angle_svg(degrees, *, size=240, label='a'):
    """Return an inline SVG string for an angle of ``degrees`` degrees.

    Two rays meet at a vertex with a small arc near the vertex labelled
    ``label``. ``degrees`` may be int, float, or Decimal. The figure is
    resolution-independent (viewBox) so it prints true-to-scale.
    """
    deg = float(degrees)
    (vx, vy), (bx, by), (rx, ry) = angle_ray_points(deg, size=size)

    # Arc near the vertex, from the baseline round to the second ray.
    r = size * 0.13
    arc_start = (vx + r, vy)
    theta = math.radians(deg)
    arc_end = (vx + r * math.cos(theta), vy - r * math.sin(theta))
    large_arc = 1 if deg > 180 else 0
    # y is flipped in SVG, so a visually counter-clockwise sweep is flag 0.
    sweep = 0

    # Label at the mid-angle, just outside the arc.
    mid = math.radians(deg / 2)
    lr = r + size * 0.07
    lx = vx + lr * math.cos(mid)
    ly = vy - lr * math.sin(mid)

    stroke = 'var(--svg-stroke, #1a1a1a)'
    return (
        f'<svg viewBox="0 0 {size} {size}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Angle of {_f(deg)} degrees to measure">'
        f'<g fill="none" stroke="{stroke}" stroke-width="2" '
        f'stroke-linecap="round">'
        f'<path d="M {_f(bx)} {_f(by)} L {_f(vx)} {_f(vy)} L {_f(rx)} {_f(ry)}"/>'
        f'<path d="M {_f(arc_start[0])} {_f(arc_start[1])} '
        f'A {_f(r)} {_f(r)} 0 {large_arc} {sweep} '
        f'{_f(arc_end[0])} {_f(arc_end[1])}"/>'
        f'</g>'
        f'<text x="{_f(lx)}" y="{_f(ly)}" fill="{stroke}" '
        f'font-size="{_f(size * 0.09)}" font-style="italic" '
        f'text-anchor="middle" dominant-baseline="middle">{label}</text>'
        f'</svg>'
    )


def _shape_inner(shape):
    """Return the SVG element for one ``shape_select`` shape, or '' if malformed.

    Handles all three geometry forms (parametric centre+size from the generator,
    traced ``points`` polygons, traced ``rx``/``ry`` ellipses — see
    ``shape_geometry_form``). Defensive on purpose — a spec that bypassed
    ``validate_shape_spec`` (raw admin JSON, a hand-edited fixture) must not 500
    the take-item render, so a bad shape is simply skipped. The element carries
    ``data-shape-id`` / ``data-shape-type`` and the ``cwa-shape`` class so the
    take-item JS can toggle its fill and collect the coloured ids.
    ``fill="transparent"`` keeps the outline tappable before it's coloured.
    """
    if not isinstance(shape, dict) or not isinstance(shape.get('id'), str):
        return ''
    stype = shape.get('type')
    # Only a safe token reaches the data attribute / markup — generated ids are
    # ``s0``/``s1`` … so this never mangles a legitimate id.
    sid = re.sub(r'[^A-Za-z0-9_-]', '', shape['id'])
    if not sid or stype not in SHAPE_TYPES:
        return ''

    stroke = 'var(--svg-stroke, #1a1a1a)'
    base = (
        f'class="cwa-shape" data-shape-id="{sid}" data-shape-type="{stype}" '
        f'fill="transparent" stroke="{stroke}" stroke-width="2" '
        f'tabindex="0" role="button" aria-label="{stype}"'
    )
    form = shape_geometry_form(shape)
    try:
        if form == 'polygon':
            pts = [(float(p[0]), float(p[1])) for p in shape['points']]
            return _poly(pts, base) if len(pts) >= 3 else ''
        if form == 'ellipse':
            cx, cy = float(shape['cx']), float(shape['cy'])
            rx, ry = float(shape['rx']), float(shape['ry'])
            rot = float(shape.get('rot', 0))
            if rx <= 0 or ry <= 0:
                return ''
            spin = f' transform="rotate({_f(rot)} {_f(cx)} {_f(cy)})"' if rot else ''
            return (f'<ellipse cx="{_f(cx)}" cy="{_f(cy)}" rx="{_f(rx)}" '
                    f'ry="{_f(ry)}" {base}{spin}/>')
        # parametric (generator)
        cx, cy, s = float(shape['cx']), float(shape['cy']), float(shape['size'])
        rot = float(shape.get('rot', 0))
        if s <= 0:
            return ''
        common = f'{base} transform="rotate({_f(rot)} {_f(cx)} {_f(cy)})"'
        return _SHAPE_GEOMETRY[stype](cx, cy, s, common)
    except (KeyError, TypeError, ValueError, IndexError):
        return ''


def _poly(points, common):
    pts = ' '.join(f'{_f(x)},{_f(y)}' for x, y in points)
    return f'<polygon points="{pts}" {common}/>'


# How each shape type maps (centre, size) → an SVG element. Proportions match
# the approved interactive prototype.
_SHAPE_GEOMETRY = {
    'circle': lambda cx, cy, s, c: f'<circle cx="{_f(cx)}" cy="{_f(cy)}" r="{_f(s)}" {c}/>',
    'ellipse': lambda cx, cy, s, c: (
        f'<ellipse cx="{_f(cx)}" cy="{_f(cy)}" rx="{_f(s * 1.45)}" ry="{_f(s * 0.8)}" {c}/>'
    ),
    'square': lambda cx, cy, s, c: (
        f'<rect x="{_f(cx - s)}" y="{_f(cy - s)}" width="{_f(2 * s)}" '
        f'height="{_f(2 * s)}" rx="2" {c}/>'
    ),
    'rectangle': lambda cx, cy, s, c: (
        f'<rect x="{_f(cx - s * 1.45)}" y="{_f(cy - s * 0.72)}" width="{_f(2 * s * 1.45)}" '
        f'height="{_f(2 * s * 0.72)}" rx="2" {c}/>'
    ),
    'triangle': lambda cx, cy, s, c: _poly(
        [(cx, cy - s), (cx - s, cy + s), (cx + s, cy + s)], c
    ),
    'rhombus': lambda cx, cy, s, c: _poly(
        [(cx, cy - s), (cx + s * 1.3, cy), (cx, cy + s), (cx - s * 1.3, cy)], c
    ),
}


def shape_select_svg(shape_spec):
    """Return the inner SVG markup (all shape elements) for a shape_select scene.

    Pure string builder — mirrors ``angle_svg``. The caller wraps these in an
    ``<svg viewBox=…>``. Returns '' for a spec with no renderable shapes, so the
    take-item template can guard with a single check.
    """
    if not isinstance(shape_spec, dict):
        return ''
    parts = [
        el for shape in (shape_spec.get('shapes') or [])
        if isinstance(shape, dict) and (el := _shape_inner(shape))
    ]
    return ''.join(parts)


def cartesian_plane_svg(plane_spec, *, pad=28, step=32):
    """Return the inner SVG markup for a signed Cartesian-plane backdrop.

    Draws the light grid, the bold x/y axes with arrowheads, integer tick labels,
    and a labelled origin — i.e. the static blank plane the pupil plots on. The
    *interactive* lattice hit-targets and any plotted/given points are overlaid
    by the take-item template (the same split as ``draw_on_grid``: SVG figure +
    template-rendered dots), so this function is pure backdrop.

    Returns '' for a malformed/oversized spec, so the model render helper can
    guard with a single check. ``pad``/``step`` must match the model's
    ``plane_data`` so backdrop and overlaid dots align.
    """
    from maths.geometry_grading import _plane_bounds
    bounds = _plane_bounds(plane_spec)
    if bounds is None:
        return ''
    xmin, xmax, ymin, ymax = bounds
    # Guard against an absurd plane that would emit thousands of grid lines.
    if (xmax - xmin) > 40 or (ymax - ymin) > 40:
        return ''

    def px(x):
        return pad + (x - xmin) * step

    def py(y):
        return pad + (ymax - y) * step  # y up on the plane, down in SVG

    left, right = px(xmin), px(xmax)
    top, bottom = py(ymax), py(ymin)
    grid = 'var(--svg-grid, #cfe8f5)'
    axis = 'var(--svg-axis, #1f6feb)'
    label = 'var(--svg-stroke, #1a1a1a)'
    fs = _f(step * 0.34)

    parts = []
    # Light grid lines (skip the axes — drawn bold below).
    for x in range(xmin, xmax + 1):
        parts.append(
            f'<line x1="{_f(px(x))}" y1="{_f(top)}" x2="{_f(px(x))}" y2="{_f(bottom)}" '
            f'stroke="{grid}" stroke-width="1"/>'
        )
    for y in range(ymin, ymax + 1):
        parts.append(
            f'<line x1="{_f(left)}" y1="{_f(py(y))}" x2="{_f(right)}" y2="{_f(py(y))}" '
            f'stroke="{grid}" stroke-width="1"/>'
        )

    # Bold axes (only when the origin is in range) with arrowheads.
    x0, y0 = px(0), py(0)
    if ymin <= 0 <= ymax:
        parts.append(
            f'<line x1="{_f(left)}" y1="{_f(y0)}" x2="{_f(right)}" y2="{_f(y0)}" '
            f'stroke="{axis}" stroke-width="2"/>'
            f'<polygon points="{_f(right)},{_f(y0)} {_f(right - 8)},{_f(y0 - 4)} '
            f'{_f(right - 8)},{_f(y0 + 4)}" fill="{axis}"/>'
            f'<text x="{_f(right)}" y="{_f(y0 - 8)}" fill="{label}" font-size="{fs}" '
            f'font-style="italic" text-anchor="end">x</text>'
        )
    if xmin <= 0 <= xmax:
        parts.append(
            f'<line x1="{_f(x0)}" y1="{_f(bottom)}" x2="{_f(x0)}" y2="{_f(top)}" '
            f'stroke="{axis}" stroke-width="2"/>'
            f'<polygon points="{_f(x0)},{_f(top)} {_f(x0 - 4)},{_f(top + 8)} '
            f'{_f(x0 + 4)},{_f(top + 8)}" fill="{axis}"/>'
            f'<text x="{_f(x0 + 8)}" y="{_f(top + 4)}" fill="{label}" font-size="{fs}" '
            f'font-style="italic">y</text>'
        )

    # Integer tick labels along the axes (skip 0; label the origin once).
    if ymin <= 0 <= ymax:
        for x in range(xmin, xmax + 1):
            if x == 0:
                continue
            parts.append(
                f'<text x="{_f(px(x))}" y="{_f(y0 + step * 0.5)}" fill="{label}" '
                f'font-size="{fs}" text-anchor="middle">{x}</text>'
            )
    if xmin <= 0 <= xmax:
        for y in range(ymin, ymax + 1):
            if y == 0:
                continue
            parts.append(
                f'<text x="{_f(x0 - step * 0.28)}" y="{_f(py(y) + step * 0.12)}" '
                f'fill="{label}" font-size="{fs}" text-anchor="end">{y}</text>'
            )
    if xmin <= 0 <= xmax and ymin <= 0 <= ymax:
        parts.append(
            f'<text x="{_f(x0 - step * 0.28)}" y="{_f(y0 + step * 0.5)}" '
            f'fill="{label}" font-size="{fs}" text-anchor="end">0</text>'
        )
    return ''.join(parts)


def line_graph_svg(graph_spec, *, width=420, height=300):
    """Return a complete inline ``<svg>`` for a read_graph line graph.

    Renders titled, labelled axes (with units), gridlines at each ``step``, and
    the plotted data series as a polyline with point markers — the pre-drawn
    graph the pupil reads a value off (e.g. a distance-vs-time race graph).
    Self-contained (its own viewBox, like ``angle_svg``) so the template renders
    it with ``{{ d.svg|safe }}``. Returns '' for a malformed spec, so the model
    render helper can guard and fall back to an uploaded image.
    """
    if not isinstance(graph_spec, dict):
        return ''
    xax, yax = graph_spec.get('x_axis'), graph_spec.get('y_axis')
    if not (isinstance(xax, dict) and isinstance(yax, dict)):
        return ''
    try:
        xmin, xmax = float(xax['min']), float(xax['max'])
        ymin, ymax = float(yax['min']), float(yax['max'])
    except (KeyError, TypeError, ValueError):
        return ''
    if xmin >= xmax or ymin >= ymax:
        return ''

    ml, mr, mt, mb = 56, 18, 34, 44   # plot-area margins (room for labels/title)
    pw, ph = width - ml - mr, height - mt - mb

    def sx(x):
        return ml + (x - xmin) / (xmax - xmin) * pw

    def sy(y):
        return mt + (ymax - y) / (ymax - ymin) * ph

    stroke = 'var(--svg-stroke, #1a1a1a)'
    grid = 'var(--svg-grid, #e2e8f0)'
    line = 'var(--svg-series, #dc2626)'

    def _ticks(lo, hi, step):
        try:
            step = float(step)
        except (TypeError, ValueError):
            step = 0
        if step <= 0 or (hi - lo) / step > 40:
            return [lo, hi]
        out, v = [], lo
        while v <= hi + 1e-9:
            out.append(round(v, 6))
            v += step
        return out

    parts = [
        f'<svg viewBox="0 0 {width} {height}" xmlns="http://www.w3.org/2000/svg" '
        f'role="img" aria-label="Line graph to read a value from" '
        f'style="width:100%;height:auto">'
    ]
    # Gridlines + tick labels.
    for x in _ticks(xmin, xmax, xax.get('step')):
        gx = sx(x)
        parts.append(
            f'<line x1="{_f(gx)}" y1="{_f(mt)}" x2="{_f(gx)}" y2="{_f(mt + ph)}" '
            f'stroke="{grid}" stroke-width="1"/>'
            f'<text x="{_f(gx)}" y="{_f(mt + ph + 16)}" fill="{stroke}" '
            f'font-size="10" text-anchor="middle">{_f(x)}</text>'
        )
    for y in _ticks(ymin, ymax, yax.get('step')):
        gy = sy(y)
        parts.append(
            f'<line x1="{_f(ml)}" y1="{_f(gy)}" x2="{_f(ml + pw)}" y2="{_f(gy)}" '
            f'stroke="{grid}" stroke-width="1"/>'
            f'<text x="{_f(ml - 6)}" y="{_f(gy + 3)}" fill="{stroke}" '
            f'font-size="10" text-anchor="end">{_f(y)}</text>'
        )
    # Axes.
    parts.append(
        f'<line x1="{_f(ml)}" y1="{_f(mt)}" x2="{_f(ml)}" y2="{_f(mt + ph)}" '
        f'stroke="{stroke}" stroke-width="1.5"/>'
        f'<line x1="{_f(ml)}" y1="{_f(mt + ph)}" x2="{_f(ml + pw)}" y2="{_f(mt + ph)}" '
        f'stroke="{stroke}" stroke-width="1.5"/>'
    )
    # Data series (polyline + markers).
    for s in (graph_spec.get('series') or []):
        if not isinstance(s, dict):
            continue
        pts = []
        for p in (s.get('points') or []):
            if (isinstance(p, (list, tuple)) and len(p) == 2
                    and all(isinstance(c, (int, float)) and not isinstance(c, bool) for c in p)):
                pts.append((sx(p[0]), sy(p[1])))
        if not pts:
            continue
        poly = ' '.join(f'{_f(x)},{_f(y)}' for x, y in pts)
        parts.append(
            f'<polyline points="{poly}" fill="none" stroke="{line}" stroke-width="2.5" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        for x, y in pts:
            parts.append(f'<circle cx="{_f(x)}" cy="{_f(y)}" r="3.5" fill="{line}"/>')

    # Title + axis labels (with units).
    title = _txt(graph_spec.get('title'))
    if title:
        parts.append(
            f'<text x="{_f(ml + pw / 2)}" y="18" fill="{stroke}" font-size="13" '
            f'font-weight="bold" text-anchor="middle">{title}</text>'
        )
    xlabel = _axis_label(xax)
    if xlabel:
        parts.append(
            f'<text x="{_f(ml + pw / 2)}" y="{_f(height - 6)}" fill="{stroke}" '
            f'font-size="11" text-anchor="middle">{xlabel}</text>'
        )
    ylabel = _axis_label(yax)
    if ylabel:
        cy = mt + ph / 2
        parts.append(
            f'<text x="14" y="{_f(cy)}" fill="{stroke}" font-size="11" '
            f'text-anchor="middle" transform="rotate(-90 14 {_f(cy)})">{ylabel}</text>'
        )
    parts.append('</svg>')
    return ''.join(parts)


def _txt(value):
    """Escape a short author string for safe inclusion in SVG text."""
    if not isinstance(value, str):
        return ''
    return (value.replace('&', '&amp;').replace('<', '&lt;')
            .replace('>', '&gt;').strip())


def _axis_label(axis):
    """Compose an axis caption like 'Distance (km)' from label + unit."""
    label = _txt(axis.get('label')) if isinstance(axis, dict) else ''
    unit = _txt(axis.get('unit')) if isinstance(axis, dict) else ''
    if label and unit:
        return f'{label} ({unit})'
    return label or unit
