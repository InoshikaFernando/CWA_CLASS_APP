"""Programmatic SVG figures for geometry/measurement questions (CPP-330).

CPP-333 renders a `measure` angle from its stored value, so authors never
upload an image and the printed figure is guaranteed true-to-scale: the
angle between the two drawn rays is exactly the requested degrees,
independent of render size (the SVG uses a viewBox, no rasterisation).

Pure functions — value in, SVG/coords out — no DB, no request.
"""
import math
import re


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

    Defensive on purpose — a spec that bypassed ``validate_shape_spec`` (raw
    admin JSON, a hand-edited fixture) must not 500 the take-item render, so a
    bad shape is simply skipped. The element carries ``data-shape-id`` /
    ``data-shape-type`` and the ``cwa-shape`` class so the take-item JS can
    toggle its fill and collect the coloured ids. ``fill="transparent"`` keeps
    the outline tappable before it's coloured.
    """
    try:
        sid = str(shape['id'])
        stype = shape['type']
        cx, cy, s = float(shape['cx']), float(shape['cy']), float(shape['size'])
        rot = float(shape.get('rot', 0))
    except (KeyError, TypeError, ValueError):
        return ''
    if s <= 0:
        return ''
    # Only a safe token reaches the data attribute / markup — ids are generated
    # (``s0``, ``s1`` …) so this never mangles a legitimate id.
    sid = re.sub(r'[^A-Za-z0-9_-]', '', sid)
    if not sid or stype not in _SHAPE_GEOMETRY:
        return ''

    stroke = 'var(--svg-stroke, #1a1a1a)'
    common = (
        f'class="cwa-shape" data-shape-id="{sid}" data-shape-type="{stype}" '
        f'fill="transparent" stroke="{stroke}" stroke-width="2" '
        f'transform="rotate({_f(rot)} {_f(cx)} {_f(cy)})" '
        f'tabindex="0" role="button" aria-label="{stype}"'
    )
    return _SHAPE_GEOMETRY[stype](cx, cy, s, common)


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
