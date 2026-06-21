"""Tests for the Cartesian-plane / graph question-type grading.

``grade_plane`` / ``grade_identify_coords`` / ``parse_coords`` are pure functions
(no DB), so most cases need no database. DB-backed tests exercise the real
``MathsPlugin.grade_answer`` dispatch to prove each new branch is wired in.
Mirrors test_shape_select_grading.py. CPP graph/Cartesian question-type family
(plot_points, plot_line, identify_coords, read_graph).
"""
import json
from decimal import Decimal

import pytest

from maths.geometry_grading import (
    grade_plane,
    grade_identify_coords,
    parse_coords,
)


def _points_spec(points=None, allow_extra=False):
    return {
        'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
        'mode': 'points',
        'target': {'points': points or [[3, -2], [1, 4]]},
        'allow_extra': allow_extra,
    }


def _segments_spec(segments=None):
    return {
        'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
        'mode': 'segments',
        'target': {'segments': segments or [
            {'x1': -2, 'y1': 1, 'x2': 0, 'y2': 4},
            {'x1': 0, 'y1': 4, 'x2': 3, 'y2': 1},
        ]},
    }


# ── grade_plane: points mode (plot_points) ───────────────────────────────

def test_plot_points_exact_set_correct():
    assert grade_plane(_points_spec(), json.dumps({'points': [[3, -2], [1, 4]]})) is True


def test_plot_points_order_independent():
    assert grade_plane(_points_spec(), json.dumps({'points': [[1, 4], [3, -2]]})) is True


def test_plot_points_missing_one_is_wrong():
    assert grade_plane(_points_spec(), json.dumps({'points': [[3, -2]]})) is False


def test_plot_points_extra_point_is_wrong():
    assert grade_plane(_points_spec(), json.dumps({'points': [[3, -2], [1, 4], [0, 0]]})) is False


def test_plot_points_allow_extra_subset_ok():
    spec = _points_spec(allow_extra=True)
    assert grade_plane(spec, json.dumps({'points': [[3, -2], [1, 4], [0, 0]]})) is True
    # Still wrong if a target point is missing, even with allow_extra.
    assert grade_plane(spec, json.dumps({'points': [[3, -2], [0, 0]]})) is False


def test_negative_coordinates_grade_correctly():
    spec = _points_spec(points=[[-3, -4], [-1, 2]])
    assert grade_plane(spec, json.dumps({'points': [[-1, 2], [-3, -4]]})) is True
    assert grade_plane(spec, json.dumps({'points': [[3, 4], [1, -2]]})) is False


def test_plot_points_accepts_already_parsed_dict():
    assert grade_plane(_points_spec(), {'points': [[3, -2], [1, 4]]}) is True


# ── grade_plane: segments mode (plot_line) ───────────────────────────────

def test_plot_line_segment_order_independent():
    # Each segment A->B must equal B->A; segment list order is irrelevant too.
    got = {'segments': [
        {'x1': 3, 'y1': 1, 'x2': 0, 'y2': 4},   # reversed
        {'x1': 0, 'y1': 4, 'x2': -2, 'y2': 1},  # reversed
    ]}
    assert grade_plane(_segments_spec(), json.dumps(got)) is True


def test_plot_line_missing_segment_wrong():
    got = {'segments': [{'x1': -2, 'y1': 1, 'x2': 0, 'y2': 4}]}
    assert grade_plane(_segments_spec(), json.dumps(got)) is False


# ── defensive: never raise on bad input ──────────────────────────────────

@pytest.mark.parametrize('bad', ['', 'not json', '{', '[]', '42', None,
                                 '{"points": "x"}', '{"points": 5}'])
def test_plane_malformed_payload_returns_false_not_raises(bad):
    assert grade_plane(_points_spec(), bad) is False


@pytest.mark.parametrize('spec', [
    'not a dict', ['a', 'list'], None,
    {'mode': 'points', 'target': {'points': []}},   # empty target
    {'mode': 'points'},                              # no target
])
def test_plane_empty_or_bad_target_returns_false(spec):
    assert grade_plane(spec, json.dumps({'points': [[0, 0]]})) is False


# ── parse_coords + grade_identify_coords ─────────────────────────────────

@pytest.mark.parametrize('text, expected', [
    ('(-2, 4)', {(-2, 4)}),
    ('-2,4', {(-2, 4)}),
    (' ( -2 , 4 ) ', {(-2, 4)}),
    ('(1,2) (3,4)', {(1, 2), (3, 4)}),
    ('(1,2); (3,4)', {(1, 2), (3, 4)}),
    ('(0,0)', {(0, 0)}),
])
def test_parse_coords_tolerant(text, expected):
    assert parse_coords(text) == expected


@pytest.mark.parametrize('bad', ['', 'banana', '3', '(3,)', None, 42, '(a,b)'])
def test_parse_coords_rejects_garbage(bad):
    assert parse_coords(bad) == set()


def test_identify_coords_correct():
    assert grade_identify_coords(_points_spec(), '(3, -2) (1, 4)') is True


def test_identify_coords_order_independent():
    assert grade_identify_coords(_points_spec(), '(1,4) (3,-2)') is True


def test_identify_coords_missing_point_wrong():
    assert grade_identify_coords(_points_spec(), '(3,-2)') is False


def test_identify_coords_garbage_wrong():
    assert grade_identify_coords(_points_spec(), 'banana') is False


# ── dispatch wiring through the plugin (DB-backed) ───────────────────────

@pytest.mark.django_db
def test_plugin_routes_plot_points():
    q = _make_question('plot_points', plane_spec=_points_spec())
    from maths.plugin import MathsPlugin
    plugin = MathsPlugin()
    correct = plugin.grade_answer(q.pk, {f'answer_{q.id}': json.dumps({'points': [[3, -2], [1, 4]]})})
    wrong = plugin.grade_answer(q.pk, {f'answer_{q.id}': json.dumps({'points': [[3, -2]]})})
    assert correct['is_correct'] is True
    assert correct['points_earned'] == 2
    assert wrong['is_correct'] is False


@pytest.mark.django_db
def test_plugin_routes_plot_line():
    q = _make_question('plot_line', plane_spec=_segments_spec())
    from maths.plugin import MathsPlugin
    got = {'segments': [
        {'x1': 0, 'y1': 4, 'x2': -2, 'y2': 1},
        {'x1': 3, 'y1': 1, 'x2': 0, 'y2': 4},
    ]}
    res = MathsPlugin().grade_answer(q.pk, {f'answer_{q.id}': json.dumps(got)})
    assert res['is_correct'] is True


@pytest.mark.django_db
def test_plugin_routes_identify_coords():
    q = _make_question('identify_coords', plane_spec=_points_spec())
    from maths.plugin import MathsPlugin
    res = MathsPlugin().grade_answer(q.pk, {f'answer_{q.id}': '(3,-2) (1,4)'})
    assert res['is_correct'] is True


@pytest.mark.django_db
def test_plugin_routes_read_graph_uses_measure_tolerance():
    q = _make_question(
        'read_graph', numeric_answer=Decimal('130'), answer_tolerance=Decimal('5'),
        answer_unit='km',
    )
    from maths.plugin import MathsPlugin
    plugin = MathsPlugin()
    within = plugin.grade_answer(q.pk, {f'answer_{q.id}': '132'})
    boundary = plugin.grade_answer(q.pk, {f'answer_{q.id}': '135'})
    outside = plugin.grade_answer(q.pk, {f'answer_{q.id}': '120'})
    assert within['is_correct'] is True
    assert boundary['is_correct'] is True       # 130 ± 5 includes 135
    assert outside['is_correct'] is False


@pytest.mark.django_db
def test_plugin_unknown_payload_not_500():
    q = _make_question('plot_points', plane_spec=_points_spec())
    from maths.plugin import MathsPlugin
    res = MathsPlugin().grade_answer(q.pk, {f'answer_{q.id}': 'garbage{'})
    assert res['is_correct'] is False           # bad submission is wrong, not an error


# ── helpers ──────────────────────────────────────────────────────────────

def _make_question(qtype, **kwargs):
    from classroom.models import Level
    from maths.models import Question
    level, _ = Level.objects.get_or_create(
        level_number=983, defaults={'display_name': 'plane grading fixture'},
    )
    return Question.objects.create(
        level=level,
        question_text='Plot the points.',
        question_type=qtype,
        difficulty=1, points=2,
        **kwargs,
    )
