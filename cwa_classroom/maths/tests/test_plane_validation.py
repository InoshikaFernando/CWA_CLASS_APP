"""Tests for plane_spec / graph_spec validation.

``validate_plane_spec`` / ``validate_graph_spec`` are pure (no DB). A DB-backed
test exercises ``Question.full_clean()`` to prove the model wires the validators
into ``clean()`` (so a malformed spec can't be saved through admin/import).
CPP graph/Cartesian question-type family.
"""
import pytest

from maths.geometry_grading import validate_plane_spec, validate_graph_spec


def _plane(points=None, **over):
    spec = {
        'bounds': {'xmin': -5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
        'mode': 'points',
        'target': {'points': points or [[3, -2]]},
    }
    spec.update(over)
    return spec


def _graph(**over):
    spec = {
        'title': 'Race',
        'x_axis': {'label': 'Time', 'unit': 'min', 'min': 0, 'max': 110, 'step': 10},
        'y_axis': {'label': 'Distance', 'unit': 'km', 'min': 0, 'max': 320, 'step': 65},
        'series': [{'points': [[20, 65], [40, 130], [60, 200]]}],
    }
    spec.update(over)
    return spec


# ── validate_plane_spec ──────────────────────────────────────────────────

def test_valid_points_plane_passes():
    validate_plane_spec(_plane())                  # must not raise


def test_valid_segments_plane_passes():
    validate_plane_spec(_plane(
        mode='segments',
        target={'segments': [{'x1': -2, 'y1': 1, 'x2': 0, 'y2': 4}]},
    ))


def test_valid_given_points_pass():
    validate_plane_spec(_plane(given_points=[[-2, 4], [0, 0]]))


@pytest.mark.parametrize('spec, msg', [
    ('not a dict', 'JSON object'),
    ({'mode': 'points', 'target': {'points': [[0, 0]]}}, 'bounds'),  # no bounds
])
def test_plane_structure_errors(spec, msg):
    with pytest.raises(ValueError) as exc:
        validate_plane_spec(spec)
    assert msg in str(exc.value)


def test_plane_bad_bounds_rejected():
    # xmin must be < xmax.
    bad = _plane()
    bad['bounds'] = {'xmin': 5, 'xmax': 5, 'ymin': -5, 'ymax': 5}
    with pytest.raises(ValueError, match='bounds'):
        validate_plane_spec(bad)


def test_plane_point_out_of_bounds_rejected():
    with pytest.raises(ValueError, match='outside'):
        validate_plane_spec(_plane(points=[[9, 9]]))


def test_plane_unknown_mode_rejected():
    with pytest.raises(ValueError, match='mode'):
        validate_plane_spec(_plane(mode='wiggle'))


def test_plane_empty_target_rejected():
    with pytest.raises(ValueError, match='non-empty'):
        validate_plane_spec(_plane(target={'points': []}))


def test_plane_non_integer_coord_rejected():
    with pytest.raises(ValueError, match='integers'):
        validate_plane_spec(_plane(points=[[1.5, 2]]))


def test_plane_bool_not_a_coord():
    with pytest.raises(ValueError, match='integers'):
        validate_plane_spec(_plane(points=[[True, 2]]))


# ── validate_graph_spec ──────────────────────────────────────────────────

def test_valid_graph_passes():
    validate_graph_spec(_graph())                  # must not raise


def test_graph_requires_axes():
    with pytest.raises(ValueError, match='x_axis'):
        validate_graph_spec(_graph(x_axis=None))


def test_graph_requires_series():
    with pytest.raises(ValueError, match='series'):
        validate_graph_spec(_graph(series=[]))


def test_graph_axis_min_must_be_below_max():
    bad = _graph()
    bad['y_axis'] = {'min': 100, 'max': 100}
    with pytest.raises(ValueError, match='less than'):
        validate_graph_spec(bad)


def test_graph_series_point_outside_range_rejected():
    with pytest.raises(ValueError, match='outside'):
        validate_graph_spec(_graph(series=[{'points': [[20, 65], [40, 999]]}]))


def test_graph_series_point_must_be_pair():
    with pytest.raises(ValueError, match='\\[x, y\\]'):
        validate_graph_spec(_graph(series=[{'points': [[20]]}]))


# ── model.clean() wiring (DB-backed) ─────────────────────────────────────

@pytest.mark.django_db
def test_model_clean_rejects_bad_plane_spec():
    from django.core.exceptions import ValidationError
    from classroom.models import Level
    from maths.models import Question

    level, _ = Level.objects.get_or_create(
        level_number=984, defaults={'display_name': 'plane validation fixture'},
    )
    q = Question(
        level=level, question_text='Plot it.',
        question_type=Question.PLOT_POINTS,
        plane_spec={'bounds': {'xmin': 5, 'xmax': 5, 'ymin': -5, 'ymax': 5},
                    'mode': 'points', 'target': {'points': [[0, 0]]}},
    )
    with pytest.raises(ValidationError) as exc:
        q.full_clean()
    assert 'plane_spec' in exc.value.error_dict


@pytest.mark.django_db
def test_model_clean_requires_plane_spec_for_plot_type():
    from django.core.exceptions import ValidationError
    from classroom.models import Level
    from maths.models import Question

    level, _ = Level.objects.get_or_create(
        level_number=984, defaults={'display_name': 'plane validation fixture'},
    )
    q = Question(level=level, question_text='Plot it.',
                 question_type=Question.PLOT_POINTS)
    with pytest.raises(ValidationError) as exc:
        q.full_clean()
    assert 'plane_spec' in exc.value.error_dict


@pytest.mark.django_db
def test_model_clean_requires_numeric_answer_for_read_graph():
    from django.core.exceptions import ValidationError
    from classroom.models import Level
    from maths.models import Question

    level, _ = Level.objects.get_or_create(
        level_number=984, defaults={'display_name': 'plane validation fixture'},
    )
    q = Question(level=level, question_text='Read off the value.',
                 question_type=Question.READ_GRAPH)
    with pytest.raises(ValidationError) as exc:
        q.full_clean()
    assert 'numeric_answer' in exc.value.error_dict
