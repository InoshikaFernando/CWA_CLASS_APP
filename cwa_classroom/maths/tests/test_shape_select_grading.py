"""Tests for shape_select grading.

``grade_shape_select`` / ``validate_shape_spec`` / ``shape_target_ids`` are pure
functions (no DB), so most cases need no database. One DB-backed test exercises
the real ``MathsPlugin.grade_answer`` dispatch to prove the ``shape_select``
branch is wired in. Mirrors test_geometry_grading.py (draw_on_grid). Epic
CPP-330 family (interactive geometry question types).
"""
import json

import pytest

from maths.geometry_grading import (
    grade_shape_select,
    shape_target_ids,
    validate_shape_spec,
)


def _shape(sid, stype, cx=10.0, cy=10.0, size=20.0, rot=0.0):
    return {'id': sid, 'type': stype, 'cx': cx, 'cy': cy, 'size': size, 'rot': rot}


def _spec(target='triangle', shapes=None):
    return {
        'target_type': target,
        'viewbox': [680, 400],
        'shapes': shapes or [
            _shape('s0', 'triangle'), _shape('s1', 'circle'),
            _shape('s2', 'triangle'), _shape('s3', 'square'),
            _shape('s4', 'triangle'),
        ],
    }


def _payload(*ids):
    return json.dumps({'selected': list(ids)})


# ── shape_target_ids (pure) ──────────────────────────────────────────────

def test_target_ids_derived_from_type():
    assert shape_target_ids(_spec()) == {'s0', 's2', 's4'}


def test_target_ids_empty_for_malformed():
    assert shape_target_ids(None) == set()
    assert shape_target_ids({'shapes': 'x'}) == set()


# ── grade_shape_select (pure) ────────────────────────────────────────────

def test_all_targets_coloured_correct():
    assert grade_shape_select(_spec(), _payload('s0', 's2', 's4')) is True


def test_order_independent():
    assert grade_shape_select(_spec(), _payload('s4', 's0', 's2')) is True


def test_missing_one_target_wrong():
    assert grade_shape_select(_spec(), _payload('s0', 's2')) is False


def test_extra_wrong_shape_marked_wrong():
    # Colouring a non-triangle as well → set not equal → wrong.
    assert grade_shape_select(_spec(), _payload('s0', 's2', 's4', 's1')) is False


def test_empty_selection_wrong():
    assert grade_shape_select(_spec(), _payload()) is False


def test_duplicate_ids_collapse_to_set():
    # A client that double-sends an id still grades as the de-duped set.
    assert grade_shape_select(_spec(), _payload('s0', 's2', 's4', 's0')) is True


def test_accepts_already_parsed_dict():
    assert grade_shape_select(_spec(), {'selected': ['s0', 's2', 's4']}) is True


@pytest.mark.parametrize('bad', ['', 'not json', '{', '[]', '42', None,
                                 '{"selected": "x"}', '{"selected": 5}'])
def test_malformed_payload_false(bad):
    assert grade_shape_select(_spec(), bad) is False


@pytest.mark.parametrize('spec', [
    'not a dict', ['a', 'list'], None,
    {'shapes': []},                                  # no target / no shapes
    {'target_type': 'triangle', 'shapes': []},       # no shapes of any type
    {'target_type': 'triangle',                      # no triangle present
     'shapes': [_shape('s0', 'circle')]},
])
def test_no_target_spec_false(spec):
    # A spec with no derivable target set is never "correct", never raises.
    assert grade_shape_select(spec, _payload('s0')) is False


# ── validate_shape_spec (pure) ───────────────────────────────────────────

def test_valid_spec_passes():
    validate_shape_spec(_spec())  # must not raise


@pytest.mark.parametrize('mutate, msg', [
    (lambda s: s.update(target_type='hexagon'), 'target_type'),
    (lambda s: s.update(shapes=[]), 'non-empty list'),
    (lambda s: s.update(shapes='x'), 'non-empty list'),
])
def test_invalid_top_level_raises(mutate, msg):
    spec = _spec()
    mutate(spec)
    with pytest.raises(ValueError) as exc:
        validate_shape_spec(spec)
    assert msg in str(exc.value)


def test_duplicate_id_raises():
    spec = _spec(shapes=[_shape('s0', 'triangle'), _shape('s0', 'circle')])
    with pytest.raises(ValueError, match='Duplicate'):
        validate_shape_spec(spec)


def test_unknown_shape_type_raises():
    spec = _spec(shapes=[_shape('s0', 'triangle'), _shape('s1', 'star')])
    with pytest.raises(ValueError, match='unknown type'):
        validate_shape_spec(spec)


def test_non_numeric_coord_raises():
    bad = {'id': 's9', 'type': 'triangle', 'cx': 'x', 'cy': 1, 'size': 5, 'rot': 0}
    with pytest.raises(ValueError, match='must be a number'):
        validate_shape_spec(_spec(shapes=[bad]))


def test_bool_is_not_a_valid_coord():
    bad = {'id': 's9', 'type': 'triangle', 'cx': True, 'cy': 1, 'size': 5}
    with pytest.raises(ValueError, match='must be a number'):
        validate_shape_spec(_spec(shapes=[bad]))


def test_no_shape_of_target_type_raises():
    spec = _spec(target='triangle',
                 shapes=[_shape('s0', 'circle'), _shape('s1', 'square')])
    with pytest.raises(ValueError, match='no shape of target_type'):
        validate_shape_spec(spec)


# ── dispatch wiring through the plugin (DB-backed) ───────────────────────

@pytest.mark.django_db
def test_plugin_grade_answer_routes_shape_select():
    from classroom.models import Level
    from maths.models import Question
    from maths.plugin import MathsPlugin

    level, _ = Level.objects.get_or_create(
        level_number=982, defaults={'display_name': 'shape_select grading fixture'},
    )
    q = Question.objects.create(
        level=level,
        question_text='Colour all the triangles.',
        question_type=Question.SHAPE_SELECT,
        difficulty=1, points=2,
        shape_spec=_spec(),
    )

    plugin = MathsPlugin()
    correct = plugin.grade_answer(q.pk, {f'answer_{q.id}': _payload('s0', 's2', 's4')})
    wrong = plugin.grade_answer(q.pk, {f'answer_{q.id}': _payload('s0', 's1')})

    assert correct['is_correct'] is True
    assert correct['points_earned'] == 2        # question.points on success
    assert wrong['is_correct'] is False
    assert wrong['points_earned'] == 0
