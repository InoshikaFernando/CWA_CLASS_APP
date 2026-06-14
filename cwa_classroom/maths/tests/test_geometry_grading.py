"""Tests for measure-question grading (CPP-332).

``grade_measure`` is a pure function (reads only ``numeric_answer`` and
``answer_tolerance``), so most cases use a lightweight stub and need no DB.
One DB-backed test exercises the real ``MathsPlugin.grade_answer`` dispatch
to prove the ``measure`` branch is wired in.

Epic CPP-330; spec docs/specs/CPP-330_interactive_geometry_questions.md.
"""
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from maths.geometry_grading import grade_draw_on_grid, grade_measure


def _q(numeric_answer, tolerance):
    """Minimal stand-in for a measure Question."""
    return SimpleNamespace(
        numeric_answer=numeric_answer,
        answer_tolerance=tolerance,
    )


# ── pure grade_measure tests (no DB) ─────────────────────────────────────

def test_within_tolerance_correct():
    assert grade_measure(_q(Decimal('135'), Decimal('2')), '134') is True


def test_boundary_inclusive():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '133') is True   # lower bound
    assert grade_measure(q, '137') is True   # upper bound


def test_outside_tolerance_wrong():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '132') is False
    assert grade_measure(q, '138') is False


def test_null_tolerance_is_exact():
    q = _q(Decimal('135'), None)
    assert grade_measure(q, '135') is True
    assert grade_measure(q, '134') is False


def test_unit_suffix_stripped():
    q = _q(Decimal('135'), Decimal('2'))
    assert grade_measure(q, '135°') is True
    assert grade_measure(q, '134 cm') is True
    assert grade_measure(q, '+136') is True


def test_decimal_value_within_tolerance():
    q = _q(Decimal('135.5'), Decimal('0.5'))
    assert grade_measure(q, '135.9') is True
    assert grade_measure(q, '136.1') is False


@pytest.mark.parametrize('bad', ['abc', '', '   ', None, '°', '--', '.'])
def test_non_numeric_returns_false(bad):
    assert grade_measure(_q(Decimal('135'), Decimal('2')), bad) is False


def test_missing_target_returns_false():
    # A misconfigured measure question (no numeric_answer) is never "correct".
    assert grade_measure(_q(None, Decimal('2')), '135') is False


@pytest.mark.parametrize('weird', ['１３５', '13⁵', '²'])
def test_unicode_digits_not_misparsed(weird):
    # str.isdigit() is True for full-width / superscript digits; the ASCII-only
    # filter must drop them so they don't corrupt the parsed value.
    assert grade_measure(_q(Decimal('135'), Decimal('2')), weird) is False


# ── dispatch wiring through the plugin (DB-backed) ───────────────────────

@pytest.mark.django_db
def test_plugin_grade_answer_routes_measure():
    from classroom.models import Level
    from maths.models import Question
    from maths.plugin import MathsPlugin

    level, _ = Level.objects.get_or_create(
        level_number=993, defaults={'display_name': 'measure grading fixture'},
    )
    q = Question.objects.create(
        level=level,
        question_text='Measure angle a.',
        question_type=Question.MEASURE,
        difficulty=1,
        points=3,
        numeric_answer=Decimal('135'),
        answer_tolerance=Decimal('2'),
        answer_unit='°',
    )

    plugin = MathsPlugin()
    correct = plugin.grade_answer(q.pk, {f'answer_{q.id}': '134'})
    wrong = plugin.grade_answer(q.pk, {f'answer_{q.id}': '120'})

    assert correct['is_correct'] is True
    assert correct['points_earned'] == 3        # question.points on success
    assert wrong['is_correct'] is False
    assert wrong['points_earned'] == 0


# ── draw_on_grid grading (CPP-337) ───────────────────────────────────────

def _seg(x1, y1, x2, y2):
    return {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2}


def _grid(mode='segments', target=None, allow_extra=False):
    return {'mode': mode, 'target': target or {}, 'allow_extra': allow_extra}


def test_segment_endpoint_order_invariant():
    # The target line is drawn one way; the student draws it the other way.
    grid = _grid(target={'segments': [_seg(4, 0, 4, 8)]})
    payload = json.dumps({'segments': [_seg(4, 8, 4, 0)]})
    assert grade_draw_on_grid(grid, payload) is True


def test_exact_set_required_when_no_extra():
    grid = _grid(target={'segments': [_seg(4, 0, 4, 8), _seg(0, 4, 8, 4)]})
    # Only one of the two required lines drawn → not equal → wrong.
    assert grade_draw_on_grid(grid, json.dumps({'segments': [_seg(4, 0, 4, 8)]})) is False
    # Both drawn (order shuffled) → correct.
    both = {'segments': [_seg(8, 4, 0, 4), _seg(4, 8, 4, 0)]}
    assert grade_draw_on_grid(grid, json.dumps(both)) is True


def test_extra_segment_marked_wrong():
    grid = _grid(target={'segments': [_seg(4, 0, 4, 8)]})
    extra = {'segments': [_seg(4, 0, 4, 8), _seg(1, 1, 2, 2)]}
    assert grade_draw_on_grid(grid, json.dumps(extra)) is False


def test_allow_extra_subset_passes():
    grid = _grid(target={'segments': [_seg(4, 0, 4, 8)]}, allow_extra=True)
    extra = {'segments': [_seg(4, 0, 4, 8), _seg(1, 1, 2, 2)]}
    assert grade_draw_on_grid(grid, json.dumps(extra)) is True
    # Still wrong if the required line is missing.
    assert grade_draw_on_grid(grid, json.dumps({'segments': [_seg(1, 1, 2, 2)]})) is False


def test_points_mode_set_match():
    grid = _grid(mode='points', target={'points': [[3, 3], [7, 5]]})
    assert grade_draw_on_grid(grid, json.dumps({'points': [[7, 5], [3, 3]]})) is True
    assert grade_draw_on_grid(grid, json.dumps({'points': [[3, 3]]})) is False


def test_shape_complete_uses_expected_extra_segments():
    grid = _grid(mode='shape_complete',
                 target={'expected_extra_segments': [_seg(5, 2, 6, 3)]})
    assert grade_draw_on_grid(grid, json.dumps({'segments': [_seg(6, 3, 5, 2)]})) is True


@pytest.mark.parametrize('bad', ['', 'not json', '{', '[]', '{"segments": "x"}', None, '42'])
def test_malformed_payload_false(bad):
    grid = _grid(target={'segments': [_seg(4, 0, 4, 8)]})
    assert grade_draw_on_grid(grid, bad) is False


@pytest.mark.parametrize('spec', [
    'not a dict', ['a', 'list'], None,
    {'mode': 'segments'},                      # no target
    {'mode': 'segments', 'target': ['list']},  # target not a dict
    {'mode': 'points', 'target': 'x'},
])
def test_malformed_grid_spec_false(spec):
    # A spec that bypassed clean() must grade False, never raise.
    assert grade_draw_on_grid(spec, json.dumps({'segments': [_seg(4, 0, 4, 8)]})) is False


def test_empty_target_false():
    # A misconfigured question with no target is never "correct".
    assert grade_draw_on_grid(_grid(target={'segments': []}),
                              json.dumps({'segments': []})) is False
    assert grade_draw_on_grid(None, json.dumps({'segments': []})) is False


@pytest.mark.django_db
def test_plugin_grade_answer_routes_draw_on_grid():
    from classroom.models import Level
    from maths.models import Question
    from maths.plugin import MathsPlugin

    level, _ = Level.objects.get_or_create(
        level_number=986, defaults={'display_name': 'draw_on_grid grading fixture'},
    )
    q = Question.objects.create(
        level=level,
        question_text='Draw all lines of symmetry.',
        question_type=Question.DRAW_ON_GRID,
        difficulty=1, points=2,
        grid_spec=_grid(target={'segments': [_seg(4, 0, 4, 8)]}),
    )

    plugin = MathsPlugin()
    correct = plugin.grade_answer(q.pk, {f'answer_{q.id}': json.dumps({'segments': [_seg(4, 8, 4, 0)]})})
    wrong = plugin.grade_answer(q.pk, {f'answer_{q.id}': json.dumps({'segments': []})})

    assert correct['is_correct'] is True
    assert correct['points_earned'] == 2
    assert wrong['is_correct'] is False
