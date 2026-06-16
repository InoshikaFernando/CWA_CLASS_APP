"""Tests for the procedural shape_select scene generator.

The generator is pure and seeded, so it needs no DB. Proves determinism (same
seed → identical scene), the exact target count, that every scene validates, and
that the derived target-id set is gradeable end-to-end.
"""
import pytest

from maths.geometry_grading import (
    grade_shape_select,
    shape_target_ids,
    validate_shape_spec,
)
from maths.shape_select_gen import generate_shape_scene


def test_same_seed_is_deterministic():
    a = generate_shape_scene(seed=42)
    b = generate_shape_scene(seed=42)
    assert a == b


def test_different_seed_changes_scene():
    a = generate_shape_scene(seed=1)
    b = generate_shape_scene(seed=2)
    assert a != b


def test_exact_target_count_and_total():
    spec = generate_shape_scene(target_type='triangle', target_count=3,
                                total_shapes=14, seed=7)
    assert len(spec['shapes']) == 14
    assert len(shape_target_ids(spec)) == 3
    assert spec['target_type'] == 'triangle'


def test_generated_scene_always_validates():
    for seed in range(10):
        validate_shape_spec(generate_shape_scene(seed=seed))  # must not raise


def test_generated_scene_grades_with_its_own_targets():
    spec = generate_shape_scene(target_type='circle', target_count=4,
                                total_shapes=12, seed=99)
    import json
    correct = json.dumps({'selected': sorted(shape_target_ids(spec))})
    assert grade_shape_select(spec, correct) is True


def test_unique_ids():
    spec = generate_shape_scene(total_shapes=15, seed=5)
    ids = [s['id'] for s in spec['shapes']]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize('kwargs', [
    {'target_type': 'hexagon'},                      # unknown type
    {'target_count': 0},                             # too few
    {'target_count': 99, 'total_shapes': 14},        # more targets than shapes
    {'distractors': ['triangle'], 'target_type': 'triangle'},  # no real distractor
])
def test_invalid_args_raise(kwargs):
    with pytest.raises(ValueError):
        generate_shape_scene(seed=1, **kwargs)
