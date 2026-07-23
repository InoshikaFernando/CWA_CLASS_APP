"""Tests for deterministic angle-pair classification (AI importer).

``classify_angle_pair`` is a pure function over an ``angle_relationship_spec`` —
no DB, no request — so it grades identically wherever it runs. Coordinates below
are page percentages (0-100), origin top-left, y increasing downward, matching the
frame the importer asks the model to use.

The four "regression" cases reproduce the exact figures from the worksheet that
the old name-it-directly prompt got wrong (Q5 alt-exterior, Q6/Q7 alt-interior)
or could not classify (Q8 multi-transversal).
"""
import math

import pytest

from maths.angle_relationship import (
    build_explanation,
    canonical_label,
    classify_angle_pair,
    parse_spec,
)

# Two horizontal parallel lines: top at y=20, bottom at y=60.
TOP = {'p1': [10, 20], 'p2': [90, 20]}
BOTTOM = {'p1': [10, 60], 'p2': [90, 60]}
# Transversal falling left-to-right through both.
TRANS = {'p1': [45, 10], 'p2': [70, 90]}


def _spec(y_pos, x_pos, lines=None, transversal=None):
    """Build a spec with labels 'y' and 'x' at the given positions."""
    return {
        'lines': lines or [TOP, BOTTOM],
        'transversal': transversal or TRANS,
        'angles': [
            {'label': 'y', 'pos': list(y_pos)},
            {'label': 'x', 'pos': list(x_pos)},
        ],
    }


def _label(spec):
    return classify_angle_pair(spec)['label']


# ── the four standard relationships ──────────────────────────────────────

def test_alternate_interior_opposite_sides():
    # both between the lines, opposite sides of the transversal
    assert _label(_spec(y_pos=(55, 28), x_pos=(52, 52))) == 'alternate interior'


def test_consecutive_interior_same_side():
    # both between the lines, same side of the transversal
    assert _label(_spec(y_pos=(40, 28), x_pos=(40, 52))) == 'consecutive interior'


def test_alternate_exterior_opposite_sides():
    # both outside the lines, opposite sides
    assert _label(_spec(y_pos=(55, 14), x_pos=(52, 68))) == 'alternate exterior'


def test_corresponding_same_corner():
    # matching corner: one exterior, one interior, same side
    assert _label(_spec(y_pos=(40, 14), x_pos=(40, 52))) == 'corresponding'


# ── regression cases: the real worksheet figures ─────────────────────────

def test_q5_regression_is_alternate_exterior():
    # y above the top line, x below the bottom line, opposite sides.
    # Old prompt mislabelled this "consecutive interior".
    assert _label(_spec(y_pos=(55, 14), x_pos=(52, 68))) == 'alternate exterior'


def test_q6_regression_is_alternate_interior():
    # y just below the top line, x just above the bottom line, opposite sides.
    # Old prompt mislabelled this "corresponding".
    assert _label(_spec(y_pos=(56, 27), x_pos=(52, 53))) == 'alternate interior'


def test_q7_regression_is_alternate_interior():
    # Same class as Q6 (the one the old prompt got right); still computes cleanly.
    assert _label(_spec(y_pos=(54, 30), x_pos=(50, 50))) == 'alternate interior'


def test_q8_multi_transversal_is_not_forced():
    # Q8 has two transversals; the model is told to leave the spec null and flag
    # it. If a malformed single-transversal spec ever slips through with the mark
    # placed where no standard name applies, we must refuse rather than guess.
    result = classify_angle_pair(_spec(y_pos=(55, 14), x_pos=(40, 52)))
    assert result['needs_review'] is True
    assert result['label'] is None


# ── refusals: pairs with no standard name / unreadable ───────────────────

def test_co_exterior_needs_review():
    # both exterior, same side -> co-exterior, not one of the four options
    result = classify_angle_pair(_spec(y_pos=(40, 14), x_pos=(40, 68)))
    assert result['needs_review'] is True
    assert 'co-exterior' in result['reason']


def test_interior_exterior_opposite_needs_review():
    result = classify_angle_pair(_spec(y_pos=(55, 14), x_pos=(40, 52)))
    assert result['needs_review'] is True
    assert result['label'] is None


def test_mark_on_a_line_is_ambiguous():
    # y sits exactly on the top line -> too close to read interior vs exterior
    result = classify_angle_pair(_spec(y_pos=(55, 20), x_pos=(52, 52)))
    assert result['needs_review'] is True
    assert 'close' in result['reason']


def test_non_parallel_lines_needs_review():
    slanted = {'p1': [10, 40], 'p2': [90, 80]}  # ~27° off horizontal
    result = classify_angle_pair(_spec(y_pos=(55, 28), x_pos=(52, 34), lines=[TOP, slanted]))
    assert result['needs_review'] is True
    assert 'not parallel' in result['reason']


def test_transversal_parallel_to_lines_needs_review():
    flat = {'p1': [10, 40], 'p2': [90, 40]}  # runs alongside the lines
    result = classify_angle_pair(_spec(y_pos=(55, 28), x_pos=(52, 52), transversal=flat))
    assert result['needs_review'] is True
    assert 'does not cross' in result['reason']


# ── invariances ──────────────────────────────────────────────────────────

def test_endpoint_order_does_not_matter():
    # List one line's endpoints reversed and flip the transversal direction.
    reversed_bottom = {'p1': [90, 60], 'p2': [10, 60]}
    flipped_trans = {'p1': [70, 90], 'p2': [45, 10]}
    spec = _spec(y_pos=(55, 28), x_pos=(52, 52),
                 lines=[TOP, reversed_bottom], transversal=flipped_trans)
    assert _label(spec) == 'alternate interior'


def test_orientation_independent_under_rotation():
    # Rotate the whole Q6 figure 37° about the origin; the label must not change.
    theta = math.radians(37)
    cos_t, sin_t = math.cos(theta), math.sin(theta)

    def rot(p):
        return [p[0] * cos_t - p[1] * sin_t, p[0] * sin_t + p[1] * cos_t]

    def rot_line(ln):
        return {'p1': rot(ln['p1']), 'p2': rot(ln['p2'])}

    base = _spec(y_pos=(55, 28), x_pos=(52, 52))
    rotated = {
        'lines': [rot_line(base['lines'][0]), rot_line(base['lines'][1])],
        'transversal': rot_line(base['transversal']),
        'angles': [{'label': a['label'], 'pos': rot(a['pos'])} for a in base['angles']],
    }
    assert _label(rotated) == 'alternate interior'


# ── canonical_label / synonyms ───────────────────────────────────────────

@pytest.mark.parametrize('text,expected', [
    ('corresponding', 'corresponding'),
    ('Corresponding', 'corresponding'),
    ('alternate interior', 'alternate interior'),
    ('Alt. Int.', 'alternate interior'),
    ('alt int', 'alternate interior'),
    ('alternate exterior', 'alternate exterior'),
    ('Alt. Ext.', 'alternate exterior'),
    ('consecutive interior', 'consecutive interior'),
    ('co-interior', 'consecutive interior'),
    ('same-side interior', 'consecutive interior'),
    ('nonsense', None),
    ('', None),
    (None, None),
])
def test_canonical_label(text, expected):
    assert canonical_label(text) == expected


# ── explanation matches the computed label ───────────────────────────────

def test_explanation_alternate_interior_mentions_opposite_and_equal():
    result = classify_angle_pair(_spec(y_pos=(55, 28), x_pos=(52, 52)))
    text = build_explanation(result)
    assert 'opposite sides' in text
    assert 'equal' in text
    assert 'same side' not in text


def test_explanation_consecutive_interior_mentions_supplementary():
    result = classify_angle_pair(_spec(y_pos=(40, 28), x_pos=(40, 52)))
    text = build_explanation(result)
    assert '180' in text
    assert 'y and x' in text


def test_explanation_empty_for_needs_review():
    result = classify_angle_pair(_spec(y_pos=(40, 14), x_pos=(40, 68)))
    assert build_explanation(result) == ''


# ── spec validation ──────────────────────────────────────────────────────

@pytest.mark.parametrize('bad', [
    {},
    {'lines': [TOP], 'transversal': TRANS, 'angles': []},
    {'lines': [TOP, BOTTOM], 'transversal': TRANS,
     'angles': [{'label': 'y', 'pos': [1, 2]}]},
    {'lines': [TOP, BOTTOM], 'transversal': TRANS,
     'angles': [{'label': 'y', 'pos': [1, 2]}, {'label': 'x', 'pos': [3]}]},
    {'lines': [TOP, BOTTOM], 'transversal': {'p1': [1, 2]},
     'angles': [{'label': 'y', 'pos': [1, 2]}, {'label': 'x', 'pos': [3, 4]}]},
])
def test_parse_spec_rejects_malformed(bad):
    with pytest.raises(ValueError):
        parse_spec(bad)
