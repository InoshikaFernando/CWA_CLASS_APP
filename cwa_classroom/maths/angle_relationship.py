"""Deterministic classification of angle-pair relationships for the AI importer.

"Identify the parallel lines and transversal, then label the marked pair of
angles as corresponding / alternate interior / alternate exterior / consecutive
interior" questions are the one case where letting the model NAME the pair proved
unreliable: it pattern-matches a plausible label instead of deriving it from the
figure, and swaps interior/exterior or the side of the transversal.

So the model no longer names the pair. It only PERCEIVES the geometry — where the
two parallel lines, the single transversal, and each labelled angle sit, in page
coordinates — and this module COMPUTES the label from that geometry:

    interior/exterior  x  same-side/opposite-side  ->  the four named pairs

Pure functions, no Django, so it is framework-agnostically testable. All maths is
sign-based (which side of the transversal, between which lines), so the caller's
coordinate frame (0-1 fractions, 0-100 percentages, or raw pixels) does not matter
as long as every point in one spec is in the SAME frame. Origin is assumed
top-left, but the classifier is orientation-agnostic anyway.

A pair that fits none of the four standard names — a figure with a non-standard
angle placement, near-coincident marks, non-parallel "parallel" lines, or a
transversal that does not cross both lines — is returned as ``needs_review`` with
a reason rather than being forced into a wrong label. Multi-transversal figures
never reach here: the model is told to leave the spec null and flag those itself.
"""
import math
import re

# The four labels this question type accepts, in canonical form.
CANONICAL_LABELS = (
    'alternate interior',
    'alternate exterior',
    'consecutive interior',
    'corresponding',
)

# Normalised spelling variants -> canonical label. Keys are already normalised
# (see _normalize): lower-case, punctuation collapsed to single spaces.
_LABEL_SYNONYMS = {
    'alternate interior': 'alternate interior',
    'alt interior': 'alternate interior',
    'alt int': 'alternate interior',
    'alternate exterior': 'alternate exterior',
    'alt exterior': 'alternate exterior',
    'alt ext': 'alternate exterior',
    'consecutive interior': 'consecutive interior',
    'co interior': 'consecutive interior',
    'cointerior': 'consecutive interior',
    'same side interior': 'consecutive interior',
    'allied': 'consecutive interior',
    'corresponding': 'corresponding',
}

# How close (as a fraction of the inter-line band width) a mark may sit to a line
# or to the transversal before we call the reading ambiguous rather than guess.
DEFAULT_MARGIN = 0.05

# How far the two "parallel" lines may diverge before we refuse to treat them as
# parallel. sin(theta) between their unit directions; ~0.26 ~= 15 degrees.
_PARALLEL_TOL = 0.26


def _normalize(text):
    """Lower-case and collapse all non-letters to single spaces."""
    return ' '.join(re.sub(r'[^a-z]+', ' ', str(text or '').lower()).split())


def canonical_label(text):
    """Map an answer-option string to its canonical label, or ``None``.

    ``"Alt. Int."`` / ``"alternate  interior"`` / ``"co-interior"`` all resolve;
    anything unrecognised returns ``None`` so the caller can decide what to do.
    """
    return _LABEL_SYNONYMS.get(_normalize(text))


# --- small vector helpers (2D, tuples of floats) ---------------------------

def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _cross(a, b):
    return a[0] * b[1] - a[1] * b[0]


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1])


def _unit(v):
    length = math.hypot(v[0], v[1])
    if length == 0:
        raise ValueError('a line or transversal was given zero length')
    return (v[0] / length, v[1] / length)


def _avg_direction(d1, d2):
    """Unit direction averaging two nearly-parallel segment directions.

    d2 is flipped to point the same way as d1 first, so the average does not
    cancel when the model listed the two lines' endpoints in opposite order.
    """
    u1 = _unit(d1)
    u2 = _unit(d2)
    if _dot(u1, u2) < 0:
        u2 = (-u2[0], -u2[1])
    return _unit((u1[0] + u2[0], u1[1] + u2[1]))


def _coord(raw, where):
    """Parse ``[x, y]`` into a float tuple; raise on anything else."""
    if (not isinstance(raw, (list, tuple))) or len(raw) != 2:
        raise ValueError(f'{where} must be an [x, y] pair')
    try:
        return (float(raw[0]), float(raw[1]))
    except (TypeError, ValueError):
        raise ValueError(f'{where} must be two numbers')


def _line(raw, where):
    if not isinstance(raw, dict):
        raise ValueError(f'{where} must be an object with p1 and p2')
    return (_coord(raw.get('p1'), f'{where}.p1'), _coord(raw.get('p2'), f'{where}.p2'))


def parse_spec(spec):
    """Validate and normalise an ``angle_relationship_spec``.

    Returns ``{'lines': [(p1,p2),(p1,p2)], 'transversal': (p1,p2),
    'angles': [{'label': str, 'pos': (x,y)}, ...]}``. Raises ``ValueError`` with a
    human-readable message on any structural problem, so it can guard both the
    importer and tests.
    """
    if not isinstance(spec, dict):
        raise ValueError('angle_relationship_spec must be an object')

    lines_raw = spec.get('lines')
    if not isinstance(lines_raw, list) or len(lines_raw) != 2:
        raise ValueError('angle_relationship_spec.lines must list exactly two parallel lines')
    lines = [_line(lines_raw[0], 'lines[0]'), _line(lines_raw[1], 'lines[1]')]

    transversal = _line(spec.get('transversal'), 'transversal')

    angles_raw = spec.get('angles')
    if not isinstance(angles_raw, list) or len(angles_raw) != 2:
        raise ValueError('angle_relationship_spec.angles must list exactly two marked angles')
    angles = []
    for i, ang in enumerate(angles_raw):
        if not isinstance(ang, dict):
            raise ValueError(f'angles[{i}] must be an object')
        label = str(ang.get('label') or '').strip()
        angles.append({'label': label, 'pos': _coord(ang.get('pos'), f'angles[{i}].pos')})

    return {'lines': lines, 'transversal': transversal, 'angles': angles}


def _needs_review(reason, facts=None):
    return {'label': None, 'needs_review': True, 'reason': reason, 'facts': facts or []}


def classify_angle_pair(spec, margin=DEFAULT_MARGIN):
    """Compute the named relationship for the two marked angles in ``spec``.

    Returns a dict:
      ``{'label': <canonical str|None>, 'needs_review': bool, 'reason': str,
         'facts': [{'label','interior','side','ambiguous'}, ...]}``

    ``label`` is one of :data:`CANONICAL_LABELS` when the figure is a clean,
    standard configuration; otherwise ``needs_review`` is True with a reason.
    Raises ``ValueError`` only for a structurally invalid spec (via
    :func:`parse_spec`) — geometric ambiguity is reported, not raised.
    """
    parsed = parse_spec(spec)
    (l1a, l1b), (l2a, l2b) = parsed['lines']
    ta, tb = parsed['transversal']
    angles = parsed['angles']

    d1 = _sub(l1b, l1a)
    d2 = _sub(l2b, l2a)
    try:
        u1, u2 = _unit(d1), _unit(d2)
    except ValueError as exc:
        return _needs_review(str(exc))

    # The two lines must actually be (roughly) parallel.
    if abs(_cross(u1, u2)) > _PARALLEL_TOL:
        return _needs_review('the two lines are not parallel, so the pair has no standard name')

    line_dir = _avg_direction(d1, d2)
    normal = (-line_dir[1], line_dir[0])

    # Signed offset of each line along the shared normal; the interior band is
    # between them.
    o1 = _dot(l1a, normal)
    o2 = _dot(l2a, normal)
    lo, hi = sorted((o1, o2))
    band = hi - lo
    if band <= 0:
        return _needs_review('the two parallel lines coincide')

    try:
        t_unit = _unit(_sub(tb, ta))
    except ValueError as exc:
        return _needs_review(str(exc))

    # The transversal must actually cross the lines, not run alongside them.
    if abs(_cross(t_unit, line_dir)) < _PARALLEL_TOL:
        return _needs_review('the transversal is parallel to the lines, so it does not cross them')

    tvec = _sub(tb, ta)
    tlen = math.hypot(tvec[0], tvec[1])
    m = margin * band

    facts = []
    for ang in angles:
        p = ang['pos']
        offset = _dot(p, normal)
        # Perpendicular signed distance from the transversal (which side).
        signed_side = _cross(tvec, _sub(p, ta)) / tlen

        near_line = abs(offset - lo) < m or abs(offset - hi) < m
        near_transversal = abs(signed_side) < m
        interior = lo < offset < hi
        facts.append({
            'label': ang['label'],
            'interior': interior,
            'side': 1 if signed_side > 0 else -1,
            'ambiguous': near_line or near_transversal,
        })

    ambiguous = [f['label'] or '?' for f in facts if f['ambiguous']]
    if ambiguous:
        return _needs_review(
            'a marked angle sits too close to a line or the transversal to read '
            f'reliably ({", ".join(ambiguous)})',
            facts,
        )

    a, b = facts
    same_side = a['side'] == b['side']

    if a['interior'] and b['interior']:
        label = 'consecutive interior' if same_side else 'alternate interior'
    elif (not a['interior']) and (not b['interior']):
        if same_side:
            return _needs_review(
                'both angles are exterior on the same side (co-exterior) — not one '
                'of the four standard options', facts)
        label = 'alternate exterior'
    else:
        # one interior, one exterior
        if same_side:
            label = 'corresponding'
        else:
            return _needs_review(
                'one angle is interior and one exterior on opposite sides — no '
                'standard name for this pair', facts)

    return {'label': label, 'needs_review': False, 'reason': '', 'facts': facts}


def _describe(fact):
    region = 'between the parallel lines (interior)' if fact['interior'] else 'outside the parallel lines (exterior)'
    return region


def build_explanation(result):
    """A short student-facing explanation derived from a classify result.

    Uses the computed facts so the wording can never contradict the label. Returns
    ``''`` for a needs-review result (no confident label to explain).
    """
    label = result.get('label')
    facts = result.get('facts') or []
    if not label or len(facts) != 2:
        return ''

    a, b = facts
    names = ' and '.join(f['label'] for f in facts if f['label']) or 'the marked angles'
    same_side = a['side'] == b['side']
    side_phrase = 'the same side of the transversal' if same_side else 'opposite sides of the transversal'

    if label == 'alternate interior':
        body = ('both lie between the parallel lines and on opposite sides of the '
                'transversal, forming a "Z" shape. Alternate interior angles are equal')
    elif label == 'alternate exterior':
        body = ('both lie outside the parallel lines and on opposite sides of the '
                'transversal. Alternate exterior angles are equal')
    elif label == 'consecutive interior':
        body = ('both lie between the parallel lines and on the same side of the '
                'transversal. Consecutive interior (co-interior) angles add up to 180°')
    else:  # corresponding
        body = ('they sit in matching positions at the two intersections (one inside '
                'the lines, one outside, on the same side of the transversal). '
                'Corresponding angles are equal')

    return f'Angles {names} {body}.'
